"""Agent(sandbox=True): the REPL worker reads and writes only what it needs (MIGRATING.md "Trust model").

Read-write: the workspace (the worker's state dir, its private temp dir and downloads are inside it). Read-only: the
Python installation and the packages it imports, system libraries, /etc (certificates, DNS), /proc and /sys. Everything
else, your home dir included (~/.ssh, ~/.config/browser-harness/auth.json, the .env next to your script, other repos),
cannot be opened. Other processes' environments cannot be read (/proc/<pid>/environ, ps -E; macOS: see below).

Linux: Landlock (5.13+, the best ABI the kernel has), applied by the worker to itself before it runs anything
(restrict), with no_new_privs; cell subprocesses inherit it. A Landlock domain cannot ptrace, and so cannot read
/proc/<pid>/environ of, processes outside it; ABI 6 also scopes signals and abstract Unix sockets to the domain.
macOS: sandbox-exec with a Seatbelt profile written per run (profile): deny by default, process-info only for the
sandbox itself. Windows: not available (check raises).

Not covered: the network (any host; use Browser(allowed_domains=...) for the browser and a container for egress), and
the browser itself: a local browser (Browser('chromium'), 'chrome', cdp_url) runs outside the sandbox and model CDP can
make it open local files (file:// URLs, DOM.setFileInputFiles). Linux cannot filter Unix sockets by path: the worker
can still connect to sockets your user can (another browser-harness daemon, /var/run/docker.sock). macOS: Seatbelt does
not mediate sysctl(KERN_PROCARGS2), so other processes' start-up environment stays readable.
"""

from __future__ import annotations

import ctypes
import importlib.machinery
import json
import os
import site
import sys
import sysconfig
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

SANDBOX_EXEC = '/usr/bin/sandbox-exec'
LINUX_READ = ('/usr', '/lib', '/lib32', '/lib64', '/libx32', '/bin', '/sbin', '/etc', '/proc', '/sys')
LINUX_DEVICES = ('/dev/null', '/dev/zero', '/dev/full', '/dev/random', '/dev/urandom', '/dev/tty')
MAC_READ = ('/usr', '/bin', '/sbin', '/System', '/Library/Apple', '/private/etc', '/private/var/db/timezone', '/opt/homebrew')
MAC_DEVICES = ('/dev/null', '/dev/zero', '/dev/random', '/dev/urandom', '/dev/tty', '/dev/dtracehelper', '/dev/autofs_nowait')
MAC_SOCKETS = ('/private/var/run/mDNSResponder',)  # DNS
MAC_SERVICES = (  # getpwuid, proxy settings (urllib's _scproxy), TLS trust (http_get), notifications, logging
	'com.apple.system.opendirectoryd.libinfo',
	'com.apple.trustd',
	'com.apple.trustd.agent',
	'com.apple.SystemConfiguration.configd',
	'com.apple.system.notification_center',
	'com.apple.system.logger',
	'com.apple.logd',
	'com.apple.diagnosticd',
)
CA_ENV = ('SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE')


@dataclass(frozen=True)
class Policy:
	"""What the worker may touch. write: read-write trees. read: read-only trees (read, list, execute). list: dirs
	whose entries can be listed but whose files cannot be read (the root of an editable install, which holds its .env).
	sockets: Unix sockets it may connect to (macOS only; Linux cannot filter them)."""

	write: tuple[str, ...]
	read: tuple[str, ...]
	list: tuple[str, ...] = ()
	sockets: tuple[str, ...] = ()

	def to_json(self) -> str:
		return json.dumps(asdict(self))

	@classmethod
	def from_json(cls, text: str) -> Policy:
		d = json.loads(text)
		return cls(**{k: tuple(v) for k, v in d.items()})


def landlock_abi() -> int:
	"""The kernel's Landlock ABI version; 0 when it has none (older than 5.13, or landlock not in the LSM list)."""
	if not sys.platform.startswith('linux'):
		return 0
	try:
		libc = ctypes.CDLL(None, use_errno=True)
		libc.syscall.restype = ctypes.c_long
		abi = libc.syscall(_SYS_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(1))  # ..._VERSION
	except (OSError, AttributeError):
		return 0
	return max(int(abi), 0)


def check() -> None:
	"""Raise before any browser starts when this OS cannot sandbox the worker: never run it unsandboxed instead."""
	if sys.platform == 'win32':
		raise ValueError(
			'Agent(sandbox=True) is not available on Windows yet (no Landlock or Seatbelt equivalent is wired up): run '
			'untrusted tasks in a container or VM, or pass sandbox=False.'
		)
	if sys.platform == 'darwin':
		if not os.path.exists(SANDBOX_EXEC):
			raise ValueError(f'Agent(sandbox=True) needs {SANDBOX_EXEC}, which this Mac does not have.')
		return
	if not sys.platform.startswith('linux'):
		raise ValueError(f'Agent(sandbox=True) supports Linux and macOS, not {sys.platform}.')
	if _SYS_CREATE_RULESET is None:
		raise ValueError(f'Agent(sandbox=True): Landlock syscalls are not known for this CPU ({os.uname().machine}).')
	if landlock_abi() < 1:
		raise ValueError(
			'Agent(sandbox=True) needs Landlock (Linux 5.13+ with landlock in the LSM list, see '
			'/sys/kernel/security/lsm), which this kernel does not offer: the worker would run unsandboxed. Run in a '
			'container or VM, or pass sandbox=False.'
		)


def check_workspace(workspace: str | os.PathLike) -> None:
	"""The workspace is read-write in the sandbox: refuse one that holds the home dir (or is the filesystem root), or
	the Python code the worker runs (policy raises)."""
	from browser_use.repl.session import worker_env

	ws, home = _real(workspace), _real('~')
	if ws == '/' or ws == home or home.startswith(ws.rstrip('/') + '/'):
		raise ValueError(
			f'Agent(sandbox=True, workspace={str(workspace)!r}): the workspace is readable and writable in the sandbox, '
			'so it must not contain your home dir. Use a dedicated dir.'
		)
	policy(Path(workspace), worker_env())


def _real(path: str | os.PathLike) -> str:
	return os.path.realpath(os.path.expanduser(str(path)))


def _pth_dirs() -> list[str]:
	"""Dirs the site .pth files add to sys.path (editable installs), as the worker's interpreter sees them."""
	dirs = []
	sitedirs = [*site.getsitepackages(), *([site.getusersitepackages()] if site.ENABLE_USER_SITE else [])]
	for sitedir in sitedirs:
		try:
			names = sorted(n for n in os.listdir(sitedir) if n.endswith('.pth'))
		except OSError:
			continue
		for name in names:
			try:
				lines = Path(sitedir, name).read_text(encoding='utf-8', errors='replace').splitlines()
			except OSError:
				continue
			for line in lines:
				line = line.strip()
				if line and not line.startswith(('#', 'import ', 'import\t')):
					full = os.path.join(sitedir, line)
					if os.path.isdir(full):
						dirs.append(full)
	return dirs


def _importable(d: str) -> list[str]:
	"""What import can load from sys.path dir d: packages, modules, extension modules and their metadata, not the
	.env, .git or data next to them."""
	suffixes = (*importlib.machinery.all_suffixes(), '.dist-info', '.egg-info')
	try:
		names = os.listdir(d)
	except OSError:
		return []
	return [os.path.join(d, n) for n in names if n.endswith(suffixes) or os.path.isfile(os.path.join(d, n, '__init__.py'))]


def _inside(path: str, roots: list[str]) -> bool:
	return any(path == r or path.startswith(r.rstrip('/') + '/') for r in roots)


def policy(workspace: Path, env: dict[str, str], sockets: list[str] | None = None) -> Policy:
	"""The worker's policy, computed in the parent (same interpreter, same packages)."""
	import browser_harness

	import browser_use

	darwin = sys.platform == 'darwin'
	python = [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]
	python += [p for k in ('stdlib', 'platstdlib', 'purelib', 'platlib') if (p := sysconfig.get_path(k))]
	python += [*site.getsitepackages(), os.path.dirname(_real(sys.executable))]
	if site.ENABLE_USER_SITE and os.path.isdir(site.getusersitepackages()):
		python.append(site.getusersitepackages())
	python += [p for p in env.get('PYTHONPATH', '').split(os.pathsep) if os.path.isabs(p)]  # '.': the parent's cwd
	python += [env[k] for k in CA_ENV if env.get(k)]
	read = [_real(p) for p in [*(MAC_READ if darwin else LINUX_READ), *python]]
	listed: list[str] = ['/'] if darwin else []  # dyld reads the root dir's entries at exec (SIGABRT without)
	for d in map(_real, _pth_dirs()):  # an editable checkout's root holds its .env: list it, read what imports from it
		listed.append(d)
		read += _importable(d)
	for m in (browser_use, browser_harness):
		if m.__file__:
			read.append(str(Path(m.__file__).resolve().parent))
	if not darwin and os.path.exists('/etc/resolv.conf'):
		read.append(_real('/etc/resolv.conf'))  # often a link into /run (systemd-resolved)
	read = [p for p in dict.fromkeys(read) if os.path.exists(p)]
	read = [p for p in read if not _inside(p, [r for r in read if r != p])]  # drop paths inside another
	write = [_real(workspace)]
	if held := [p for p in [*read, *listed] if _inside(p, write)]:  # workspace='.' in a project with its .venv
		raise ValueError(
			f'Agent(sandbox=True, workspace={str(workspace)!r}): the workspace holds {held[0]}, which the worker loads '
			'Python from: writable in the sandbox, a cell could plant code there that runs before the next worker '
			'confines itself. Use a dedicated dir.'
		)
	devices = [p for p in (MAC_DEVICES if darwin else LINUX_DEVICES) if os.path.exists(p)]
	return Policy(
		write=tuple([*write, *devices]),
		read=tuple(read),
		list=tuple(dict.fromkeys(listed)),
		sockets=tuple(_real(s) for s in [*(sockets or []), *(MAC_SOCKETS if darwin else ())]),
	)


# -- Linux: Landlock -------------------------------------------------------------------------------------------------

# landlock_create_ruleset; add_rule and restrict_self follow it. One number on every architecture but mips and alpha.
_SYSCALLS: dict[str, int] = dict.fromkeys(
	('x86_64', 'aarch64', 'arm64', 'riscv64', 'ppc64le', 'ppc64', 's390x', 'armv7l', 'i686', 'i386'), 444
)
_SYS_CREATE_RULESET = _SYSCALLS.get(os.uname().machine) if hasattr(os, 'uname') else None
_PR_SET_NO_NEW_PRIVS = 38
_RULE_PATH_BENEATH = 1
# LANDLOCK_ACCESS_FS_*: EXECUTE, WRITE_FILE, READ_FILE, READ_DIR, REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR, MAKE_REG,
# MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM (ABI 1), REFER (2), TRUNCATE (3), IOCTL_DEV (5)
_EXECUTE, _WRITE_FILE, _READ_FILE, _READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
_FS_ABI = {1: (1 << 13) - 1, 2: (1 << 14) - 1, 3: (1 << 15) - 1, 4: (1 << 15) - 1, 5: (1 << 16) - 1}
_FILE_ONLY = _EXECUTE | _WRITE_FILE | _READ_FILE | (1 << 14) | (1 << 15)  # the rights a rule on a non-directory may hold
_SCOPE_ABSTRACT_UNIX_SOCKET, _SCOPE_SIGNAL = 1 << 0, 1 << 1  # ABI 6


class _RulesetAttr(ctypes.Structure):
	_fields_ = [('handled_access_fs', ctypes.c_uint64), ('handled_access_net', ctypes.c_uint64), ('scoped', ctypes.c_uint64)]


class _PathBeneath(ctypes.Structure):
	_pack_ = 1
	_fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]


def restrict(p: Policy) -> int:
	"""Landlock this process (and every process it starts) to p. Call before any other thread starts: Landlock binds
	the calling thread only. Returns the ABI used; raises OSError when the kernel refuses (never runs unsandboxed)."""
	if threading.active_count() != 1:
		raise RuntimeError('sandbox.restrict() must run before any other thread starts')
	abi = landlock_abi()
	create = _SYS_CREATE_RULESET
	if abi < 1 or create is None:
		raise OSError('Landlock is not available on this kernel')
	libc = ctypes.CDLL(None, use_errno=True)
	libc.syscall.restype = ctypes.c_long
	libc.prctl.restype = ctypes.c_int
	fs = _FS_ABI[min(abi, 5)]
	attr = _RulesetAttr(handled_access_fs=fs, handled_access_net=0, scoped=0)
	size = ctypes.sizeof(ctypes.c_uint64)  # ABI 1-3: handled_access_fs only
	if abi >= 6:
		attr.scoped = _SCOPE_ABSTRACT_UNIX_SOCKET | _SCOPE_SIGNAL
		size = ctypes.sizeof(attr)
	elif abi >= 4:
		size = 2 * ctypes.sizeof(ctypes.c_uint64)
	ruleset = libc.syscall(create, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
	if ruleset < 0:
		raise OSError(ctypes.get_errno(), f'landlock_create_ruleset: {os.strerror(ctypes.get_errno())}')
	try:
		read = _EXECUTE | _READ_FILE | _READ_DIR
		for paths, access in ((p.write, fs), (p.read, read), (p.list, _READ_DIR)):
			for path in paths:
				_add_rule(libc, create + 1, ruleset, path, access)
		if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
			raise OSError(ctypes.get_errno(), 'prctl(PR_SET_NO_NEW_PRIVS)')
		if libc.syscall(create + 2, ctypes.c_int(ruleset), ctypes.c_uint32(0)) != 0:  # restrict_self
			raise OSError(ctypes.get_errno(), f'landlock_restrict_self: {os.strerror(ctypes.get_errno())}')
	finally:
		os.close(ruleset)
	return abi


def _add_rule(libc, add_rule: int, ruleset: int, path: str, access: int) -> None:
	try:
		fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
	except OSError:  # gone since the parent listed it
		return
	try:
		if not os.path.isdir(path):
			access &= _FILE_ONLY
			if not access:
				return
		rule = _PathBeneath(allowed_access=access, parent_fd=fd)
		r = libc.syscall(
			add_rule,
			ctypes.c_int(ruleset),
			ctypes.c_int(_RULE_PATH_BENEATH),
			ctypes.byref(rule),
			ctypes.c_uint32(0),
		)
		if r != 0:
			raise OSError(ctypes.get_errno(), f'landlock_add_rule {path}: {os.strerror(ctypes.get_errno())}')
	finally:
		os.close(fd)


# -- macOS: Seatbelt -------------------------------------------------------------------------------------------------


def _sb(path: str) -> str:
	return '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'


def profile(p: Policy) -> str:
	"""The Seatbelt (SBPL) profile sandbox-exec runs the worker under. Metadata (stat) stays readable everywhere, as
	path lookups need it; file contents only under p.read and p.write."""
	read = ' '.join(f'(subpath {_sb(x)})' for x in p.read)
	write = ' '.join(f'(subpath {_sb(x)})' for x in p.write if not x.startswith('/dev/'))
	devices = ' '.join(f'(literal {_sb(x)})' for x in p.write if x.startswith('/dev/'))
	listed = ' '.join(f'(literal {_sb(x)})' for x in p.list)
	sockets = ' '.join(f'(remote unix-socket (path-literal {_sb(x)}))' for x in p.sockets)
	services = ' '.join(f'(global-name {_sb(x)})' for x in MAC_SERVICES)
	rules = [
		'(version 1)',
		'(deny default)',
		'(allow process-exec)',
		'(allow process-fork)',
		'(allow signal (target same-sandbox))',
		'(allow process-info* (target same-sandbox))',
		'(allow sysctl-read)',
		'(allow user-preference-read)',
		'(allow ipc-posix-sem)',
		'(allow pseudo-tty)',
		f'(allow mach-lookup {services})',
		'(allow file-read-metadata)',
		f'(allow file-read* {read})',
		f'(allow file-read* file-write* {write})',
		# openpty(): only ptys the sandbox opened (as Codex): /dev/ttys* also holds your other terminals' keystrokes
		'(allow file-read* file-write* file-ioctl (literal "/dev/ptmx"))',
		'(allow file-read* file-write* file-ioctl (require-all (regex #"^/dev/ttys[0-9]+$") (extension "com.apple.sandbox.pty")))',
		'(allow system-socket)',
		f'(allow network-outbound (remote ip "*:*") {sockets})',
		'(allow network-inbound (local ip "*:*"))',
		'(allow network-bind (local ip "*:*"))',
	]
	if devices:
		rules.append(f'(allow file-read* file-write-data file-ioctl {devices})')
	if listed:
		rules.append(f'(allow file-read-data {listed})')
	return '\n'.join(rules) + '\n'


def is_sandboxed() -> bool:
	"""macOS: whether this process runs under a Seatbelt profile (libsystem_sandbox's sandbox_check)."""
	try:
		lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
		lib.sandbox_check.restype = ctypes.c_int
		lib.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
		return lib.sandbox_check(os.getpid(), None, 0) == 1
	except (OSError, AttributeError):
		return False


def self_test(p: Policy) -> None:
	"""After restricting: a dir outside the policy (the root dir, else the home dir) must not list. Raises when it does
	(fail closed)."""

	def allowed(d: str) -> bool:
		return _inside(d, [*p.read, *p.write]) or d in p.list  # a listed dir is that dir alone

	probe = next((d for d in ('/', _real('~')) if os.path.isdir(d) and not allowed(d)), None)
	if probe is None:
		return
	try:
		os.listdir(probe)
	except PermissionError:
		return
	raise RuntimeError(f'sandbox is not in effect: {probe} is readable')
