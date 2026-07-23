"""CustomToolset — lightweight tool collection for user-defined actions only.

Inherits BaseToolset with no built-in actions pre-registered.
Register your own actions via the ``@action`` decorator:

.. code-block:: python

    from browser_use.tools.custom_toolset import CustomToolset
    from browser_use.agent.views import ActionResult

    tools = CustomToolset()


    @tools.action('Say hello')
    async def greet(name: str, browser_session) -> ActionResult:
        return ActionResult(extracted_content=f'Hello, {name}!')

No mandatory methods to implement — just decorate your functions.
"""

from browser_use.tools.base import BaseToolset

__all__ = ['CustomToolset']


class CustomToolset(BaseToolset):
	"""A lightweight toolset for user-defined actions.

	No built-in actions are registered. Use the ``action`` decorator
	to register your own callables.
	"""
