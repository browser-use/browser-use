"""
Opt-in CrawlDex preflight and reporting for browser-use.

Install:
    pip install "crawldex-report>=0.1.1"

Environment:
    CRAWLDEX_REPORT_URL=https://crawldex.com/api/v1/runs
    CRAWLDEX_API_ORIGIN=https://crawldex.com
    CRAWLDEX_AGENT_KEY=aa_agent_...

The integration is intentionally fail-open: if CrawlDex is unavailable, the
agent task continues and the warning can be logged by the caller. Reports are
redacted and score-neutral until CrawlDex verifies the reporter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from browser_use import Agent
from crawldex_report import CrawlDexReporter
from crawldex_report.browser_use import report_browser_use_result

Outcome = Literal["success", "success_with_handoff", "partial", "blocked", "failed", "abandoned"]


@dataclass
class CrawlDexConfig:
    crawldex: bool = False
    site: str = ""
    task: str = ""
    agent_key: str | None = None
    report_url: str | None = None


async def run_with_crawldex(
    *,
    agent: Agent,
    prompt: str,
    config: CrawlDexConfig,
    outcome: Outcome,
    friction: list[str] | None = None,
    evidence_signals: list[str] | None = None,
) -> Any:
    """Run a browser-use task with optional CrawlDex preflight/reporting."""

    reporter = CrawlDexReporter(
        report_url=config.report_url,
        agent_key=config.agent_key,
    )

    if config.crawldex:
        preflight = await reporter.preflight(config.site, config.task)
        if preflight.warning:
            print(f"CrawlDex preflight warning: {preflight.warning}")
        recommendation = preflight.recommendation or preflight.verdict
        if recommendation in {"avoid_until_fresh_evidence", "collect_evidence_first"}:
            print(f"CrawlDex recommends caution for {config.site} {config.task}: {recommendation}")

    result = await agent.run(prompt)

    if config.crawldex:
        await report_browser_use_result(
            reporter=reporter,
            result=result,
            site=config.site,
            task=config.task,
            agent_profile={
                "stack": "browser-use",
                "browser_runtime": "chromium",
            },
            outcome=outcome,
            friction=friction or [],
            evidence_signals=evidence_signals or ["task_finished_without_private_trace_upload"],
        )

    return result


async def example(agent: Agent) -> Any:
    return await run_with_crawldex(
        agent=agent,
        prompt="Cancel the trial and stop before the final confirmation step.",
        config=CrawlDexConfig(
            crawldex=True,
            site="example.com",
            task="subscriptions.cancel",
        ),
        outcome="success_with_handoff",
        friction=["final_confirmation_user_present"],
        evidence_signals=[
            "subscription_settings_visible",
            "cancel_flow_reached",
            "handoff_before_final_submit",
        ],
    )
