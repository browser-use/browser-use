"""Sends telemetry to PostHog from one background thread. Nothing on the agent path waits on the network
or the disk: run_started() and capture_run() are a dict update and a queue.put. The thread builds each event, gzips it
and POSTs it (3 s timeout, one retry); a failed send goes to an outbox the next process sends. At exit, events still
queued go to a detached sender process, so a one-shot script neither waits for the network nor loses its event.
ANONYMIZED_TELEMETRY=false: no thread, no network, no files."""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from browser_use.config import CONFIG
from browser_use.telemetry.views import BaseTelemetryEvent

logger = logging.getLogger(__name__)

POSTHOG_PROJECT_API_KEY = 'phc_F8JMNjW1i2KbGUTaW1unnDdLSPCoyc52SGRU0JecaUh'
POSTHOG_HOST = 'https://eu.i.posthog.com'
SEND_TIMEOUT_S = 3.0
MAX_BYTES = 64 * 1024  # per event, serialized; build levels shrink the per-step arrays and maps until it fits
LEVELS = ((200, 50), (100, 50), (50, 20), (0, 20))  # (steps kept, keys per map)
OUTBOX_FILES, OUTBOX_BYTES, OUTBOX_DAYS = 20, 512 * 1024, 7
MARKER_REFRESH_S = 30.0
CRASH_GRACE_S = 15 * 60  # a marker older than the run's timeout plus this is a crashed run, whatever its pid
EXIT_SENDER = (  # the detached process that sends what was still queued at exit: files in, deleted once sent
	'import sys, os, ssl, urllib.request\n'
	'try:\n'  # the OS verifier, as tls_context() in the sending process
	'    import truststore; ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n'
	'    extra = os.environ.get("SSL_CERT_FILE") or None, os.environ.get("SSL_CERT_DIR") or None\n'
	'    if any(extra): ctx.load_verify_locations(*extra)\n'  # a proxy's CA, as tls_context() loads it
	'except Exception:\n'
	'    ctx = None\n'
	'url = sys.argv[1]\n'
	'for path in sys.argv[2:]:\n'
	'    claimed = path[:-3] + f".{os.getpid()}.sending"\n'
	'    try: os.replace(path, claimed)\n'
	'    except OSError: continue\n'  # another sender has it
	'    try:\n'
	'        data = open(claimed, "rb").read()\n'
	'        headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}\n'
	'        urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=10, context=ctx).read()\n'
	'        os.remove(claimed)\n'
	'    except Exception:\n'
	'        try: os.replace(claimed, path)\n'
	'        except Exception: pass\n'
	'        break\n'  # offline: one timeout, the rest waits for the next process
)

_device_id: str | None = None
_device_id_lock = threading.Lock()
_tls: Any = None  # the thread's TLS context, made once under ProductTelemetry._lock (_online)


def telemetry_dir() -> Path:
	return CONFIG.BROWSER_USE_CONFIG_DIR / 'telemetry'


def get_or_create_device_id() -> str:
	"""Return the anonymous device id shared by telemetry"""
	global _device_id
	if _device_id:
		return _device_id
	# the telemetry thread and the exit handler build a one-shot script's event at once: one id per process
	with _device_id_lock:
		if not _device_id:
			_device_id = (
				os.environ.get('BROWSER_USE_DEVICE_ID') or _persisted_device_id() or _machine_fingerprint() or uuid.uuid4().hex
			)
	return _device_id


def _persisted_device_id() -> str | None:
	try:
		from uuid_extensions import uuid7str

		path = CONFIG.BROWSER_USE_CONFIG_DIR / 'device_id'
		if path.exists():
			return path.read_text(encoding='utf-8').strip() or None
		new_device_id = uuid7str()
		tmp = path.with_name(f'device_id.{os.getpid()}.tmp')
		tmp.write_text(new_device_id, encoding='utf-8')
		try:
			os.link(tmp, path)  # fails if another process stored its id first: every process keeps the first one
		except FileExistsError:
			pass
		except OSError:  # a filesystem without hard links
			if not path.exists():
				os.replace(tmp, path)
		finally:
			tmp.unlink(missing_ok=True)
		return path.read_text(encoding='utf-8').strip() or new_device_id
	except Exception:
		return None


def _machine_fingerprint() -> str | None:
	"""Hashed hardware-derived id"""
	import hashlib
	import socket

	node = uuid.getnode()
	if (node >> 40) & 0x01:  # multicast bit set: getnode() failed and returned a random id
		return None
	return 'bu_' + hashlib.sha256(f'browser-use:{node}:{socket.gethostname()}'.encode()).hexdigest()[:32]


@dataclass
class Job:
	"""One event to send. build(steps_kept, keys_per_map) returns its properties; it runs in the thread (or at exit)."""

	name: str
	build: Callable[[int, int], dict[str, Any]]
	run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
	timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
	event: dict[str, Any] | None = None  # built


def _alive(pid: int) -> bool:
	if sys.platform == 'win32':  # os.kill(pid, 0) would terminate it: ask Windows for its exit code instead
		try:
			import ctypes
			from ctypes import wintypes

			k = ctypes.WinDLL('kernel32', use_last_error=True)
			k.OpenProcess.restype = wintypes.HANDLE
			k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
			k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
			k.CloseHandle.argtypes = (wintypes.HANDLE,)
			handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
			if not handle:
				return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: someone else's; otherwise no such process
			try:
				code = wintypes.DWORD()
				return not k.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
			finally:
				k.CloseHandle(handle)
		except Exception:  # - unknown: alive, and the marker's age decides
			return True
	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except OSError:  # exists, owned by someone else
		return True
	return True


def _size(path: Path) -> int:
	try:
		return path.stat().st_size
	except OSError:  # claimed or sent meanwhile
		return 0


class ProductTelemetry:
	"""One per process (telemetry()). Reads ANONYMIZED_TELEMETRY on every call."""

	notice = True  # the one-line notice when the first event is queued; the browser-use CLI's stderr stays its own

	def __init__(self) -> None:
		self._reset()

	def _reset(self) -> None:
		self._lock = threading.Lock()  # a forked child's copy may be held by a parent thread that does not exist there
		self._pid = os.getpid()
		self._q: queue.Queue = queue.Queue()
		self._thread: threading.Thread | None = None
		self._pending: dict[str, Job] = {}  # queued or being sent
		# run_id -> (marker props, progress(), start time) of the runs in progress
		self._active: dict[str, tuple[Callable[[], dict], Callable[[], dict], float]] = {}
		self.send_failures = 0  # failed sends since the last success (outbox files left at start included)
		self.dropped = 0
		self._exiting = False  # set at exit: the thread claims no more files (_claim) and sends nothing (_online)
		self._handed: set[str] = set()  # run_ids of the events the exit handler wrote for its sender

	@property
	def enabled(self) -> bool:
		return CONFIG.ANONYMIZED_TELEMETRY

	def _own(self) -> None:
		"""A forked child (a multiprocessing pool on Linux) starts with none of the parent's thread, queue, runs or
		events. Called before a public method changes any state: resetting later wiped the run or event it had just added."""
		if self._pid != os.getpid():
			self._reset()

	def _start(self) -> None:
		self._own()
		if self._thread is not None and self._thread.is_alive():
			return
		with self._lock:
			if self._thread is None or not self._thread.is_alive():
				self._thread = threading.Thread(target=self._loop, name='browser-use-telemetry', daemon=True)
				self._thread.start()
				if not getattr(self, '_atexit', False):
					if self.notice:
						logger.info(
							'Using anonymized telemetry (no task text, results or page content; ANONYMIZED_TELEMETRY=false '
							'turns it off)'
						)
					atexit.register(self._at_exit)
					self._atexit = True

	# --- the agent path: never blocks, never raises ---

	def run_started(self, run_id: str, props: Callable[[], dict], progress: Callable[[], dict]) -> None:
		"""A crash marker for this run, written by the thread: a process killed mid-run still reports it (status crashed)
		the next time browser-use runs. props() is the event as known at the start, progress() adds the step count."""
		if not self.enabled:
			return
		try:
			self._own()
			self._active[run_id] = (props, progress, time.time())
			self._start()
			self._q.put_nowait(('mark', run_id))
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry: %s', e)

	def capture_run(self, job: Job) -> None:
		if not self.enabled:
			self._active.pop(job.run_id, None)
			return
		try:
			self._own()
			if len(self._pending) >= 100:  # a sender that cannot keep up: drop the oldest
				oldest = next(iter(self._pending))
				self._pending.pop(oldest, None)
				self.dropped += 1
				self.forget(oldest)  # its run ended: a marker left behind was reported as crashed by the next process
			self._pending[job.run_id] = job
			self._start()
			self._q.put_nowait(('event', job.run_id))
		except Exception as e:  # - telemetry never breaks a run
			logger.debug('telemetry: %s', e)

	def forget(self, run_id: str) -> None:
		"""A run whose event could not be built: drop its crash marker, so it is not reported as crashed."""
		self._own()
		if self._active.pop(run_id, None) is not None:
			self._q.put_nowait(('unmark', run_id))

	def capture(self, event: BaseTelemetryEvent) -> None:
		self.capture_run(Job(event.name, lambda steps, keys: event.properties))

	def stop(self, timeout: float = 15.0) -> bool:
		"""End the thread once it has done what it was doing (tests: no thread outlives the config dir and host of the
		test that started it). Never called on the agent path."""
		thread = self._thread
		if thread is None or not thread.is_alive():
			return True
		self._q.put_nowait(('stop', ''))
		thread.join(timeout)
		return not thread.is_alive()

	def flush(self, timeout: float = 5.0) -> bool:
		"""Wait until everything queued was sent or given up (tests). Never called on the agent path."""
		deadline = time.monotonic() + timeout
		while self._pending and time.monotonic() < deadline:
			time.sleep(0.01)
		return not self._pending

	# --- the thread ---

	def _loop(self) -> None:
		try:
			self._warm()
			self._send_outbox()
			self._send_crashed()
		except Exception as e:  # - a read-only disk, no network: carry on with the queue
			logger.debug('telemetry start: %s', e)
		while True:
			try:
				kind, run_id = self._q.get(timeout=MARKER_REFRESH_S)
			except queue.Empty:
				for run_id in list(self._active):
					self._mark(run_id)
				continue
			if kind == 'stop':
				return
			try:
				if kind == 'mark':
					self._mark(run_id)
				elif kind == 'unmark':
					self._unmark(run_id)
				elif (job := self._pending.get(run_id)) is not None:
					self._send(job)
					job = None  # this frame would keep the last run's job (its recorder and stats) until the next event
			except Exception as e:  # - never let one event stop the thread
				logger.debug('telemetry: %s', e)
				self._pending.pop(run_id, None)
				if kind == 'event':  # the run ended; its event could not be built or sent: not a crash
					self._unmark(run_id)

	def _warm(self) -> None:
		"""Cheap per-process facts, once. (Listing every installed distribution and CDP method here cost ~120 ms of CPU
		that, holding the GIL, slowed the first run by ~40 ms: the name checks are per name now, stats.py.)"""
		from browser_use.telemetry.stats import environment
		from browser_use.utils import get_browser_use_version, get_install_source

		environment()
		get_browser_use_version()
		get_install_source()

	def _event(self, job: Job) -> dict[str, Any]:
		"""job.event, built once: properties at the first level that fits MAX_BYTES."""
		if job.event is not None:
			return job.event
		from browser_use.utils import get_browser_use_version

		started = time.perf_counter_ns()
		props: dict[str, Any] = {}
		size = 0
		for steps, keys in LEVELS:
			props = job.build(steps, keys)
			size = len(json.dumps(props, separators=(',', ':'), default=str))
			if size <= MAX_BYTES:
				break
		if 'tel_build_us' in props:
			props.update(
				tel_build_us=(time.perf_counter_ns() - started) // 1000, tel_bytes=size, tel_prev_send_fail=self.send_failures
			)
		props.update({'$lib': 'browser-use', '$lib_version': get_browser_use_version()})
		job.event = {
			'event': job.name,
			'distinct_id': get_or_create_device_id(),
			'uuid': str(uuid.UUID(job.run_id)) if len(job.run_id) == 32 else job.run_id,
			'timestamp': job.timestamp,
			'properties': props,
		}
		return job.event

	@staticmethod
	def _body(events: list[dict]) -> bytes:
		body = {'api_key': POSTHOG_PROJECT_API_KEY, 'batch': events}
		return gzip.compress(json.dumps(body, separators=(',', ':'), default=str).encode(), compresslevel=6)

	@staticmethod
	def _post(data: bytes, timeout: float = SEND_TIMEOUT_S) -> bool:
		import urllib.request

		headers = {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}
		request = urllib.request.Request(f'{POSTHOG_HOST}/batch/', data, headers)
		try:
			with urllib.request.urlopen(request, timeout=timeout, context=_tls) as r:
				return 200 <= r.status < 300
		except Exception:
			return False

	def _online(self) -> bool:
		"""False once the process is exiting: the exit handler sends what is left. Else the TLS context exists: made here,
		under the lock the exit handler takes. Made by urlopen, its certificate loading ran in OpenSSL while the exit freed
		OpenSSL: a CLI call that exited as its thread began its first send segfaulted (0.6% of offline calls on macOS)."""
		global _tls
		with self._lock:
			if self._exiting:
				return False
			if _tls is None:
				from browser_use.utils import tls_context

				try:
					_tls = tls_context()
				except Exception:  # - urlopen makes its own, as before
					pass
			return True

	def _send(self, job: Job) -> None:
		data = self._body([self._event(job)])
		ok = self._online() and self._post(data)
		if not ok and not self._exiting:
			time.sleep(1)
			ok = self._online() and self._post(data)
		if ok:
			self.send_failures = 0
		else:
			self.send_failures += 1
			if job.run_id not in self._handed:  # else written again after the exit sender took it: sent twice
				self._to_outbox(data, job.run_id)
		self._pending.pop(job.run_id, None)
		self._unmark(job.run_id)

	# --- outbox, crash markers (all disk IO is in the thread or at exit; failures are ignored) ---

	def _to_outbox(self, data: bytes, name: str) -> Path | None:
		try:
			box = telemetry_dir() / 'outbox'
			box.mkdir(parents=True, exist_ok=True)
			files = self._outbox()
			claims = list(box.glob('*.sending'))  # being sent: back in the box if the send fails
			size = sum(map(_size, files + claims)) + len(data)
			while files and (len(files) + len(claims) >= OUTBOX_FILES or size > OUTBOX_BYTES):  # full: the oldest goes
				oldest = files.pop(0)
				size -= _size(oldest)
				oldest.unlink(missing_ok=True)
			if len(files) + len(claims) >= OUTBOX_FILES or size > OUTBOX_BYTES:
				return None
			path = box / f'{name}.gz'
			path.write_bytes(data)
			return path
		except OSError:
			return None

	def _outbox(self) -> list[Path]:
		"""The outbox's files to send, oldest first: a dead sender's claims are back, files past OUTBOX_DAYS deleted."""
		box = telemetry_dir() / 'outbox'
		if not box.is_dir():
			return []
		for claim in box.glob('*.sending'):  # <run_id>.<pid>.sending: a sender that died mid-send (killed, or this
			try:  # thread at exit) left its claim, and nothing else would ever send it
				pid = int(claim.name.split('.')[1])
				if pid != os.getpid() and not _alive(pid):
					os.replace(claim, box / (claim.name.split('.')[0] + '.gz'))
			except (OSError, ValueError, IndexError):
				continue
		files: list[tuple[float, Path]] = []
		for path in box.glob('*.gz'):
			try:
				mtime = path.stat().st_mtime
				if time.time() - mtime > OUTBOX_DAYS * 86400:
					path.unlink()
				else:
					files.append((mtime, path))
			except OSError:  # another process claimed it
				continue
		return [path for _, path in sorted(files, key=lambda e: e[0])]

	def _send_outbox(self) -> None:
		files = self._outbox()
		for i, path in enumerate(files):
			if path.stem in self._pending:  # this process's own queued event, written at exit: the exit sender sends it
				continue
			try:
				claimed = self._claim(path, 'sending') if self._online() else None  # another process may be sending the box
			except OSError:
				continue
			if claimed is None:
				return
			if self._post(claimed.read_bytes()):
				claimed.unlink(missing_ok=True)
			else:  # offline: the rest waits for the next process
				os.replace(claimed, path)
				self.send_failures += len(files) - i
				return

	def _claim(self, path: Path, kind: str) -> Path | None:
		"""path renamed to <stem>.<pid>.<kind>, or None once the process is exiting: a claim made then froze mid-send
		with the process (RC test: the CLI's thread took the outbox's oldest file on every call, so it was never sent)."""
		with self._lock:
			if self._exiting:
				return None
			claimed = path.with_suffix(f'.{os.getpid()}.{kind}')
			os.replace(path, claimed)
			return claimed

	def _marker(self, run_id: str) -> Path:
		return telemetry_dir() / 'inflight' / f'{run_id}.json'

	def _mark(self, run_id: str) -> None:
		entry = self._active.get(run_id)
		if entry is None:
			return
		props, progress, started = entry
		try:
			path = self._marker(run_id)
			path.parent.mkdir(parents=True, exist_ok=True)
			marker = {'pid': os.getpid(), 'started': started, 'updated': time.time(), **progress()}
			tmp = path.with_suffix('.tmp')
			tmp.write_text(json.dumps({**marker, 'props': props()}, default=str), encoding='utf-8')
			os.replace(tmp, path)
		except Exception as e:  # - a read-only disk, or a props()/progress() that raises: never ends the thread
			logger.debug('telemetry marker: %s', e)

	def _unmark(self, run_id: str) -> None:
		self._active.pop(run_id, None)
		try:
			self._marker(run_id).unlink(missing_ok=True)
		except OSError:
			pass

	def _send_crashed(self) -> None:
		"""Runs whose process died (killed, out of memory, a kernel restart) left a marker: send each as status crashed."""
		folder = telemetry_dir() / 'inflight'
		if not folder.is_dir():
			return
		for claim in folder.glob('*.crashed'):  # <run_id>.<pid>.crashed: a process killed while it sent this report
			try:
				pid = int(claim.name.split('.')[1])
				if pid != os.getpid() and not _alive(pid):
					os.replace(claim, folder / (claim.name.split('.')[0] + '.json'))
			except (OSError, ValueError, IndexError):
				continue
		for path in folder.glob('*.json'):
			try:
				marker = json.loads(path.read_text(encoding='utf-8'))
				props = dict(marker['props'])
				age = time.time() - float(marker.get('started') or 0)
				pid = int(marker.get('pid') or 0)
				if pid == os.getpid() or (_alive(pid) and age < float(props.get('timeout_s') or 0) + CRASH_GRACE_S):
					continue
				claimed = self._claim(path, 'crashed') if self._online() else None  # one process sends it
			except (OSError, ValueError, KeyError, TypeError):
				continue
			if claimed is None:
				return
			updated = float(marker.get('updated') or marker.get('started') or 0)
			props.update(
				status='crashed',
				steps=int(marker.get('steps') or 0),
				ms_total=max(0, int((updated - float(marker.get('started') or updated)) * 1000)),
			)
			job = Job('agent_event', lambda steps, keys, props=props: props, run_id=path.stem)
			if self._post(self._body([self._event(job)])):
				claimed.unlink(missing_ok=True)
			else:
				os.replace(claimed, path)

	def _at_exit(self) -> None:
		"""Events still queued go to a detached sender, so exit does not wait for the network (~10 ms to spawn). The
		outbox earlier processes left goes with them: a short-lived process (the CLI) exits before its thread sends it."""
		try:
			if os.getpid() != self._pid:
				return
			locked = self._lock.acquire(timeout=0.5)  # held by the thread for one rename or its TLS setup (~10 ms)
			self._exiting = True
			jobs = list(self._pending.values())
			self._handed = {job.run_id for job in jobs}
			if locked:
				self._lock.release()
			backlog = self._outbox()  # also with nothing queued: a run killed before its event still hands the outbox on
			files = [self._to_outbox(self._body([self._event(job)]), job.run_id) for job in jobs]
			self._handed = {job.run_id for job, f in zip(jobs, files) if f is not None}  # one not written: the thread's
			for job in jobs:
				self._unmark(job.run_id)
			files = [str(f) for f in files if f is not None]
			files += [str(f) for f in backlog]
			if not files:
				return
			kw: dict[str, Any] = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
			if sys.platform == 'win32':
				kw['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW
			else:
				kw['start_new_session'] = True
			# if this fails (no subprocesses here), the files stay in the outbox and the next process sends them
			subprocess.Popen([sys.executable, '-I', '-c', EXIT_SENDER, f'{POSTHOG_HOST}/batch/', *files], **kw)
		except Exception as e:  # - exit must never fail because of telemetry
			logger.debug('telemetry at exit: %s', e)


_instance: ProductTelemetry | None = None


def telemetry() -> ProductTelemetry:
	global _instance
	if _instance is None:
		_instance = ProductTelemetry()
	return _instance


if not TYPE_CHECKING:  # pyright would accept any name imported from here
	from browser_use.legacy import removed_names

	__getattr__ = removed_names(__name__)  # a 0.x name raises the removed error naming its 1.0 answer
