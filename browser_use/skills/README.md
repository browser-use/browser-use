# Skills Module

The Skills module provides integration with the Browser Use API to fetch and execute skills.

## Basic Usage

```python
import asyncio
from browser_use.skills import SkillService

async def main():
    skill_ids = ['skill-id-1', 'skill-id-2']

    # Initialize service
    service = SkillService(skill_ids=skill_ids, api_key='your-api-key')

    # Get all loaded skills (auto-initializes on first call)
    skills = await service.get_all_skills()

    # Execute a skill (auto-initializes if needed)
    result = await service.execute_skill(
        skill_id='skill-id-1',
        parameters={'param1': 'value1'}
    )

    if result.success:
        print(f'Success! Result: {result.result}')

    # Cleanup
    await service.close()

asyncio.run(main())
```

## Local Skills

Use `LocalSkillService` to load local `SKILL.md` files without a Browser Use API key.
It scans a directory for `*/SKILL.md` files with YAML frontmatter containing
`name` and `description`, then exposes each file as a no-argument skill action.

```python
from browser_use import Agent, ChatBrowserUse
from browser_use.skills import LocalSkillService

agent = Agent(
    task='Use my local workflow',
    llm=ChatBrowserUse(),
    skill_service=LocalSkillService('./skills'),
)
```
