from browser_use.agent.runtime import BrowserContext, BrowserSkillRegistry, SkillItem, TaskItem


def test_default_skill_registry_loads_relevant_interaction_skills_only() -> None:
	registry = BrowserSkillRegistry.default()

	selected = registry.select(task='Upload a receipt PDF through the checkout iframe', url='https://example.com/checkout')
	names = [skill.name for skill in selected]

	assert names == ['downloads', 'iframes', 'uploads']
	assert 'dialogs' not in names


def test_skill_registry_can_select_by_failure_or_explicit_name() -> None:
	registry = BrowserSkillRegistry.default()

	by_failure = registry.select(recent_failures=['Element not clickable inside shadow root'])
	by_name = registry.select(explicit_names=['dialogs'])

	assert [skill.name for skill in by_failure] == ['shadow_dom']
	assert [skill.name for skill in by_name] == ['dialogs']


def test_skill_items_render_as_typed_context_without_base_prompt_bloat() -> None:
	registry = BrowserSkillRegistry.default()
	skills = registry.select(task='Choose an option from the dropdown', max_skills=1)
	context = BrowserContext(items=[TaskItem(text='Choose shipping'), *[SkillItem(**skill.model_dump()) for skill in skills]])

	rendered = context.render()
	round_tripped = BrowserContext.model_validate(context.model_dump(mode='json'))

	assert '<user_request>' in rendered
	assert '<skill name="dropdowns" title="Dropdowns">' in rendered
	assert 'custom dropdowns' in rendered
	assert [item.kind for item in round_tripped.items] == ['task', 'skill']
