from langchain_core.messages import SystemMessage, HumanMessage
from browser_use.agent.task.views import TaskContext
import json

class TaskPrompt:
    def __init__(self, similarity_threshold: float = 0.92):
        self.similarity_threshold = similarity_threshold

    def get_system_message(self) -> SystemMessage:
        return SystemMessage(content="""You are a task planning assistant that creates structured plans for web automation tasks.
For each step, explicitly connect it to the task goal using task-specific terms.

Guidelines for creating steps:
1. Each step should clearly relate to the main task keywords
2. Include the task objective in step descriptions
3. Be specific about what is being searched, clicked, or selected
4. Tie navigation and UI interactions to the task purpose
5. Break down into SINGLE ACTIONS - one browser action per step

Example:
Task: "Go to amazon.com, search for laptop, sort by best rating, and get the first result's price"

Good steps:
- "Navigate to amazon.com to begin laptop search"
- "Enter 'laptop' into the Amazon search field"
- "Initiate the laptop search"
- "Access the sorting options for laptop results"
- "Select best rating filter to find top-rated laptops"
- "Extract the price of the highest-rated laptop"

Bad steps (too generic):
- "Click the search button"
- "Wait for page to load"
- "Click sorting dropdown"
- "Get the price"

Provide analysis in this JSON format:
{
    "analysis": {
        "task_summary": "Brief description of what needs to be done",
        "tags": ["relevant", "task", "categories"],
        "difficulty": <1-10 scale>,
        "potential_challenges": ["possible", "issues", "to handle"]
    },
    "execution": {
        "steps": ["task-specific steps as shown in example"],
        "success_criteria": "How to know when task is complete",
        "fallback_strategies": ["alternative", "approaches", "if needed"]
    }
}

Critical Requirements:
1. Always return valid JSON matching the exact structure above
2. All lists must contain at least one item
3. Difficulty must be between 1 and 10
4. Make steps specific and actionable
5. Include task-specific terms in each step
6. Don't include browser launch steps - browser is already running
7. Focus only on browser actions - no system operations
""")

    def get_adaptation_prompt(self, original_task: str, new_task: str, steps: list[str], actions: list[dict]) -> str:
        """Get prompt for adapting actions from similar task"""
        return f"""You are an expert in adapting browser automation actions. Your role is to precisely modify existing successful actions while maintaining their exact structure.

Given these two similar tasks:
Original task: {original_task}
New task: {new_task}

Below is the EXACT successful execution record that must be adapted:

Original Steps (DO NOT MODIFY STRUCTURE):
{json.dumps(steps, indent=2)}

Original Actions (ONLY MODIFY VALUES, NOT STRUCTURE):
{json.dumps(actions, indent=2)}

Instructions for adaptation:
1. Copy the exact action structure - do not add or remove fields
2. Only modify parameter values that absolutely need to change
3. Keep all action names EXACTLY as they appear
4. Maintain the same number and sequence of actions
5. Do not invent new parameters or actions

Return ONLY a JSON array of the modified actions. Example format:
[
    {{
        "action_name": {{
            "param1": "new_value",
            "param2": "value2"
        }}
    }}
]

Critical Requirements:
- Output must be valid JSON array
- Action names must match original exactly
- Only modify parameter values when necessary
- Keep all original parameters
- Do not add new parameters"""

    def get_context_message(self, context: TaskContext | None) -> HumanMessage | None:
        """Create message with context from similar tasks"""
        if not context or not context.most_similar_task:
            return None

        context_msg = f"""I found a highly similar task in our execution history (Similarity: {context.similarity_score:.2%})

Previous Successful Task:
"{context.most_similar_task.task}"

Execution Record:
1. Steps Taken:
{json.dumps(context.most_similar_task.steps, indent=2)}

2. Browser Actions Used:
{json.dumps(context.most_similar_task.actions, indent=2)}

Task Statistics:
• Total similar tasks found: {context.n_similar_tasks}
• Overall success rate: {context.success_rate * 100:.0f}%
• Execution time: {context.most_similar_task.execution_time:.1f}s
• Error count: {context.most_similar_task.error_count}

Most Effective Patterns:
{json.dumps(dict(sorted(context.common_patterns.items(), key=lambda x: x[1], reverse=True)[:5]), indent=2)}

Use this successful execution as a reference only"""

        return HumanMessage(content=context_msg) 