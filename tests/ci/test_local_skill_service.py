from pathlib import Path

import pytest

from browser_use.agent.service import Agent
from browser_use.skills import LocalSkillService
from tests.ci.conftest import create_mock_llm


def _write_skill(root: Path, directory: str, frontmatter: str, body: str) -> Path:
	skill_dir = root / directory
	skill_dir.mkdir(parents=True)
	skill_path = skill_dir / 'SKILL.md'
	skill_path.write_text(f'---\n{frontmatter}\n---\n{body}', encoding='utf-8')
	return skill_path


async def test_local_skill_service_loads_and_executes_markdown_skill(tmp_path):
	_write_skill(
		tmp_path,
		'research',
		"name: local-research\ntitle: \"Local Research\"\ndescription: 'Load Bob''s local workflow instructions.'",
		'# Research\n\nUse the local workflow.',
	)

	service = LocalSkillService(tmp_path)
	skills = await service.get_all_skills()

	assert len(skills) == 1
	assert skills[0].id == 'local-research'
	assert skills[0].title == 'Local Research'
	assert skills[0].description == "Load Bob's local workflow instructions."
	assert skills[0].parameters == []

	result = await service.execute_skill('local-research', parameters={}, cookies=[])
	assert result.success is True
	assert result.result == '# Research\n\nUse the local workflow.'


async def test_local_skill_service_filters_by_skill_id(tmp_path):
	_write_skill(tmp_path, 'one', 'name: one\ndescription: First skill.', 'one body')
	_write_skill(tmp_path, 'two', 'name: two\ndescription: Second skill.', 'two body')

	service = LocalSkillService(tmp_path, skill_ids=['two'])
	skills = await service.get_all_skills()

	assert [skill.id for skill in skills] == ['two']


async def test_local_skill_service_empty_skill_ids_loads_no_skills(tmp_path):
	_write_skill(tmp_path, 'one', 'name: one\ndescription: First skill.', 'one body')

	service = LocalSkillService(tmp_path, skill_ids=[])
	skills = await service.get_all_skills()

	assert skills == []


async def test_local_skill_service_filters_by_frontmatter_name_when_id_and_title_exist(tmp_path):
	_write_skill(
		tmp_path,
		'summarize',
		'name: summarize\nid: local-summarizer\ntitle: Summarize text\ndescription: Summarize content.',
		'summarize body',
	)

	service = LocalSkillService(tmp_path, skill_ids=['summarize'])
	skills = await service.get_all_skills()

	assert [skill.id for skill in skills] == ['local-summarizer']


async def test_local_skill_service_only_scans_immediate_skill_directories(tmp_path):
	_write_skill(tmp_path, 'top-level', 'name: top-level\ndescription: Top-level skill.', 'top-level body')
	_write_skill(tmp_path, 'vendor/nested', 'name: nested\ndescription: Nested skill.', 'nested body')

	service = LocalSkillService(tmp_path)
	skills = await service.get_all_skills()

	assert [skill.id for skill in skills] == ['top-level']


async def test_local_skill_service_rejects_duplicate_skill_ids(tmp_path):
	_write_skill(tmp_path, 'first', 'name: duplicate\ndescription: First skill.', 'first body')
	_write_skill(tmp_path, 'second', 'name: duplicate\ndescription: Second skill.', 'second body')

	service = LocalSkillService(tmp_path)

	with pytest.raises(ValueError, match='Duplicate local skill id'):
		await service.get_all_skills()


async def test_local_skill_service_raises_for_invalid_direct_file(tmp_path):
	skill_path = tmp_path / 'SKILL.md'
	skill_path.write_text('missing frontmatter', encoding='utf-8')

	service = LocalSkillService(skill_path)

	with pytest.raises(ValueError, match='Invalid local skill'):
		await service.get_all_skills()


async def test_local_skill_service_rejects_block_scalar_frontmatter_in_direct_file(tmp_path):
	skill_path = tmp_path / 'SKILL.md'
	skill_path.write_text('---\nname: local\ndescription: |\n  multiline\n---\nBody', encoding='utf-8')

	service = LocalSkillService(skill_path)

	with pytest.raises(ValueError, match='block scalars are not supported'):
		await service.get_all_skills()


async def test_local_skill_service_accepts_frontmatter_closing_delimiter_at_eof(tmp_path):
	skill_path = tmp_path / 'SKILL.md'
	skill_path.write_text('---\nname: local\ndescription: Ends at frontmatter delimiter.\n---', encoding='utf-8')

	service = LocalSkillService(skill_path)
	skills = await service.get_all_skills()

	assert [skill.id for skill in skills] == ['local']
	result = await service.execute_skill('local', parameters={}, cookies=[])
	assert result.success is True
	assert result.result == ''


async def test_local_skill_service_rejects_yaml_specific_double_quoted_escapes(tmp_path):
	skill_path = tmp_path / 'SKILL.md'
	skill_path.write_text('---\nname: local\ndescription: "Bad \\x41 escape"\n---\nBody', encoding='utf-8')

	service = LocalSkillService(skill_path)

	with pytest.raises(ValueError, match='JSON-compatible escapes'):
		await service.get_all_skills()


async def test_agent_registers_local_skills_as_actions(tmp_path):
	_write_skill(
		tmp_path,
		'workflow',
		'name: local-workflow\ntitle: Local Workflow\ndescription: Load local workflow instructions before acting.',
		'Follow these local instructions.',
	)

	service = LocalSkillService(tmp_path)
	agent = Agent(task='Use the local workflow', llm=create_mock_llm(), skill_service=service)

	await agent._register_skills_as_actions()

	action = agent.tools.registry.registry.actions.get('local_workflow')
	assert action is not None
	assert action.description == 'Load local workflow instructions before acting. (Skill: "Local Workflow")'
