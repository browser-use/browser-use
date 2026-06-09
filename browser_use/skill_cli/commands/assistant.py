"""Structured research/recommendation assistant for the CLI daemon."""

from typing import Any

from browser_use.assistant.research import BrowserResearchAssistant, ResearchAssistantConfig, render_report
from browser_use.skill_cli.sessions import SessionInfo


async def handle(session: SessionInfo, params: dict[str, Any]) -> dict[str, Any]:
	"""Run the browser research assistant against the current browser session."""
	task = params.get('task')
	if not task:
		return {'error': 'Task is required'}

	config = ResearchAssistantConfig(
		task=task,
		model=params.get('model'),
		locale=params.get('locale'),
		max_steps=params.get('max_steps', 18),
		llm_timeout=params.get('llm_timeout', 120),
		max_actions_per_step=params.get('max_actions_per_step', 2),
		max_recommendations=params.get('max_recommendations', 3),
		use_vision=params.get('vision', False),
		shopping_sites=params.get('shopping_sites', []) or [],
		review_sites=params.get('review_sites', []) or [],
		official_sites=params.get('official_sites', []) or [],
		web_sites=params.get('web_sites', []) or [],
	)

	cdp_url = (
		session.browser_session.cdp_url
		or session.cdp_url
		or session.browser_session.browser_profile.cdp_url
	)
	assistant = BrowserResearchAssistant(config)
	artifacts = await assistant.run(cdp_url=cdp_url)

	return {
		'_raw_text': render_report(artifacts.report),
		'task_plan': artifacts.task_plan.model_dump(mode='json'),
		'stage_results': [stage.model_dump(mode='json') for stage in artifacts.stage_results],
		'candidate_catalog': [candidate.model_dump(mode='json') for candidate in artifacts.candidate_catalog],
		'report': artifacts.report.model_dump(mode='json'),
		'research_dossier': artifacts.research_dossier,
	}
