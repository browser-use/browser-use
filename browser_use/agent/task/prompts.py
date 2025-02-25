from langchain_core.messages import SystemMessage, HumanMessage
from browser_use.agent.task.views import TaskContext
import json

class TaskPrompt:
    def __init__(self, similarity_threshold: float = 0.92):
        self.similarity_threshold = similarity_threshold

    def get_system_message(self) -> SystemMessage:
        return SystemMessage(content="""You are a task analyzer that helps plan browser automation tasks.

Core Responsibilities:
1. Break down tasks into SINGLE ACTIONS - one browser action per step
2. Never combine multiple actions (like "search AND click")
3. Consider direct URLs over search when known
4. Optimize for minimal necessary steps

Critical Rules:
- Web browser is already running - don't include browser launch steps
- Assume stable internet - don't add connection checks
- Focus only on browser actions - no system-level operations
- Don't make assumptions about webpage states

Provide analysis in this JSON format:
{
    "analysis": {
        "task_summary": "Brief description of what needs to be done",
        "tags": ["relevant", "task", "categories"],
        "difficulty": <1-10 scale>,
        "potential_challenges": ["possible", "issues", "to handle"]
    },
    "execution_plan": {
        "steps": ["steps", "to take"],
        "success_criteria": "How to know when task is complete",
        "fallback_strategies": ["alternative", "approaches", "if needed"]
    }
}

Important:
1. Always return valid JSON matching the exact structure above
2. All lists must contain at least one item
3. Difficulty must be between 1 and 10
4. Make steps specific and actionable
5. Consider common browser automation challenges

Analyze the task carefully and provide a detailed plan.""")

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