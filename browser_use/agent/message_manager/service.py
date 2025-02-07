from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional, Type

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI



from browser_use.agent.message_manager.views import MessageHistory, MessageMetadata
from browser_use.agent.prompts import AgentMessagePrompt, SystemPrompt
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo
from browser_use.browser.views import BrowserState
from openai import OpenAI

logger = logging.getLogger(__name__)

# Setup the logger for memory operations
def setup_memory_logger():
    """Setup a logger for memory operations."""
    memory_logger = logging.getLogger('MemoryLogger')
    memory_logger.setLevel(logging.INFO)
    
    # Create file handler with no size limit
    handler = logging.FileHandler('memory_operations_new.log')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    if not memory_logger.handlers:  # To prevent adding multiple handlers to the logger
        memory_logger.addHandler(handler)
        
    return memory_logger

# Initialize the memory logger
memory_logger = setup_memory_logger()

class MessageManager:
    def __init__(
        self,
        llm: BaseChatModel,
        task: str,
        action_descriptions: str,
        system_prompt_class: Type[SystemPrompt],
        max_input_tokens: int = 128000,
        estimated_characters_per_token: int = 3,
        image_tokens: int = 800,
        include_attributes: list[str] = [],
        max_error_length: int = 400,
        max_actions_per_step: int = 10,
        message_context: Optional[str] = None,
    ):
        self.llm = llm
        self.system_prompt_class = system_prompt_class
        self.max_input_tokens = max_input_tokens
        self.history = MessageHistory()
        self.task = task
        self.action_descriptions = action_descriptions
        self.estimated_characters_per_token = estimated_characters_per_token
        self.IMG_TOKENS = image_tokens
        self.include_attributes = include_attributes
        self.max_error_length = max_error_length
        self.message_context = message_context

        system_message = self.system_prompt_class(
            self.action_descriptions,
            current_date=datetime.now(),
            max_actions_per_step=max_actions_per_step,
        ).get_system_message()

        self._add_message_with_tokens(system_message)
        self.system_prompt = system_message

        if self.message_context:
            context_message = HumanMessage(content=self.message_context)
            self._add_message_with_tokens(context_message)

        task_message = self.task_instructions(task)
        self._add_message_with_tokens(task_message)
        self.tool_id = 1
        tool_calls = [
            {
                'name': 'AgentOutput',
                'args': {
                    'current_state': {
                        'evaluation_previous_goal': 'Unknown - No previous actions to evaluate.',
                        'memory': '',
                        'next_goal': 'Start browser',
                    },
                    'action': [],
                },
                'id': str(self.tool_id),
                'type': 'tool_call',
            }
        ]

        example_tool_call = AIMessage(
            content=f'',
            tool_calls=tool_calls,
        )
        self._add_message_with_tokens(example_tool_call)
        tool_message = ToolMessage(
            content=f'Browser started',
            tool_call_id=str(self.tool_id),
        )
        self._add_message_with_tokens(tool_message)
        self.tool_id += 1

    

    @staticmethod
    def task_instructions(task: str) -> HumanMessage:
        content = f'Your ultimate task is: {task}. If you achieved your ultimate task, stop everything and use the done action in the next step to complete the task. If not, continue as usual.'
        return HumanMessage(content=content)



    def add_state_message(
        self,
        state: BrowserState,
        step_id: str,
        result: Optional[List[ActionResult]] = None,
        step_info: Optional[AgentStepInfo] = None,
        save_state: bool = True,  # Default to True to preserve current functionality by default
    ) -> None:
        """Add browser state as human message, optionally saving the state based on the save_state flag."""
        # Log and save results if present and flagged to be kept in memory
        if result:
            for r in result:
                if r.include_in_memory:
                    if r.extracted_content:
                        msg = HumanMessage(content='Action result: ' + str(r.extracted_content))
                        self._add_message_with_tokens(msg)
                        memory_logger.info(f"Result added to memory: {r.extracted_content}, Step ID: {step_id}")
                    if r.error:
                        msg = HumanMessage(content='Action error: ' + str(r.error)[-self.max_error_length:])
                        self._add_message_with_tokens(msg)
                        memory_logger.info(f"Error added to memory: {r.error}, Step ID: {step_id}")
                    result = None  # Clear result to avoid adding it again

        # Only add the state message to the history if save_state is True
        if save_state:
            state_message = AgentMessagePrompt(
                state,
                result,
                include_attributes=self.include_attributes,
                max_error_length=self.max_error_length,
                step_info=step_info,
                step_id=step_id,
            ).get_user_message()
            self._add_message_with_tokens(state_message)
            memory_logger.info(f"State message added to history with Step ID: {step_id}")
        else:
            memory_logger.info("State message not added to history due to save_state flag set to False, Step ID: {step_id}")

     
    def add_model_output(self, model_output: AgentOutput) -> None:
        """Add model output as AI message"""
        tool_calls = [
            {
                'name': 'AgentOutput',
                'args': model_output.model_dump(mode='json', exclude_unset=True),
                'id': str(self.tool_id),
                'type': 'tool_call',
            }
        ]

        msg = AIMessage(
            content='',
            tool_calls=tool_calls,
        )

        self._add_message_with_tokens(msg)
        memory_logger.info(f'tool call: {msg}')
        # empty tool response
        tool_message = ToolMessage(
            content='',
            tool_call_id=str(self.tool_id),
        )
        self._add_message_with_tokens(tool_message)
        memory_logger.info(f'tool call: {tool_message}')
        self.tool_id += 1

    def get_messages(self) -> List[BaseMessage]:
        """Get current message list, potentially trimmed to max tokens"""

        msg = [m.message for m in self.history.messages]
        # debug which messages are in history with token count # log
        total_input_tokens = 0
        logger.debug(f'Messages in history: {len(self.history.messages)}:')
        for m in self.history.messages:
            total_input_tokens += m.metadata.input_tokens
            logger.debug(f'{m.message.__class__.__name__} - Token count: {m.metadata.input_tokens}')
            memory_logger.info(f'{m.message.__class__.__name__} - Token count: {m.metadata.input_tokens}')
        logger.debug(f'Total input tokens: {total_input_tokens}')

        return msg

    def _add_message_with_tokens(self, message: BaseMessage) -> None:
        """Add message with token count metadata"""
        token_count = self._count_tokens(message)
        metadata = MessageMetadata(input_tokens=token_count)
        self.history.add_message(message, metadata)
        memory_logger.info(f"Message added to history with step_id: {getattr(message, 'step_id', 'None')}")

    def _count_tokens(self, message: BaseMessage) -> int:
        """Count tokens in a message using the model's tokenizer"""
        tokens = 0
        if isinstance(message.content, list):
            for item in message.content:
                if 'image_url' in item:
                    tokens += self.IMG_TOKENS
                elif isinstance(item, dict) and 'text' in item:
                    tokens += self._count_text_tokens(item['text'])
        else:
            msg = message.content
            if hasattr(message, 'tool_calls'):
                msg += str(message.tool_calls)  # type: ignore
            tokens += self._count_text_tokens(msg)
        return tokens

    def _count_text_tokens(self, text: str) -> int:
        """Count tokens in a text string"""

        tokens = len(text) // self.estimated_characters_per_token  # Rough estimate if no tokenizer available
        return tokens

    def cut_messages(self):
        """Get current message list, potentially trimmed to max tokens"""
        diff = self.history.total_tokens - self.max_input_tokens
        if diff <= 0:
            return None

        msg = self.history.messages[-1]

        # if list with image remove image
        if isinstance(msg.message.content, list):
            text = ''
            for item in msg.message.content:
                if 'image_url' in item:
                    msg.message.content.remove(item)
                    diff -= self.IMG_TOKENS
                    msg.metadata.input_tokens -= self.IMG_TOKENS
                    self.history.total_tokens -= self.IMG_TOKENS
                    logger.debug(
                        f'Removed image with {self.IMG_TOKENS} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens}'
                    )
                elif 'text' in item and isinstance(item, dict):
                    text += item['text']
            msg.message.content = text
            self.history.messages[-1] = msg

        if diff <= 0:
            return None

        # if still over, remove text from state message proportionally to the number of tokens needed with buffer
        # Calculate the proportion of content to remove
        proportion_to_remove = diff / msg.metadata.input_tokens
        if proportion_to_remove > 0.99:
            raise ValueError(
                f'Max token limit reached - history is too long - reduce the system prompt or task. '
                f'proportion_to_remove: {proportion_to_remove}'
            )
        logger.debug(
            f'Removing {proportion_to_remove * 100:.2f}% of the last message  {proportion_to_remove * msg.metadata.input_tokens:.2f} / {msg.metadata.input_tokens:.2f} tokens)'
        )

        content = msg.message.content
        characters_to_remove = int(len(content) * proportion_to_remove)
        content = content[:-characters_to_remove]

        # remove tokens and old long message
        self.history.remove_message(index=-1)

        # new message with updated content
        msg = HumanMessage(content=content)
        self._add_message_with_tokens(msg)

        last_msg = self.history.messages[-1]

        logger.debug(
            f'Added message with {last_msg.metadata.input_tokens} tokens - total tokens now: {self.history.total_tokens}/{self.max_input_tokens} - total messages: {len(self.history.messages)}'
        )

    def convert_messages_for_non_function_calling_models(self, input_messages: list[BaseMessage]) -> list[BaseMessage]:
        """Convert messages for non-function-calling models"""
        output_messages = []
        for message in input_messages:
            if isinstance(message, HumanMessage):
                output_messages.append(message)
            elif isinstance(message, SystemMessage):
                output_messages.append(message)
            elif isinstance(message, ToolMessage):
                output_messages.append(HumanMessage(content=message.content))
            elif isinstance(message, AIMessage):
                # check if tool_calls is a valid JSON object
                if message.tool_calls:
                    tool_calls = json.dumps(message.tool_calls)
                    output_messages.append(AIMessage(content=tool_calls))
                else:
                    output_messages.append(message)
            else:
                raise ValueError(f'Unknown message type: {type(message)}')
        return output_messages

    def merge_successive_human_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Some models like deepseek-reasoner dont allow multiple human messages in a row. This function merges them into one."""
        merged_messages = []
        streak = 0
        for message in messages:
            if isinstance(message, HumanMessage):
                streak += 1
                if streak > 1:
                    merged_messages[-1].content += message.content
                else:
                    merged_messages.append(message)
            else:
                merged_messages.append(message)
                streak = 0
        return merged_messages

    def extract_json_from_model_output(self, content: str) -> dict:
        """Extract JSON from model output, handling both plain JSON and code-block-wrapped JSON."""
        try:
            # If content is wrapped in code blocks, extract just the JSON part
            if content.startswith(''):
                # Find the JSON content between code blocks
                content = content.split('')[1]
                # Remove language identifier if present (e.g., 'json\n')
                if '\n' in content:
                    content = content.split('\n', 1)[1]
            # Parse the cleaned content
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f'Failed to parse model output: {str(e)}')
            raise ValueError('Could not parse response.')

    async def _remove_last_state_message(self, previous_state, previous_step_id, model_output, task_roadmap):
            """Remove the last state message based on LLM decision."""
            # Construct a prompt for the AI
            prompt = (
            f"Previous state URL: {previous_state.url}\n"
            f"Previous state title: {previous_state.title}\n"
            f"Evaluation of previous goals: {model_output.current_state.evaluation_previous_goal}\n"
            f"Memory of previous interactions: {model_output.current_state.memory}\n"
            f"Next intended goal: {model_output.current_state.next_goal}\n"
            f"Task roadmap: {task_roadmap}\n"
            "Based on this information, should the previous state be removed if it is not needed to continue and finish the task sucessfully? Answer 'yes' to remove it, 'no' to keep it."
            )
            client = OpenAI()
            # Query the OpenAI API
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Adjust the model name as necessary
                messages=[
                    {"role": "system", "content": "You are an assistant to help decide if browser states should be retained. Answer in a simple yes or no."},
                    {"role": "user", "content": prompt}
                ]
            )

            # Assuming the response includes whether to remove the state or not
            decision = response.choices[0].message.content.strip().lower()
            memory_logger.info(f"LLM decision on removing state with ID {previous_step_id}: {decision}")
            should_remove = decision.lower() == "yes"

            # Log the current state of history before attempting to remove
            memory_logger.info(f"Current history length: {len(self.history.messages)}")
            memory_logger.info(f"LLM decision on removing state with ID {previous_step_id}: {decision}")

            # # Log types of the last three messages if they exist
            # last_messages = self.history.messages[-3:]  # Get the last three messages
            # for i, msg in enumerate(reversed(last_messages), 1):
            #     memory_logger.info(f"Message {i} from last: Type: {type(msg.message)}")
            
            # for i, msg in enumerate(self.history.messages):
            #     memory_logger.info(f"Message {i}: type={type(msg)}, has step_id={hasattr(msg, 'step_id')}")
            #     memory_logger.info(f"Message {i}: message type={type(msg.message)}, has step_id={hasattr(msg.message, 'step_id')}")


            # Check AI decision and remove if appropriate
            if should_remove and any(msg for msg in self.history.messages if getattr(msg.message, 'step_id', None) == previous_step_id):
                # Find the message with the specific step_id and remove it
                self.history.messages = [msg for msg in self.history.messages if getattr(msg.message, 'step_id', None) != previous_step_id]
                memory_logger.info(f"Removed state message with ID {previous_step_id} based on LLM decision.")
            else:
                memory_logger.info("LLM decision was to keep the previous state message or message not found.")
