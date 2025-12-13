import sys, os, importlib
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

mod = importlib.import_module('browser_use.ui.log_viewer')
print('Imported', mod.LogViewerApp)
