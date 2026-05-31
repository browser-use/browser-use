"""Unit tests for ActionModel.set_index() edge cases."""

from browser_use.tools.registry.views import ActionModel


def test_set_index_no_fields_does_not_raise():
    """ActionModel subclass with no fields set must not raise StopIteration."""

    class DoneParams(ActionModel):
        pass

    m = DoneParams()
    m.set_index(0)  # must complete without raising StopIteration
