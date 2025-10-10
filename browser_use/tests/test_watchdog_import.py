import importlib


def test_default_action_watchdog_importable():
    mod = importlib.import_module('browser_use.browser.watchdogs.default_action_watchdog')
    assert hasattr(mod, 'DefaultActionWatchdog'), 'DefaultActionWatchdog not found in module'
    cls = getattr(mod, 'DefaultActionWatchdog')
    # ensure the class has our click implementation method
    assert hasattr(cls, '_click_element_node_impl'), '_click_element_node_impl not present on DefaultActionWatchdog'
    # the method should be a coroutine function
    import inspect

    assert inspect.iscoroutinefunction(cls._click_element_node_impl) or inspect.iscoroutinefunction(getattr(cls, '_click_element_node_impl', None))
