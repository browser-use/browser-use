"""Root conftest — ensures the local browser_use source takes priority over any editable install
from a sibling venv, so new submodules (e.g. browser_use.research) are always discoverable."""

import sys
from pathlib import Path

# Insert project root at index 0 so local source wins over any venv editable-install .pth
_project_root = str(Path(__file__).parent)
if _project_root not in sys.path:
	sys.path.insert(0, _project_root)
