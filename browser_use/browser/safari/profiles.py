"""Persistent mapping between user-facing Safari profile labels and host profile identifiers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_SAFARI_PROFILE_STORE = Path.home() / '.browser-use' / 'safari' / 'profiles.json'


@dataclass(slots=True)
class SafariProfileBinding:
	"""Local mapping for a Safari profile label."""

	label: str
	profile_identifier: str
	last_seen_target_id: str | None = None


class SafariProfileStore:
	"""Simple JSON-backed profile binding store."""

	def __init__(self, path: Path | None = None) -> None:
		self.path = path or DEFAULT_SAFARI_PROFILE_STORE

	def list_bindings(self) -> list[SafariProfileBinding]:
		return [
			SafariProfileBinding(**item)
			for item in self._read().get('bindings', [])
			if item.get('label') and item.get('profile_identifier')
		]

	def get_identifier(self, label: str) -> str | None:
		for binding in self.list_bindings():
			if binding.label == label:
				return binding.profile_identifier
		return None

	def get_binding(self, label: str) -> SafariProfileBinding | None:
		for binding in self.list_bindings():
			if binding.label == label:
				return binding
		return None

	def get_label(self, profile_identifier: str) -> str | None:
		for binding in self.list_bindings():
			if binding.profile_identifier == profile_identifier:
				return binding.label
		return None

	def bind(self, label: str, profile_identifier: str, *, last_seen_target_id: str | None = None) -> SafariProfileBinding:
		bindings = self.list_bindings()
		new_binding = SafariProfileBinding(
			label=label,
			profile_identifier=profile_identifier,
			last_seen_target_id=last_seen_target_id,
		)

		updated = False
		for index, binding in enumerate(bindings):
			if binding.label == label or binding.profile_identifier == profile_identifier:
				bindings[index] = new_binding
				updated = True
				break

		if not updated:
			bindings.append(new_binding)

		self._write(bindings)
		return new_binding

	def _read(self) -> dict:
		if not self.path.exists():
			return {'bindings': []}

		try:
			return json.loads(self.path.read_text())
		except (json.JSONDecodeError, OSError):
			return {'bindings': []}

	def _write(self, bindings: list[SafariProfileBinding]) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps({'bindings': [asdict(binding) for binding in bindings]}, indent=2))
