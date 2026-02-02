import json
import re
from pathlib import Path


def _load_tool_spec() -> list[str]:
    spec_path = Path(__file__).resolve().parents[1] / "fixtures" / "browser_use_tool_spec.json"
    return json.loads(spec_path.read_text())


def _extract_tool_actions() -> list[str]:
    service_path = Path(__file__).resolve().parents[2] / "browser_use" / "tools" / "service.py"
    lines = service_path.read_text().splitlines()
    actions: list[str] = []
    for idx, line in enumerate(lines):
        if "@self.registry.action" not in line:
            continue
        for j in range(idx + 1, min(idx + 30, len(lines))):
            match = re.search(r"async def ([a-zA-Z_][\w]*)", lines[j])
            if match:
                actions.append(match.group(1))
                break
    return sorted(set(actions))


def test_browser_use_tool_spec_matches_registry() -> None:
    expected = _load_tool_spec()
    actual = _extract_tool_actions()
    assert actual == expected, f"Tool registry mismatch. expected={expected}, actual={actual}"
