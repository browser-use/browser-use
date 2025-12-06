# Skills Module

The Skills module provides integration with the Browser Use API to fetch and execute skills.

## Basic Usage

```python
import asyncio
from browser_use.skills import SkillService

async def main():
    skill_ids = ['skill-id-1', 'skill-id-2']

    # Using context manager (recommended)
    async with SkillService(skill_ids=skill_ids, api_key='your-api-key') as service:
        # Get all loaded skills (auto-initializes on first call)
        skills = await service.get_all_skills()

        # Execute a skill (auto-initializes if needed)
        result = await service.execute_skill(
            skill_id='skill-id-1',
            parameters={'param1': 'value1'}
        )

        if result.success:
            print(f'Success! Result: {result.result}')

asyncio.run(main())
```
