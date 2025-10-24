import importlib

mod = importlib.import_module('browser_use.ui.log_viewer')
print('Imported LogViewerApp:', getattr(mod, 'LogViewerApp', None))
