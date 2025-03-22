import json
import logging
from langchain_core.messages import HumanMessage
from browser_use.agent.task.prompts import TaskPrompt
from browser_use.agent.task.store import TaskStore
from browser_use.agent.task.views import TaskContext, TaskAnalysis, Plan
import numpy as np
from browser_use.agent.embeddings import EmbeddingModel

logger = logging.getLogger(__name__)

class TaskService:
    """Service for handling task analysis and memory"""

    def __init__(self,
                 llm,
                 task: str,
                 adaptation_threshold: float = 0.92,
                 context_threshold: float = 0.5,
                 task_store=None,
                 retry_on_hallucination: bool = False):
        self.task_llm = llm
        self.task = task
        self.task_store: TaskStore | None = task_store
        self.adaptation_threshold = adaptation_threshold
        self.context_threshold = context_threshold
        self.task_prompt = TaskPrompt()
        self.sentence_model = EmbeddingModel.get_instance()
        self.retry_on_hallucination = retry_on_hallucination

    def _clean_plan_text(self, plan: str) -> str:
        """Clean plan text by removing markdown code blocks and extra whitespace"""
        # Remove markdown code blocks
        if plan.startswith('```') and plan.endswith('```'):
            plan = plan[3:-3]  # Remove outer backticks
        
        # Remove language identifier if present
        if plan.startswith(('json', 'python')):
            plan = plan.split('\n', 1)[1]
        
        # Strip extra whitespace
        plan = plan.strip()
        
        return plan

    async def analyze_task(self) -> TaskAnalysis | None:
        """Get plan or adapted actions for task execution"""
        try:
            context = await self.get_context()

            # If we have a very similar task, adapt its steps directly
            if (context and context.most_similar_task and context.similarity_score 
                and context.similarity_score >= self.adaptation_threshold):
                logger.info(f"Found highly similar task (score: {context.similarity_score}), adapting steps directly")
                # Return adapted actions directly
                adapted_actions = await self._adapt_actions(
                    context.most_similar_task.steps,
                    context.most_similar_task.actions,
                    original_task=context.most_similar_task.task,
                    new_task=self.task
                )
                return TaskAnalysis(
                    type="actions",
                    content=adapted_actions,
                    similarity_score=context.similarity_score,
                    original_task=context.most_similar_task.task
                )
                
            # Otherwise, proceed with full task analysis
            task_messages = [
                self.task_prompt.get_system_message(),
                HumanMessage(content=f"Task: {self.task}")
            ]
            
            # Add context from similar tasks if available
            context_message = self.task_prompt.get_context_message(context)
            if context_message:
                task_messages.append(context_message)

            # Get structured analysis from LLM
            structured_llm = self.task_llm.with_structured_output(Plan)
            plan_output = await structured_llm.ainvoke(task_messages)
            
            # Check for hallucinations
            is_valid, hallucinations = self._check_plan_hallucination(plan_output)
            if not is_valid:
                logger.warning(f"Detected hallucinations in plan:\n" + "\n".join(hallucinations))
                if not self.retry_on_hallucination:
                    return None
                    
                # Only retry if configured to do so
                return await self._retry_plan_generation(task_messages, hallucinations)
            
            return TaskAnalysis(type="plan", content=plan_output)

        except Exception as e:
            logger.warning(f"Error creating plan: {e}")
            return None

    async def _adapt_actions(self, steps: list[str], actions: list[dict], original_task: str, new_task: str) -> list[dict]:
        """Let LLM adapt actions from similar task to current task"""
        try:
            prompt = self.task_prompt.get_adaptation_prompt(original_task, new_task, steps, actions)
            response = await self.task_llm.ainvoke([HumanMessage(content=prompt)])
            adapted_json = self._clean_plan_text(str(response.content))
            
            # Parse JSON to get adapted actions
            adapted_actions = json.loads(adapted_json)
            if not isinstance(adapted_actions, list):
                logger.warning("LLM response is not a list of actions")
                return actions
            
            return adapted_actions

        except Exception as e:
            logger.warning(f"Failed to adapt actions, using original: {e}")
            return actions

    async def get_context(self) -> TaskContext | None:
        """Get and analyze similar tasks for context"""
        if not self.task_store:
            return None
        
        similar_tasks = await self.task_store.search_similar_tasks(self.task, context_threshold=self.context_threshold)
        if not similar_tasks:
            return None

        # Unpack tasks and scores
        tasks, scores = zip(*similar_tasks)
        most_similar = tasks[0]
        
        # Count step frequencies
        step_counts = {}
        total_steps = 0
        total_errors = 0
        
        for task in tasks:
            # Count steps and errors
            total_steps += task.step_count
            total_errors += task.error_count
            
            # Count step frequencies - use step descriptions
            for step in task.steps:
                step_counts[step] = step_counts.get(step, 0) + 1
        
        # Calculate success rate
        success_rate = 1 - (total_errors / total_steps) if total_steps > 0 else 0
        
        # Calculate step frequencies
        n_tasks = len(tasks)
        common_patterns = {
            step: count / n_tasks
            for step, count in step_counts.items()
        }
        
        return TaskContext(
            most_similar_task=most_similar,
            similarity_score=scores[0],
            n_similar_tasks=n_tasks,
            success_rate=success_rate,
            common_patterns=common_patterns
        )

    def _check_plan_hallucination(self, plan: Plan) -> tuple[bool, list[str]]:
        """Check if plan steps are semantically related to the task"""
        if not self.sentence_model:
            logger.warning("No sentence model available for hallucination check")
            return True, []

        # Encode task and steps
        task_embedding = self.sentence_model.encode(self.task)
        steps_embeddings = self.sentence_model.encode(plan.execution.steps)
        
        # Calculate cosine similarity between task and each step
        similarities = np.dot(steps_embeddings, task_embedding) / (
            np.linalg.norm(steps_embeddings, axis=1) * np.linalg.norm(task_embedding)
        )
        
        # Flag steps with low similarity as potential hallucinations
        hallucinated_steps = []
        for step, sim in zip(plan.execution.steps, similarities):
            if sim < 0.05:  # More permissive threshold for common UI interactions
                hallucinated_steps.append(f"Step '{step}' seems unrelated to task (similarity: {sim:.2f})")
        
        return len(hallucinated_steps) == 0, hallucinated_steps

    async def _retry_plan_generation(self, task_messages: list, hallucinations: list[str]) -> TaskAnalysis | None:
        """Retry plan generation with reduced temperature"""
        current_temperature = 0.7
        structured_llm = self.task_llm.with_structured_output(Plan)

        for attempt in range(3):
            current_temperature *= 0.5
            structured_llm = structured_llm.with_settings(temperature=current_temperature)
            
            task_messages.append(HumanMessage(content=f"""
Previous plan contained unrelated steps. Please create a new plan that:
1. Only includes steps directly related to: {self.task}
2. Avoids these unrelated steps: {', '.join(hallucinations)}
3. Maintains strict focus on the core task
"""))

            try:
                plan_output = await structured_llm.ainvoke(task_messages)
                is_valid, new_hallucinations = self._check_plan_hallucination(plan_output)
                if is_valid:
                    return TaskAnalysis(type="plan", content=plan_output)
                hallucinations = new_hallucinations
            except Exception as e:
                logger.warning(f"Retry attempt {attempt + 1} failed: {e}")

        logger.warning("Failed to generate valid plan after retries")
        return None