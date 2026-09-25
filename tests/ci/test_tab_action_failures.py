"""Regression tests for tab actions reporting their real outcome."""

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools


class _BrowserWithInvalidTab:
    async def get_target_id_from_tab_id(self, tab_id: str) -> str:
        raise ValueError(f"No TargetID found ending in tab_id=...{tab_id}")


async def test_switch_reports_invalid_tab_id_as_failure() -> None:
    tools = Tools()
    action = tools.registry.registry.actions["switch"].function

    result = await action(
        params=tools.registry.registry.actions["switch"].param_model(tab_id="dead"),
        browser_session=_BrowserWithInvalidTab(),
    )

    assert isinstance(result, ActionResult)
    assert result.success is False
    assert result.error == "No TargetID found ending in tab_id=...dead"
    assert "Failed to switch to tab #dead" in (result.extracted_content or "")
