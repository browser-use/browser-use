from __future__ import annotations


import asyncio
import importlib.resources
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, TypeVar, Sequence

from browser_use.agent.gif import create_history_gif
from browser_use.agent.message_manager.utils import extract_json_from_model_output, save_conversation
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
	BaseMessage,
	HumanMessage,
	SystemMessage,
)

# from lmnr.sdk.decorators import observe
from pydantic import BaseModel, ValidationError

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from browser_use.agent.service import Agent
from browser_use.telemetry.views import AgentEndTelemetryEvent, AgentStepTelemetryEvent
from browser_use.agent.views import AgentStepInfo, StepMetadata, AgentHistoryList
from browser_use.agent.prompts import SystemPrompt, AgentMessagePrompt
from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.browser.views import  BrowserError, BrowserStateHistory

from supatest.agent.views import SupatestAgentOutput, SupatestAgentBrain,SupatestAgentHistory, SupatestAgentHistoryList, SupatestActionResult
from supatest.controller.registry.views import SupatestActionModel

from supatest.browser.browser import SupatestBrowser
from supatest.browser.context import SupatestBrowserContext
from supatest.browser.views import SupatestBrowserState
from supatest.controller.service import SupatestController
from importlib import resources

logger = logging.getLogger(__name__)

Context = TypeVar('Context')

class SupatestAgent(Agent[Context]):
    """Extended Agent class with custom implementations"""

    browser_context: SupatestBrowserContext
    controller: SupatestController[Context]

    def __init__(
        self,
        task: str,
        llm: BaseChatModel,
        browser: SupatestBrowser | None = None,
        browser_context: SupatestBrowserContext | None = None,
        controller: SupatestController[Context] = SupatestController(),
        sensitive_data: Optional[Dict[str, str]] = None,
        initial_actions: Optional[List[Dict[str, Dict[str, Any]]]] = None,
        register_new_step_callback: Callable[['SupatestBrowserState', 'SupatestAgentOutput', int], Awaitable[None]] | None = None,
        register_done_callback: Callable[['SupatestAgentHistoryList'], Awaitable[None]] | None = None,
        register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
        send_message: Optional[Callable[[dict], Awaitable[bool]]] = None,
        goal_step_id: Optional[str] = None,
        requestId: Optional[str] = None,
        testCaseId: Optional[str] = None,
        active_page_id: Optional[str] = None,
        **kwargs
    ):
        # Initialize consecutive_eval_failure first
        self.consecutive_eval_failure = 0
        
        # Get custom action descriptions from our registry before calling super().__init__
        controller_registry = controller.registry
        available_actions = controller_registry.get_prompt_description()
        
        # Handle browser and browser_context setup before calling super().__init__
        self.injected_browser = browser is not None
        self.injected_browser_context = browser_context is not None
        
        # If only browser is provided, create a SupatestBrowserContext
        if browser and not browser_context:
            browser_context = SupatestBrowserContext(browser=browser, config=browser.config.new_context_config, active_page_id=active_page_id)
            # We created the browser_context, so we should close it
            self.injected_browser_context = False
        
        # Load our custom system prompt if not already overridden
        if 'override_system_message' not in kwargs:
            try:
                # Load the custom system prompt from the Supatest package
                with importlib.resources.files('supatest.agent').joinpath('system_prompt.md').open('r') as f:
                    custom_system_prompt = f.read()
                max_actions = kwargs.get('max_actions_per_step', 10)
                custom_system_prompt = custom_system_prompt.format(max_actions=max_actions)
                kwargs['override_system_message'] = custom_system_prompt
            except Exception as e:
                logger.warning(f"Failed to load custom system prompt: {e}") 
        
        super().__init__(
            task=task,
            llm=llm,
            browser=browser,
            browser_context=browser_context,
            controller=controller,
            sensitive_data=sensitive_data,
            initial_actions=initial_actions,
            register_new_step_callback=register_new_step_callback,
            register_done_callback=register_done_callback,
            register_external_agent_status_raise_error_callback=register_external_agent_status_raise_error_callback,
            **kwargs
        )
        self.send_message = send_message
        self.goal_step_id = goal_step_id
        self.requestId = requestId
        self.testCaseId = testCaseId
        self.active_page_id = active_page_id
        # Store our custom action descriptions
        self.available_actions = available_actions

        self._message_manager = MessageManager(
            task=task,
            system_message= SystemPrompt(
                action_description=self.available_actions,
                max_actions_per_step=self.settings.max_actions_per_step,
                override_system_message=kwargs.get('override_system_message'),
                extend_system_message=self.settings.extend_system_message,
            ).get_system_message(),
            settings=MessageManagerSettings(
                max_input_tokens=self.settings.max_input_tokens,
                include_attributes=self.settings.include_attributes,
                message_context=self.settings.message_context,
                sensitive_data=sensitive_data,
                available_file_paths=self.settings.available_file_paths,
            ),
            state=self.state.message_manager_state,
        )
        
        self.locator_js_code = resources.read_text('supatest.agent', 'locator.js')

    def _setup_action_models(self) -> None:
        """Setup dynamic action models from controller's registry using our extended AgentOutput"""
        self.ActionModel = self.controller.registry.create_action_model()
        self.AgentOutput = SupatestAgentOutput.type_with_custom_actions(self.ActionModel)
        self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'])
        self.DoneAgentOutput = SupatestAgentOutput.type_with_custom_actions(self.DoneActionModel)
      
    async def get_next_action(self, input_messages: list[BaseMessage]) -> SupatestAgentOutput:
        """Get next action from LLM based on current state"""
        input_messages = self._convert_input_messages(input_messages)

        if self.tool_calling_method == 'raw':
            output = self.llm.invoke(input_messages)
            # TODO: currently invoke does not return reasoning_content, we should override invoke
            output.content = self._remove_think_tags(str(output.content))
            try:
                parsed_json = extract_json_from_model_output(output.content)
                parsed = self.AgentOutput(**parsed_json)
            except (ValueError, ValidationError) as e:
                logger.warning(f'Failed to parse model output: {output} {str(e)}')
                raise ValueError('Could not parse response.')

        elif self.tool_calling_method is None:
            structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True)
            response: dict[str, Any] = await structured_llm.ainvoke(input_messages)  # type: ignore
            parsed: SupatestAgentOutput | None = response['parsed']
        else:
            structured_llm = self.llm.with_structured_output(self.AgentOutput, include_raw=True, method=self.tool_calling_method)
            logger.debug(f"🤖 Calling LLM with messages: {input_messages}")
            response: dict[str, Any] = await structured_llm.ainvoke(input_messages)
            parsed: SupatestAgentOutput | None = response['parsed']

        if parsed is None:
            raise ValueError('Could not parse response.')
        
        parsed.action = parsed.action[: self.settings.max_actions_per_step]
        self.state.n_steps += 1

        return parsed

    async def _log_response(self, response: SupatestAgentOutput) -> None:
        """Log the model's response with custom websocket messaging"""
        if 'Success' in response.current_state.evaluation_previous_goal:
            emoji = '👍'
        elif 'Failed' in response.current_state.evaluation_previous_goal:
            emoji = '⚠'
        else:
            emoji = '🤷'

        # Log to console
        logger.debug(f'🤖 {emoji} Page summary: {response.current_state.page_summary}')
        logger.info(f'{emoji} Eval: {response.current_state.evaluation_previous_goal}')
        logger.info(f'🧠 Memory: {response.current_state.memory}')
        logger.info(f'🎯 Next goal: {response.current_state.next_goal}')
        logger.info(f'🎯 Thought: {response.current_state.thought}')

        # Create steps array with all actions
        steps = []
        for i, action in enumerate(response.action):
            step = action.model_dump(exclude_none=True)
            steps.append(step)
            logger.info(f'🛠️  Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')

    async def _handle_step_error(self, e: Exception) -> list[SupatestActionResult]:
            error_str = str(e)
            return [SupatestActionResult(
                error=error_str,
                include_in_memory=True,
                isExecuted='failure'
            )]
            
    async def step(self, step_info: Optional[AgentStepInfo] = None) -> None:
        """Execute one step of the task with custom error handling and messaging"""
        state = None
        model_output = None
        result: list[SupatestActionResult] = []
        step_start_time = time.time()
        tokens = 0
        subgoal_id = uuid.uuid4()
        logger.info(f'\n\n --------------------------------------')
        logger.info(f'📍 Step {self.state.n_steps} | Subgoal ID: {subgoal_id}')

        try:
            state = await self.browser_context.get_state()
            await self._raise_if_stopped_or_paused()

            self._message_manager.add_state_message(state, self.state.last_result, step_info, self.settings.use_vision)

            # Custom eval failure handling
            if self.consecutive_eval_failure >= self.settings.max_failures:
                logger.info("⚠️  Max eval failures reached: Generate Done Action with success as False")
                # Add a human message about the consecutive failures
                failure_msg = (
                    f"You have failed to achieve your goals {self.consecutive_eval_failure} times in a row. You must now generate a 'done' action with success=false and provide a detailed explanation of why the task could not be completed after multiple attempts in 'text' key."
                )
                self._message_manager._add_message_with_tokens(HumanMessage(content=failure_msg))

            # Run planner at specified intervals if planner is configured
            if self.settings.planner_llm and self.state.n_steps % self.settings.planner_interval == 0:
                plan = await self._run_planner()
                self._message_manager.add_plan(plan, position=-1)

            if step_info and step_info.is_last_step():
                # Add last step warning if needed
                msg = 'Now comes your last step. Use only the "done" action now. No other actions - so here your action sequence must have length 1.'
                msg += '\nIf the task is not yet fully finished as requested by the user, set success in "done" to false! E.g. if not all steps are fully completed.'
                msg += '\nIf the task is fully finished, set success in "done" to true.'
                msg += '\nInclude everything you found out for the ultimate task in the done text.'
                logger.info('Last step finishing up')
                self._message_manager._add_message_with_tokens(HumanMessage(content=msg))
                self.AgentOutput = self.DoneAgentOutput

            input_messages = self._message_manager.get_messages()
            tokens = self._message_manager.state.history.current_tokens

            # Planning action from LLM
            try:
                model_output = await self.get_next_action(input_messages)
                await self._check_eval_failure(model_output, step_info)
                await self._log_response(model_output)
                await self._send_subgoal_update(subgoal_id, False, model_output)

                if self.register_new_step_callback:
                    await self.register_new_step_callback(state, model_output, self.state.n_steps)

                if self.settings.save_conversation_path:
                    target = self.settings.save_conversation_path + f'_{self.state.n_steps}.txt'
                    save_conversation(input_messages, model_output, target, self.settings.save_conversation_path_encoding)

                self._message_manager._remove_last_state_message()
                await self._raise_if_stopped_or_paused()
                self._message_manager.add_model_output(model_output)

            except Exception as e:
                # Create steps array with all actions
                error_str = str(e)
                self._message_manager._remove_last_state_message()
                self.state.last_result = [SupatestActionResult(error=error_str, include_in_memory=True, isExecuted='failure')]
                custom_error_str = 'The agent was unable to generate a valid subgoal due to technical glitches'
                error_info = {
                    "errorCount": self.state.consecutive_failures,
                    "errorType": "AGENT_PLANNER_ERROR",  # TODO: yet to decide the different error types
                    "errorMessage": custom_error_str
                }
                await self._send_subgoal_update(subgoal_id, True, error_info=error_info)
                raise e

            # Execute actions 
            result = await self.multi_act(model_output.action, subgoal_id)
            self.state.last_result = result

            if len(result) > 0 and result[-1].is_done:
                logger.info(f'📄 Result: {result[-1].extracted_content}')

            self.state.consecutive_failures = 0

        except InterruptedError:
            logger.debug('Agent paused')
            self.state.last_result = [
                SupatestActionResult(
                    error='The agent was paused - now continuing actions might need to be repeated',
                    include_in_memory=True,
                    isExecuted='failure'
                )
            ]
            return
        except Exception as e:
            result = await self._handle_step_error(e)
            self.state.last_result = result
            error_str = str(e)
            logger.error(f'❌ Error: {error_str}')
            

        finally:
            step_end_time = time.time()
            actions = [a.model_dump(exclude_unset=True) for a in model_output.action] if model_output else []
            self.telemetry.capture(
                AgentStepTelemetryEvent(
                    agent_id=self.state.agent_id,
                    step=self.state.n_steps,
                    actions=actions,
                    consecutive_failures=self.state.consecutive_failures,
                    step_error=[r.error for r in result if r.error] if result else ['No result'],
                )
            )

            if not result:
                return

            if state:
                metadata = StepMetadata(
                    step_number=self.state.n_steps,
                    step_start_time=step_start_time,
                    step_end_time=step_end_time,
                    input_tokens=tokens,
                )
    
                self._make_history_item(model_output, state, result, metadata)

    def _make_history_item(
        self,
        model_output: SupatestAgentOutput | None,
        state: BrowserState,
        result: list[SupatestActionResult],
        metadata: Optional[StepMetadata] = None,
    ) -> None:
        """Create and store history item"""
        
        if model_output:
            interacted_elements = SupatestAgentHistory.get_interacted_element(model_output, state.selector_map)
        else:
            interacted_elements = [None]

        state_history = BrowserStateHistory(
            url=state.url,
            title=state.title,
            tabs=state.tabs,
            interacted_element=interacted_elements,
            screenshot=state.screenshot,
        )

        history_item = SupatestAgentHistory(model_output=model_output, result=result, state=state_history, metadata=metadata)

        self.state.history.history.append(history_item)

    # Set the max steps to 20 for now
    async def run(self, max_steps: int = 20) -> SupatestAgentHistoryList:
        """Execute the task with maximum number of steps and custom completion handling"""
        try:
            self._log_agent_run()

            if self.initial_actions:
                result = await self.multi_act(self.initial_actions, subgoal_id=uuid.uuid4(), check_for_new_elements=False)
                self.state.last_result = result

            for step in range(max_steps):
                if self.state.consecutive_failures >= self.settings.max_failures:
                    logger.error(f'❌ Stopping due to {self.settings.max_failures} consecutive failures')
                    error_messages = [r.error for r in self.state.last_result if r.error]
                    logger.error(f'❌ Error message: {error_messages}')
                    error_message = "The agent was unable to achieve the specified goal due to some prompt issues. Please consider modifying the prompt and trying again."
                    if error_messages:
                        # in the case of LLM we don't send it the errors in subgoal level
                        if (any("ResponsibleAIPolicyViolation" in msg for msg in error_messages) or 
                            any("content_filter" in msg for msg in error_messages) or
                            any("Could not parse response" in msg for msg in error_messages)):
                            await self._send_message("ERROR", error_message)
                            break
                        else:
                            error_message = "The agent was unable to complete the task. Please try again."
                    else:
                        # TODO: still not very sure of, need to check if this is correct 
                        error_message = "Unknown error occurred in agent execution"
                        error_info = None
                        if self.state.consecutive_failures == 3:
                            error_info = {
                                    "errorCount": self.state.consecutive_failures,
                                    "errorType": "ACTION_EXECUTION_ERROR",
                                    "errorMessage": error_message
                                }
                    
                            # Send single websocket message with all data
                            await self._send_message("AGENT_GOAL_STOP_RES", {
                                "requestId": self.requestId,
                                "testCaseId": self.testCaseId,
                                "success": False,
                                "error": json.dumps(error_info) if error_info else None,
                            })
                            break

                if self.state.stopped:
                    logger.info('Agent stopped')
                    break

                while self.state.paused:
                    await asyncio.sleep(0.2)
                    if self.state.stopped:
                        break

                step_info = AgentStepInfo(step_number=step, max_steps=max_steps)
                await self.step(step_info)

                if self.state.history.is_done():
                    if self.settings.validate_output and step < max_steps - 1:
                        if not await self._validate_output():
                            continue                    
                    try:
                        if self.send_message:
                            await self._send_message("AGENT_GOAL_STOP_RES", {
                                "requestId": self.requestId,
                                "testCaseId": self.testCaseId,
                                "success": True,
                                "error": None,
                            })
                    except Exception as e:
                        logger.warning(f"Failed to send goal stop message: {str(e)}")
                        
                  
                    await self.log_completion()
                    break
            else:
                # unable to complete task in max steps ERROR
                logger.info('❌ Failed to complete task in maximum steps')
                if self.send_message:
                    await self._send_message("ERROR", "The agent was unable to complete the task within the allowed number of steps.")

            return self.state.history

        finally:
            await self._cleanup(max_steps)

    async def _cleanup(self, max_steps: int) -> None:
        """Cleanup resources and generate final artifacts"""
        logger.debug('🔄 Cleaning up...')
        # Remove highlights before closing the browser context
        await self.browser_context.remove_highlights()

    async def stop(self) -> None:
        """Stop the agent"""
        logger.info('⏹️ Supatest Agent stopping')
        self.state.stopped = True
        error_info = {
            "errorCount": 1,
            "errorType": "AGENT_STOPPED",
            "errorMessage": "Agent execution terminated - stopped by user or system before task completion"
        }
        if self.send_message:
            await self._send_message("AGENT_GOAL_STOP_RES", {
                "requestId": self.requestId,
                "testCaseId": self.testCaseId,
                "success": False,
                "error": json.dumps(error_info),
            })

    async def multi_act(
        self,
        actions: Sequence[SupatestActionModel],
        subgoal_id: str,
        check_for_new_elements: bool = True,
    ) -> list[SupatestActionResult]:
        """Execute multiple actions with SupatestActionModel type"""
        results = []

        cached_selector_map = await self.browser_context.get_selector_map()
        cached_path_hashes = set(e.hash.branch_path_hash for e in cached_selector_map.values())

        await self.browser_context.remove_highlights()

        # Create initial steps array
        steps = []
        for i, action in enumerate(actions):
            step = action.model_dump(exclude_none=True)  
            steps.append(step)

        for i, action in enumerate(actions):
            isExecuted = 'pending'
            if action.get_index() is not None and i != 0:
                new_state = await self.browser_context.get_state()
                new_path_hashes = set(e.hash.branch_path_hash for e in new_state.selector_map.values())
                if check_for_new_elements and not new_path_hashes.issubset(cached_path_hashes):
                    # next action requires index but there are new elements on the page
                    isExecuted = 'failure'
                    step = action.model_dump(exclude_none=True)
                    steps = await self._send_action_update(step, isExecuted, steps)
                    msg = f'Something new appeared after step {i} / {len(actions)}'
                    logger.info(msg)
                    error_info = {
                        "errorCount": 1,
                        "errorType": "NEW_ELEMENTS_ERROR",
                        "errorMessage": msg
                    }
                    await self._send_subgoal_update(subgoal_id, True, error_info=error_info)
                    results.append(SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='failure'))
                    break

            await self._raise_if_stopped_or_paused()

            # For actions that have an index, we need to get the element node to extract the locators
            element_node = None
            action_index = action.get_index()
            locator: str | None = None
            all_unique_locators: list[dict] | None = None
            if action_index is not None:
                if action_index not in await self.browser_context.get_selector_map():
                    message = f'Element index {action_index} does not exist - retry or use alternative actions'
                    SupatestActionResult(error=message, isExecuted='failure')
                    raise Exception(message)
                
                element_node = await self.browser_context.get_dom_element_by_index(action_index)
                if element_node is None:
                    raise Exception(f'Element index {action_index} does not exist - retry or use alternative actions')
                logger.debug(f'Element node: {element_node}')
            
                element_handle = await self.browser_context.get_locate_element(element_node)
                if element_handle is None:
                    raise BrowserError(f'Element: {repr(element_node)} not found')
                
                eval_element = await element_handle.evaluate(self.locator_js_code)
                locator = eval_element['locator']
                all_unique_locators = eval_element['allUniqueLocators']
                logger.debug(f'Locator: {locator}')
                logger.debug(f'All Unique Locators: {all_unique_locators}')

            result = await self.controller.act(
                action,
                self.browser_context,
                self.settings.page_extraction_llm,
                self.sensitive_data,
                self.settings.available_file_paths,
                context=self.context,
            )

            isExecuted = result.isExecuted 
            if locator and all_unique_locators:
                action.set_locator(locator)
                action.set_all_unique_locators(all_unique_locators)

            step = action.model_dump(exclude_none=True)
            
            if(result.error):
                error_info = {
                    "errorCount": self.state.consecutive_failures,
                    "errorType": "ACTION_EXECUTION_ERROR",
                    "errorMessage": result.error
                }
                await self._send_subgoal_update(subgoal_id, True, error_info=error_info)
            
            
            
            # TODO: send the update of execution  and if error occurs send that also
            
            # Send update that the action has been executed with the result
            # The key change: update the steps variable with the returned updated steps
            steps = await self._send_action_update(step, isExecuted, steps)
            results.append(result)

            logger.debug(f'Executed action {i + 1} / {len(actions)}')
            if results[-1].is_done or results[-1].error or i == len(actions) - 1:
                break

            await asyncio.sleep(self.browser_context.config.wait_between_actions)
            # hash all elements. if it is a subset of cached_state its fine - else break (new elements on page)

        return results



# ALL SUPATEST CUSTOM METHODS
    async def _send_action_update(self, action, is_executed: str, steps: list[dict]) -> list[dict]:
        """
        Send action execution status update via websocket

        Args:
            action: The action that was executed
            is_executed: The execution status ('pending', 'success', 'failure')
            steps: List of all steps in the current sequence

        Returns:
            The updated steps list with execution status
        """
        if not self.send_message:
            return steps  # Return original steps if no message sending

        try:
            # Get the action type and details from the current action
            action_type = next(iter(action))  # Get the action type (e.g., 'input_text', 'click_element')
            action_details = action[action_type]

            # Find and update the matching step
            for step in steps:
                step_type = next(iter(step))
                step_details = step[step_type]
                
                # Match both the action type and the action details (using ID or other unique identifiers)
                if (step_type == action_type and 
                    step_details.get('index') == action_details.get('index')):
                    step[step_type]['isExecuted'] = is_executed
                    if action_details.get('locator'):
                        step[step_type]['locator'] = action_details.get('locator')
                    if action_details.get('allUniqueLocators'):
                        step[step_type]['allUniqueLocators'] = action_details.get('allUniqueLocators')  
                    break


            simplified_steps = [list(step.values())[0] for step in steps]
            # Send the updated steps via websocket
            await self._send_message("AGENT_STEP_EXECUTED", {
                "steps": simplified_steps
            })

            return steps

        except Exception as e:
            logger.warning(f"Failed to send action update: {str(e)}")
            return steps  # Return original steps if there was an error
        
    async def _check_eval_failure(self, model_output: SupatestAgentOutput, step_info: AgentStepInfo | None = None) -> None:
        """Check if the evaluation of the previous goal failed"""
        if step_info and step_info.step_number > 0 and ('Failed' in model_output.current_state.evaluation_previous_goal or 'Unknown' in model_output.current_state.evaluation_previous_goal):
            self.consecutive_eval_failure += 1
        else:
            self.consecutive_eval_failure = 0
        
    async def _send_message(self, message_type: str, message_data: Any) -> None:
        """Send websocket messages if send_message callback is configured"""
        if not self.send_message:
            return
            
        try:
            message = {
                "type": message_type,
                "goalId": self.goal_step_id,
                "message": message_data if isinstance(message_data, dict) else {"message": str(message_data)}
            }
            await self.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to send message: {str(e)}")   
            
    async def _send_subgoal_update(self, subgoal_id: str, is_error: bool, model_output: Optional[SupatestAgentOutput] = None, error_info: Optional[dict] = None) -> None:
        """Send subgoal update via websocket
        
        Args:
            subgoal_id: Unique identifier for the subgoal
            is_error: Flag indicating if this update is for an error
            model_output: The model output containing action and state info (required if is_error=False)
            error_info: Error information dictionary (required if is_error=True)
        """
        
        if self.send_message:
            subgoal_id_str = str(subgoal_id)
            if is_error:
                logger.info(f"📤 [ERROR] sending subgoal error update for {subgoal_id_str}")
                if not error_info:
                    raise ValueError("error_info is required when is_error=True")
                    
                await self._send_message("AGENT_SUB_GOAL_UPDATE", {
                    "subgoalId": subgoal_id_str,
                    "pageSummary": None,
                    "eval": None,
                    "memory": None,
                    "nextGoal": None,
                    "thought": None,
                    "steps": [],
                    "error": [error_info]
                })
            else:
                logger.info(f"📤 [ACTION-PLAN] sending subgoal update for {subgoal_id_str}")
                if not model_output:
                    raise ValueError("model_output is required when is_error=False")
                    
                steps = []
                for i, action in enumerate(model_output.action):
                    step = action.model_dump(exclude_none=True)
                    steps.append(step)

                await self._send_message("AGENT_SUB_GOAL_UPDATE", {
                    "subgoalId": subgoal_id_str,
                    "pageSummary": model_output.current_state.page_summary,
                    "eval": model_output.current_state.evaluation_previous_goal,
                    "memory": model_output.current_state.memory,
                    "nextGoal": model_output.current_state.next_goal,
                    "thought": model_output.current_state.thought,
                    "steps": steps,
                    "error": None
                })

