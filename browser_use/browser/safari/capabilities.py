"""Capability probing for the Safari real-profile backend."""

from __future__ import annotations

import platform
import plistlib
import socket
from dataclasses import dataclass, field
from pathlib import Path

MIN_SAFARI_VERSION = (26, 3, 1)
MIN_MACOS_MAJOR = 26
DEFAULT_SAFARI_HOST_SOCKET = Path.home() / '.browser-use' / 'safari' / 'host.sock'
SAFARI_APP_PATH = Path('/Applications/Safari.app')
SAFARI_INFO_PLIST = SAFARI_APP_PATH / 'Contents' / 'Info.plist'


def _parse_version(version: str | None) -> tuple[int, ...]:
	if not version:
		return ()
	parts: list[int] = []
	for token in version.split('.'):
		try:
			parts.append(int(token))
		except ValueError:
			break
	return tuple(parts)


def _is_version_at_least(version: str | None, minimum: tuple[int, ...]) -> bool:
	parsed = _parse_version(version)
	if not parsed:
		return False
	padded_parsed = parsed + (0,) * max(0, len(minimum) - len(parsed))
	padded_minimum = minimum + (0,) * max(0, len(parsed) - len(minimum))
	return padded_parsed >= padded_minimum


def _read_safari_version() -> str | None:
	if not SAFARI_INFO_PLIST.exists():
		return None

	try:
		with SAFARI_INFO_PLIST.open('rb') as fh:
			info = plistlib.load(fh)
		return info.get('CFBundleShortVersionString')
	except Exception:
		return None


def _read_macos_version() -> str | None:
	version = platform.mac_ver()[0]
	return version or None


def _socket_reachable(socket_path: Path) -> bool:
	if not socket_path.exists():
		return False

	client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	client.settimeout(0.2)
	try:
		client.connect(str(socket_path))
		return True
	except OSError:
		return False
	finally:
		client.close()


@dataclass(slots=True)
class SafariCapabilityReport:
	"""Local preflight report for Safari backend startup."""

	safari_installed: bool
	safari_version: str | None
	macos_version: str | None
	host_socket_path: Path
	host_reachable: bool
	supported: bool
	issues: list[str] = field(default_factory=list)

	def raise_for_unsupported(self) -> None:
		if self.supported:
			return
		raise RuntimeError(self.to_error_message())

	def to_error_message(self) -> str:
		issues = '\n'.join(f'  - {issue}' for issue in self.issues) or '  - Unknown Safari backend error'
		return (
			'Safari real-profile backend is unavailable.\n'
			f'Host socket: {self.host_socket_path}\n'
			f'Observed Safari: {self.safari_version or "not installed"}\n'
			f'Observed macOS: {self.macos_version or "unknown"}\n'
			f'{issues}\n\n'
			'This backend requires Safari 26.3.1+, macOS 26+, and the local Safari companion host.'
		)


def probe_safari_environment(socket_path: Path | None = None) -> SafariCapabilityReport:
	"""Inspect local Safari support and host availability."""

	socket_path = socket_path or DEFAULT_SAFARI_HOST_SOCKET
	safari_version = _read_safari_version()
	macos_version = _read_macos_version()
	issues: list[str] = []

	safari_installed = SAFARI_APP_PATH.exists()
	if not safari_installed:
		issues.append('Safari.app was not found at /Applications/Safari.app')

	if not _is_version_at_least(safari_version, MIN_SAFARI_VERSION):
		issues.append('Safari 26.3.1 or newer is required')

	if not _is_version_at_least(macos_version, (MIN_MACOS_MAJOR,)):
		issues.append('macOS 26 or newer is required')

	host_reachable = _socket_reachable(socket_path)
	if not host_reachable:
		issues.append('Safari companion host socket is not reachable')

	return SafariCapabilityReport(
		safari_installed=safari_installed,
		safari_version=safari_version,
		macos_version=macos_version,
		host_socket_path=socket_path,
		host_reachable=host_reachable,
		supported=not issues,
		issues=issues,
	)
