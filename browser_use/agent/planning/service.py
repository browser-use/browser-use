from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

import pyperplan
from pyperplan.search import astar_search
from pyperplan.task import Task
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from browser_use.agent.prompts import PlannerPrompt
from browser_use.agent.views import AgentStepInfo, PlanningResult
from browser_use.agent.planning.views import PlanningContext
from browser_use.browser.views import BrowserState

if TYPE_CHECKING:
    from browser_use.agent.message_manager.service import MessageManager

logger = logging.getLogger(__name__)


class PlanningService:
    """Service for planning next steps in browser automation"""

    def __init__(
        self,
        message_manager: MessageManager,
        agent_llm: BaseChatModel,
        planner_llm: Optional[BaseChatModel] = None,
        use_vision_for_planner: bool = True,
        planner_interval: int = 5,
    ):
        """Initialize the planning service
        
        Args:
            message_manager: Message manager for the agent
            agent_llm: LLM for the agent
            planner_llm: LLM to use for planning (defaults to agent's LLM)
            use_vision_for_planner: Whether to use vision for planning
            planner_interval: How often to run planning (every N steps)
        """
        self._message_manager = message_manager
        self._agent_llm = agent_llm
        self._planner_llm = planner_llm
        self._use_vision_for_planner = use_vision_for_planner
        self._planner_interval = planner_interval
        self._last_plan: Optional[PlanningResult] = None
        
        self._vector_db = None
        try:
            self._embeddings = OpenAIEmbeddings()
            self._vector_db = FAISS.from_texts(
                texts=["Initial document"],  # Start with a dummy document
                embedding=self._embeddings,
                persist_directory="./browser_tasks_db"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize vector DB: {e}")
        
    async def plan_next_steps(
        self, step_info: AgentStepInfo, browser_state: BrowserState
    ) -> Optional[str]:
        """Plan next steps based on current state
        
        Args:
            step_info: Information about the current step
            browser_state: Current state of the browser
            
        Returns:
            Planning result as a string, or None if planning is skipped
        """
        # Skip planning if not at the right interval
        if step_info.step % self._planner_interval != 0:
            return None
            
        # Get LLM to use for planning
        planner_llm = self._planner_llm or self._agent_llm
        
        # Prepare planning context
        context = self._prepare_planning_context(step_info, browser_state)
        
        # Create messages for the planner
        messages = self._create_planning_messages(context)
        
        # Get planning response
        try:
            response = await planner_llm.agenerate([messages])
            plan = response.generations[0][0].text
            
            # Process the plan
            processed_plan = self._process_plan(plan)
            
            refined_plan = self._refine_with_classical_planner(processed_plan, context)
            
            if self._vector_db:
                refined_plan = self._enhance_with_vector_db(refined_plan, context)
            
            # Parse and store the planning result
            self._last_plan = PlanningResult.from_json(refined_plan)
            
            if self._vector_db:
                self._store_successful_plan(refined_plan, context)
            
            return refined_plan
        except Exception as e:
            logger.error(f"Error during planning: {e}")
            return None
            
    def _refine_with_classical_planner(self, plan_str: str, context: PlanningContext) -> str:
        """Refine the plan using a classical planner"""
        try:
            plan_json = json.loads(plan_str)
            
            next_steps = plan_json.get("next_steps", "")
            
            pddl_domain, pddl_problem = self._convert_to_pddl(context, next_steps)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pddl', delete=False) as domain_file:
                domain_file.write(pddl_domain)
                domain_path = domain_file.name
                
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pddl', delete=False) as problem_file:
                problem_file.write(pddl_problem)
                problem_path = problem_file.name
            
            try:
                # Use a simpler approach
                import subprocess
                
                # Run pyperplan as a subprocess
                result = subprocess.run(
                    ['pyperplan', domain_path, problem_path],
                    capture_output=True,
                    text=True
                )
                
                # Parse the output
                if result.returncode == 0 and "Plan length:" in result.stdout:
                    # Extract the plan from the output
                    plan_lines = [line.strip() for line in result.stdout.split('\n') if line.strip().startswith('(')]
                    plan_steps = [line.strip('()') for line in plan_lines]
                    plan_json["next_steps"] = self._convert_pddl_to_natural_language(plan_steps)
            finally:
                os.unlink(domain_path)
                os.unlink(problem_path)
                
            return json.dumps(plan_json, indent=4)
        except Exception as e:
            logger.warning(f"Classical planning failed: {e}")
            return plan_str
    
    def _convert_to_pddl(self, context: PlanningContext, next_steps: str) -> tuple[str, str]:
        """Convert the planning context and next steps to PDDL format"""
        domain_template = """
(define (domain browser-automation)
  (:requirements :strips :typing)
  (:types
    element - object
    url - object
  )
  (:predicates
    (at ?u - url)
    (clickable ?e - element)
    (visible ?e - element)
    (contains-text ?e - element ?t - object)
    (clicked ?e - element)
    (task-completed)
  )
  (:action navigate
    :parameters (?from - url ?to - url)
    :precondition (at ?from)
    :effect (and (not (at ?from)) (at ?to))
  )
  (:action click
    :parameters (?e - element)
    :precondition (and (clickable ?e) (visible ?e))
    :effect (clicked ?e)
  )
  (:action search
    :parameters (?term - object)
    :precondition (at google)
    :effect (and (task-completed))
  )
)
"""

        problem_template = f"""
(define (problem browser-task)
  (:domain browser-automation)
  (:objects
    google - url
    search-box - element
    search-button - element
    python - object
  )
  (:init
    (at {context.current_url or "unknown"})
    (clickable search-box)
    (clickable search-button)
    (visible search-box)
    (visible search-button)
  )
  (:goal (task-completed))
)
"""
        return domain_template, problem_template
    
    def _convert_pddl_to_natural_language(self, plan_steps: List[str]) -> str:
        """Convert PDDL steps to natural language"""
        nl_steps = []
        for step in plan_steps:
            if "navigate" in step:
                nl_steps.append(f"Navigate to the URL mentioned in the action.")
            elif "click" in step:
                nl_steps.append(f"Click on the element mentioned in the action.")
            elif "search" in step:
                nl_steps.append(f"Enter the search term and submit the search.")
        
        return "\n".join([f"{i+1}. {step}" for i, step in enumerate(nl_steps)])
    
    def _enhance_with_vector_db(self, plan_str: str, context: PlanningContext) -> str:
        """Enhance the plan using vector database"""
        try:
            if not self._vector_db:
                return plan_str
            
            plan_json = json.loads(plan_str)
            
            query = f"Task: {context.task}\nURL: {context.current_url}\nTitle: {context.page_title}"
            
            similar_tasks = self._vector_db.similarity_search(query, k=3)
            
            if similar_tasks:
                similar_plans = []
                for doc in similar_tasks:
                    if "next_steps" in doc.metadata:
                        similar_plans.append(doc.metadata["next_steps"])
                
                if similar_plans:
                    plan_json["similar_tasks"] = similar_plans
                    
                    enhanced_next_steps = self._refine_next_steps_with_examples(
                        plan_json["next_steps"], 
                        similar_plans
                    )
                    
                    plan_json["next_steps"] = enhanced_next_steps
            
            return json.dumps(plan_json, indent=4)
        except Exception as e:
            logger.warning(f"Vector DB enhancement failed: {e}")
            return plan_str
    
    def _refine_next_steps_with_examples(self, current_steps: str, example_steps: List[str]) -> str:
        """Refine the next steps using examples"""
        combined_examples = "\n\n".join([f"Example {i+1}:\n{ex}" for i, ex in enumerate(example_steps)])
        
        prompt = f"""
Current plan:
{current_steps}

Similar successful plans:
{combined_examples}

Based on these similar successful plans, refine the current plan to be more effective:
"""
        
        try:
            messages = [
                SystemMessage(content="You are a helpful assistant that refines browser automation plans."),
                HumanMessage(content=prompt)
            ]
            
            response = self._agent_llm.invoke(messages)
            content = response.content
            if isinstance(content, list):
                # If content is a list, convert it to a string representation
                return str(content)
            return content if isinstance(content, str) else current_steps
        except Exception as e:
            logger.warning(f"Plan refinement failed: {e}")
            return current_steps
    
    def _store_successful_plan(self, plan_str: str, context: PlanningContext) -> None:
        """Store the successful plan in vector database"""
        if not self._vector_db:
            return
            
        try:
            plan_json = json.loads(plan_str)
            
            document_text = f"Task: {context.task}\nURL: {context.current_url}\nTitle: {context.page_title}"
            
            metadata = {
                "task": context.task,
                "url": context.current_url,
                "title": context.page_title,
                "state_analysis": plan_json.get("state_analysis", ""),
                "progress_evaluation": plan_json.get("progress_evaluation", ""),
                "next_steps": plan_json.get("next_steps", "")
            }
            
            self._vector_db.add_texts(
                texts=[document_text],
                metadatas=[metadata]
            )
            
            # FAISS doesn't have a persist method, so we'll save it to disk
            import pickle
            with open("./browser_tasks_db.pkl", "wb") as f:
                pickle.dump(self._vector_db, f)
        except Exception as e:
            logger.warning(f"Failed to store plan in vector DB: {e}")
            
    def _prepare_planning_context(
        self, step_info: AgentStepInfo, browser_state: BrowserState
    ) -> PlanningContext:
        """Prepare context for planning
        
        Args:
            step_info: Information about the current step
            browser_state: Current state of the browser
            
        Returns:
            Planning context
        """
        # Get recent actions (last 5)
        recent_actions = step_info.recent_actions
        
        # Get screenshot if using vision
        screenshot_base64 = None
        if self._use_vision_for_planner and browser_state.screenshot:
            screenshot_base64 = browser_state.screenshot
            
        return PlanningContext(
            task=self._message_manager.task,
            current_url=browser_state.url or "",
            page_title=browser_state.title or "",
            step_number=step_info.step,
            recent_actions=recent_actions,
            has_errors=bool(step_info.errors),
            screenshot_base64=screenshot_base64,
        )
        
    def _create_planning_messages(self, context: PlanningContext) -> List[BaseMessage]:
        """Create messages for the planner
        
        Args:
            context: Planning context
            
        Returns:
            List of messages for the planner
        """
        # Create system message
        system_message = SystemMessage(content=PlannerPrompt.get_system_prompt())
        
        # Create human message
        human_message = HumanMessage(
            content=PlannerPrompt.get_human_prompt(
                task=context.task,
                current_url=context.current_url,
                page_title=context.page_title,
                step_number=context.step_number,
                recent_actions=context.recent_actions,
                has_errors=context.has_errors,
            )
        )
        
        # Add image content if available
        if context.screenshot_base64:
            human_message.content = [
                {"type": "text", "text": human_message.content},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{context.screenshot_base64}"
                    },
                },
            ]
            
        return [system_message, human_message]
        
    def _process_plan(self, plan: Any) -> str:
        """Process the planning response"""
        # If it's already a dict or list, convert to JSON string
        if isinstance(plan, (dict, list)):
            return json.dumps(plan, indent=4)
        
        # If it's a string, process it
        if isinstance(plan, str):
            # Remove think tags if present
            plan = self._remove_think_tags(plan)
            
            # Try to extract JSON if wrapped in markdown code blocks
            if "```json" in plan:
                pattern = r"```json\s*(.*?)\s*```"
                import re
                match = re.search(pattern, plan, re.DOTALL)
                if match:
                    plan = match.group(1)
                
            try:
                # Try to parse as JSON
                plan_json = json.loads(plan)
                
                # Validate required fields
                required_fields = ["state_analysis", "progress_evaluation", "next_steps"]
                for field in required_fields:
                    if field not in plan_json:
                        plan_json[field] = f"Missing {field}"
                    
                # Format back to string with proper indentation
                return json.dumps(plan_json, indent=4)
            except json.JSONDecodeError:
                # If not valid JSON, return as is
                logger.warning("Planning response is not valid JSON")
                return plan
            except Exception as e:
                logger.error(f"Error processing plan: {e}")
                return plan
            
        # If it's neither a string nor a dict/list, convert to string
        return str(plan)
            
    def _remove_think_tags(self, text: str) -> str:
        """Remove <think> tags from text for certain models"""
        # Some models like deepseek-reasoner use <think> tags
        text = text.replace("<think>", "")
        text = text.replace("</think>", "")
        return text
        
    @property
    def last_plan(self) -> Optional[PlanningResult]:
        """Get the last planning result"""
        return self._last_plan 