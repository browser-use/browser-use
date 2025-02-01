<a id="conftest"></a>

# conftest

<a id="browser_use"></a>

# browser\_use

<a id="browser_use.logging_config"></a>

# browser\_use.logging\_config

<a id="browser_use.logging_config.addLoggingLevel"></a>

#### addLoggingLevel

```python
def addLoggingLevel(levelName, levelNum, methodName=None)
```

Comprehensively adds a new logging level to the `logging` module and the
currently configured logging class.

`levelName` becomes an attribute of the `logging` module with the value
`levelNum`. `methodName` becomes a convenience method for both `logging`
itself and the class returned by `logging.getLoggerClass()` (usually just
`logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
used.

To avoid accidental clobberings of existing attributes, this method will
raise an `AttributeError` if the level name is already an attribute of the
`logging` module or if the method name is already present

Example
-------
>>> addLoggingLevel('TRACE', logging.DEBUG - 5)
>>> logging.getLogger(__name__).setLevel('TRACE')
>>> logging.getLogger(__name__).trace('that worked')
>>> logging.trace('so did this')
>>> logging.TRACE
5

<a id="browser_use.agent.service"></a>

# browser\_use.agent.service

<a id="browser_use.agent.service.Agent"></a>

## Agent Objects

```python
class Agent()
```

<a id="browser_use.agent.service.Agent.step"></a>

#### step

```python
@time_execution_async('--step')
async def step(step_info: Optional[AgentStepInfo] = None) -> None
```

Execute one step of the task

<a id="browser_use.agent.service.Agent.get_next_action"></a>

#### get\_next\_action

```python
@time_execution_async('--get_next_action')
async def get_next_action(input_messages: list[BaseMessage]) -> AgentOutput
```

Get next action from LLM based on current state

<a id="browser_use.agent.service.Agent.run"></a>

#### run

```python
@observe(name='agent.run')
async def run(max_steps: int = 100) -> AgentHistoryList
```

Execute the task with maximum number of steps

<a id="browser_use.agent.service.Agent.rerun_history"></a>

#### rerun\_history

```python
async def rerun_history(
        history: AgentHistoryList,
        max_retries: int = 3,
        skip_failures: bool = True,
        delay_between_actions: float = 2.0) -> list[ActionResult]
```

Rerun a saved history of actions with error handling and retry logic.

**Arguments**:

- `history` - The history to replay
- `max_retries` - Maximum number of retries per action
- `skip_failures` - Whether to skip failed actions or stop execution
- `delay_between_actions` - Delay between actions in seconds
  

**Returns**:

  List of action results

<a id="browser_use.agent.service.Agent.load_and_rerun"></a>

#### load\_and\_rerun

```python
async def load_and_rerun(history_file: Optional[str | Path] = None,
                         **kwargs) -> list[ActionResult]
```

Load history from file and rerun it.

**Arguments**:

- `history_file` - Path to the history file
- `**kwargs` - Additional arguments passed to rerun_history

<a id="browser_use.agent.service.Agent.save_history"></a>

#### save\_history

```python
def save_history(file_path: Optional[str | Path] = None) -> None
```

Save the history to a file

<a id="browser_use.agent.service.Agent.create_history_gif"></a>

#### create\_history\_gif

```python
def create_history_gif(output_path: str = 'agent_history.gif',
                       duration: int = 3000,
                       show_goals: bool = True,
                       show_task: bool = True,
                       show_logo: bool = False,
                       font_size: int = 40,
                       title_font_size: int = 56,
                       goal_font_size: int = 44,
                       margin: int = 40,
                       line_spacing: float = 1.5) -> None
```

Create a GIF from the agent's history with overlaid task and goal text.

<a id="browser_use.agent.service.Agent.pause"></a>

#### pause

```python
def pause() -> None
```

Pause the agent before the next step

<a id="browser_use.agent.service.Agent.resume"></a>

#### resume

```python
def resume() -> None
```

Resume the agent

<a id="browser_use.agent.service.Agent.stop"></a>

#### stop

```python
def stop() -> None
```

Stop the agent

<a id="browser_use.agent.prompts"></a>

# browser\_use.agent.prompts

<a id="browser_use.agent.prompts.SystemPrompt"></a>

## SystemPrompt Objects

```python
class SystemPrompt()
```

<a id="browser_use.agent.prompts.SystemPrompt.important_rules"></a>

#### important\_rules

```python
def important_rules() -> str
```

Returns the important rules for the agent.

<a id="browser_use.agent.prompts.SystemPrompt.get_system_message"></a>

#### get\_system\_message

```python
def get_system_message() -> SystemMessage
```

Get the system prompt for the agent.

**Returns**:

- `str` - Formatted system prompt

<a id="browser_use.agent.message_manager.service"></a>

# browser\_use.agent.message\_manager.service

<a id="browser_use.agent.message_manager.service.MessageManager"></a>

## MessageManager Objects

```python
class MessageManager()
```

<a id="browser_use.agent.message_manager.service.MessageManager.add_state_message"></a>

#### add\_state\_message

```python
def add_state_message(state: BrowserState,
                      result: Optional[List[ActionResult]] = None,
                      step_info: Optional[AgentStepInfo] = None) -> None
```

Add browser state as human message

<a id="browser_use.agent.message_manager.service.MessageManager.add_model_output"></a>

#### add\_model\_output

```python
def add_model_output(model_output: AgentOutput) -> None
```

Add model output as AI message

<a id="browser_use.agent.message_manager.service.MessageManager.get_messages"></a>

#### get\_messages

```python
def get_messages() -> List[BaseMessage]
```

Get current message list, potentially trimmed to max tokens

<a id="browser_use.agent.message_manager.service.MessageManager.cut_messages"></a>

#### cut\_messages

```python
def cut_messages()
```

Get current message list, potentially trimmed to max tokens

<a id="browser_use.agent.message_manager.service.MessageManager.convert_messages_for_non_function_calling_models"></a>

#### convert\_messages\_for\_non\_function\_calling\_models

```python
def convert_messages_for_non_function_calling_models(
        input_messages: list[BaseMessage]) -> list[BaseMessage]
```

Convert messages for non-function-calling models

<a id="browser_use.agent.message_manager.service.MessageManager.merge_successive_human_messages"></a>

#### merge\_successive\_human\_messages

```python
def merge_successive_human_messages(
        messages: list[BaseMessage]) -> list[BaseMessage]
```

Some models like deepseek-reasoner dont allow multiple human messages in a row. This function merges them into one.

<a id="browser_use.agent.message_manager.service.MessageManager.extract_json_from_model_output"></a>

#### extract\_json\_from\_model\_output

```python
def extract_json_from_model_output(content: str) -> dict
```

Extract JSON from model output, handling both plain JSON and code-block-wrapped JSON.

<a id="browser_use.agent.message_manager.tests"></a>

# browser\_use.agent.message\_manager.tests

<a id="browser_use.agent.message_manager.tests.test_initial_messages"></a>

#### test\_initial\_messages

```python
def test_initial_messages(message_manager: MessageManager)
```

Test that message manager initializes with system and task messages

<a id="browser_use.agent.message_manager.tests.test_add_state_message"></a>

#### test\_add\_state\_message

```python
def test_add_state_message(message_manager: MessageManager)
```

Test adding browser state message

<a id="browser_use.agent.message_manager.tests.test_add_state_with_memory_result"></a>

#### test\_add\_state\_with\_memory\_result

```python
def test_add_state_with_memory_result(message_manager: MessageManager)
```

Test adding state with result that should be included in memory

<a id="browser_use.agent.message_manager.tests.test_add_state_with_non_memory_result"></a>

#### test\_add\_state\_with\_non\_memory\_result

```python
def test_add_state_with_non_memory_result(message_manager: MessageManager)
```

Test adding state with result that should not be included in memory

<a id="browser_use.agent.message_manager.tests.test_token_overflow_handling_with_real_flow"></a>

#### test\_token\_overflow\_handling\_with\_real\_flow

```python
@pytest.mark.skip('not sure how to fix this')
@pytest.mark.parametrize('max_tokens', [100000, 10000, 5000])
def test_token_overflow_handling_with_real_flow(
        message_manager: MessageManager, max_tokens)
```

Test handling of token overflow in a realistic message flow

<a id="browser_use.agent.message_manager.views"></a>

# browser\_use.agent.message\_manager.views

<a id="browser_use.agent.message_manager.views.MessageMetadata"></a>

## MessageMetadata Objects

```python
class MessageMetadata(BaseModel)
```

Metadata for a message including token counts

<a id="browser_use.agent.message_manager.views.ManagedMessage"></a>

## ManagedMessage Objects

```python
class ManagedMessage(BaseModel)
```

A message with its metadata

<a id="browser_use.agent.message_manager.views.MessageHistory"></a>

## MessageHistory Objects

```python
class MessageHistory(BaseModel)
```

Container for message history with metadata

<a id="browser_use.agent.message_manager.views.MessageHistory.add_message"></a>

#### add\_message

```python
def add_message(message: BaseMessage, metadata: MessageMetadata) -> None
```

Add a message with metadata

<a id="browser_use.agent.message_manager.views.MessageHistory.remove_message"></a>

#### remove\_message

```python
def remove_message(index: int = -1) -> None
```

Remove last message from history

<a id="browser_use.agent.tests"></a>

# browser\_use.agent.tests

<a id="browser_use.agent.views"></a>

# browser\_use.agent.views

<a id="browser_use.agent.views.ActionResult"></a>

## ActionResult Objects

```python
class ActionResult(BaseModel)
```

Result of executing an action

<a id="browser_use.agent.views.ActionResult.include_in_memory"></a>

#### include\_in\_memory

whether to include in past messages as context or not

<a id="browser_use.agent.views.AgentBrain"></a>

## AgentBrain Objects

```python
class AgentBrain(BaseModel)
```

Current state of the agent

<a id="browser_use.agent.views.AgentOutput"></a>

## AgentOutput Objects

```python
class AgentOutput(BaseModel)
```

Output model for agent

@dev note: this model is extended with custom actions in AgentService. You can also use some fields that are not in this model as provided by the linter, as long as they are registered in the DynamicActions model.

<a id="browser_use.agent.views.AgentOutput.type_with_custom_actions"></a>

#### type\_with\_custom\_actions

```python
@staticmethod
def type_with_custom_actions(
        custom_actions: Type[ActionModel]) -> Type['AgentOutput']
```

Extend actions with custom actions

<a id="browser_use.agent.views.AgentHistory"></a>

## AgentHistory Objects

```python
class AgentHistory(BaseModel)
```

History item for agent actions

<a id="browser_use.agent.views.AgentHistory.model_dump"></a>

#### model\_dump

```python
def model_dump(**kwargs) -> Dict[str, Any]
```

Custom serialization handling circular references

<a id="browser_use.agent.views.AgentHistoryList"></a>

## AgentHistoryList Objects

```python
class AgentHistoryList(BaseModel)
```

List of agent history items

<a id="browser_use.agent.views.AgentHistoryList.__str__"></a>

#### \_\_str\_\_

```python
def __str__() -> str
```

Representation of the AgentHistoryList object

<a id="browser_use.agent.views.AgentHistoryList.__repr__"></a>

#### \_\_repr\_\_

```python
def __repr__() -> str
```

Representation of the AgentHistoryList object

<a id="browser_use.agent.views.AgentHistoryList.save_to_file"></a>

#### save\_to\_file

```python
def save_to_file(filepath: str | Path) -> None
```

Save history to JSON file with proper serialization

<a id="browser_use.agent.views.AgentHistoryList.model_dump"></a>

#### model\_dump

```python
def model_dump(**kwargs) -> Dict[str, Any]
```

Custom serialization that properly uses AgentHistory's model_dump

<a id="browser_use.agent.views.AgentHistoryList.load_from_file"></a>

#### load\_from\_file

```python
@classmethod
def load_from_file(cls, filepath: str | Path,
                   output_model: Type[AgentOutput]) -> 'AgentHistoryList'
```

Load history from JSON file

<a id="browser_use.agent.views.AgentHistoryList.last_action"></a>

#### last\_action

```python
def last_action() -> None | dict
```

Last action in history

<a id="browser_use.agent.views.AgentHistoryList.errors"></a>

#### errors

```python
def errors() -> list[str]
```

Get all errors from history

<a id="browser_use.agent.views.AgentHistoryList.final_result"></a>

#### final\_result

```python
def final_result() -> None | str
```

Final result from history

<a id="browser_use.agent.views.AgentHistoryList.is_done"></a>

#### is\_done

```python
def is_done() -> bool
```

Check if the agent is done

<a id="browser_use.agent.views.AgentHistoryList.has_errors"></a>

#### has\_errors

```python
def has_errors() -> bool
```

Check if the agent has any errors

<a id="browser_use.agent.views.AgentHistoryList.urls"></a>

#### urls

```python
def urls() -> list[str]
```

Get all unique URLs from history

<a id="browser_use.agent.views.AgentHistoryList.screenshots"></a>

#### screenshots

```python
def screenshots() -> list[str]
```

Get all screenshots from history

<a id="browser_use.agent.views.AgentHistoryList.action_names"></a>

#### action\_names

```python
def action_names() -> list[str]
```

Get all action names from history

<a id="browser_use.agent.views.AgentHistoryList.model_thoughts"></a>

#### model\_thoughts

```python
def model_thoughts() -> list[AgentBrain]
```

Get all thoughts from history

<a id="browser_use.agent.views.AgentHistoryList.model_outputs"></a>

#### model\_outputs

```python
def model_outputs() -> list[AgentOutput]
```

Get all model outputs from history

<a id="browser_use.agent.views.AgentHistoryList.model_actions"></a>

#### model\_actions

```python
def model_actions() -> list[dict]
```

Get all actions from history

<a id="browser_use.agent.views.AgentHistoryList.action_results"></a>

#### action\_results

```python
def action_results() -> list[ActionResult]
```

Get all results from history

<a id="browser_use.agent.views.AgentHistoryList.extracted_content"></a>

#### extracted\_content

```python
def extracted_content() -> list[str]
```

Get all extracted content from history

<a id="browser_use.agent.views.AgentHistoryList.model_actions_filtered"></a>

#### model\_actions\_filtered

```python
def model_actions_filtered(include: list[str] = []) -> list[dict]
```

Get all model actions from history as JSON

<a id="browser_use.agent.views.AgentError"></a>

## AgentError Objects

```python
class AgentError()
```

Container for agent error handling

<a id="browser_use.agent.views.AgentError.format_error"></a>

#### format\_error

```python
@staticmethod
def format_error(error: Exception, include_trace: bool = False) -> str
```

Format error message based on error type and optionally include trace

<a id="browser_use.controller.service"></a>

# browser\_use.controller.service

<a id="browser_use.controller.service.Controller"></a>

## Controller Objects

```python
class Controller()
```

<a id="browser_use.controller.service.Controller.action"></a>

#### action

```python
def action(description: str, **kwargs)
```

Decorator for registering custom actions

@param description: Describe the LLM what the function does (better description == better function calling)

<a id="browser_use.controller.service.Controller.multi_act"></a>

#### multi\_act

```python
@time_execution_async('--multi-act')
async def multi_act(actions: list[ActionModel],
                    browser_context: BrowserContext,
                    check_for_new_elements: bool = True) -> list[ActionResult]
```

Execute multiple actions

<a id="browser_use.controller.service.Controller.act"></a>

#### act

```python
@time_execution_sync('--act')
async def act(action: ActionModel,
              browser_context: BrowserContext) -> ActionResult
```

Execute an action

<a id="browser_use.controller.registry.service"></a>

# browser\_use.controller.registry.service

<a id="browser_use.controller.registry.service.Registry"></a>

## Registry Objects

```python
class Registry()
```

Service for registering and managing actions

<a id="browser_use.controller.registry.service.Registry.action"></a>

#### action

```python
def action(description: str,
           param_model: Optional[Type[BaseModel]] = None,
           requires_browser: bool = False)
```

Decorator for registering actions

<a id="browser_use.controller.registry.service.Registry.execute_action"></a>

#### execute\_action

```python
async def execute_action(action_name: str,
                         params: dict,
                         browser: Optional[BrowserContext] = None) -> Any
```

Execute a registered action

<a id="browser_use.controller.registry.service.Registry.create_action_model"></a>

#### create\_action\_model

```python
def create_action_model() -> Type[ActionModel]
```

Creates a Pydantic model from registered actions

<a id="browser_use.controller.registry.service.Registry.get_prompt_description"></a>

#### get\_prompt\_description

```python
def get_prompt_description() -> str
```

Get a description of all actions for the prompt

<a id="browser_use.controller.registry.views"></a>

# browser\_use.controller.registry.views

<a id="browser_use.controller.registry.views.RegisteredAction"></a>

## RegisteredAction Objects

```python
class RegisteredAction(BaseModel)
```

Model for a registered action

<a id="browser_use.controller.registry.views.RegisteredAction.prompt_description"></a>

#### prompt\_description

```python
def prompt_description() -> str
```

Get a description of the action for the prompt

<a id="browser_use.controller.registry.views.ActionModel"></a>

## ActionModel Objects

```python
class ActionModel(BaseModel)
```

Base model for dynamically created action models

<a id="browser_use.controller.registry.views.ActionModel.get_index"></a>

#### get\_index

```python
def get_index() -> int | None
```

Get the index of the action

<a id="browser_use.controller.registry.views.ActionModel.set_index"></a>

#### set\_index

```python
def set_index(index: int)
```

Overwrite the index of the action

<a id="browser_use.controller.registry.views.ActionRegistry"></a>

## ActionRegistry Objects

```python
class ActionRegistry(BaseModel)
```

Model representing the action registry

<a id="browser_use.controller.registry.views.ActionRegistry.get_prompt_description"></a>

#### get\_prompt\_description

```python
def get_prompt_description() -> str
```

Get a description of all actions for the prompt

<a id="browser_use.controller.views"></a>

# browser\_use.controller.views

<a id="browser_use.controller.views.ScrollAction"></a>

## ScrollAction Objects

```python
class ScrollAction(BaseModel)
```

<a id="browser_use.controller.views.ScrollAction.amount"></a>

#### amount

The number of pixels to scroll. If None, scroll down/up one page

<a id="browser_use.controller.views.NoParamsAction"></a>

## NoParamsAction Objects

```python
class NoParamsAction(BaseModel)
```

Accepts absolutely anything in the incoming data
and discards it, so the final parsed model is empty.

<a id="browser_use.browser.tests.test_clicks"></a>

# browser\_use.browser.tests.test\_clicks

<a id="browser_use.browser.tests.screenshot_test"></a>

# browser\_use.browser.tests.screenshot\_test

<a id="browser_use.browser.browser"></a>

# browser\_use.browser.browser

Playwright browser on steroids.

<a id="browser_use.browser.browser.BrowserConfig"></a>

## BrowserConfig Objects

```python
@dataclass
class BrowserConfig()
```

Configuration for the Browser.

Default values:
	headless: True
		Whether to run browser in headless mode

	disable_security: False
		Disable browser security features

	extra_chromium_args: []
		Extra arguments to pass to the browser

	wss_url: None
		Connect to a browser instance via WebSocket

	cdp_url: None
		Connect to a browser instance via CDP

	chrome_instance_path: None
		Path to a Chrome instance to use to connect to your normal browser
		e.g. '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'

<a id="browser_use.browser.browser.Browser"></a>

## Browser Objects

```python
class Browser()
```

Playwright browser on steroids.

This is persistant browser factory that can spawn multiple browser contexts.
It is recommended to use only one instance of Browser per your application (RAM usage will grow otherwise).

<a id="browser_use.browser.browser.Browser.new_context"></a>

#### new\_context

```python
async def new_context(config: BrowserContextConfig = BrowserContextConfig()
                      ) -> BrowserContext
```

Create a browser context

<a id="browser_use.browser.browser.Browser.get_playwright_browser"></a>

#### get\_playwright\_browser

```python
async def get_playwright_browser() -> PlaywrightBrowser
```

Get a browser context

<a id="browser_use.browser.browser.Browser.close"></a>

#### close

```python
async def close()
```

Close the browser instance

<a id="browser_use.browser.browser.Browser.__del__"></a>

#### \_\_del\_\_

```python
def __del__()
```

Async cleanup when object is destroyed

<a id="browser_use.browser.context"></a>

# browser\_use.browser.context

Playwright browser on steroids.

<a id="browser_use.browser.context.BrowserContextConfig"></a>

## BrowserContextConfig Objects

```python
@dataclass
class BrowserContextConfig()
```

Configuration for the BrowserContext.

Default values:
cookies_file: None
Path to cookies file for persistence

disable_security: False
Disable browser security features

minimum_wait_page_load_time: 0.5
Minimum time to wait before getting page state for LLM input

wait_for_network_idle_page_load_time: 1.0
Time to wait for network requests to finish before getting page state.
Lower values may result in incomplete page loads.

maximum_wait_page_load_time: 5.0
Maximum time to wait for page load before proceeding anyway

wait_between_actions: 1.0
Time to wait between multiple per step actions

browser_window_size: {
'width': 1280,
'height': 1100,
}
Default browser window size

no_viewport: False
Disable viewport

save_recording_path: None
Path to save video recordings

save_downloads_path: None
Path to save downloads to

trace_path: None
Path to save trace files. It will auto name the file with the TRACE_PATH/{context_id}.zip

locale: None
Specify user locale, for example en-GB, de-DE, etc. Locale will affect navigator.language value, Accept-Language request header value as well as number and date formatting rules. If not provided, defaults to the system default locale.

user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36'
custom user agent to use.

highlight_elements: True
Highlight elements in the DOM on the screen

viewport_expansion: 500
Viewport expansion in pixels. This amount will increase the number of elements which are included in the state what the LLM will see. If set to -1, all elements will be included (this leads to high token usage). If set to 0, only the elements which are visible in the viewport will be included.

allowed_domains: None
List of allowed domains that can be accessed. If None, all domains are allowed.
Example: ['example.com', 'api.example.com']

include_dynamic_attributes: bool = True
Include dynamic attributes in the CSS selector. If you want to reuse the css_selectors, it might be better to set this to False.

<a id="browser_use.browser.context.BrowserContext"></a>

## BrowserContext Objects

```python
class BrowserContext()
```

<a id="browser_use.browser.context.BrowserContext.__aenter__"></a>

#### \_\_aenter\_\_

```python
async def __aenter__()
```

Async context manager entry

<a id="browser_use.browser.context.BrowserContext.__aexit__"></a>

#### \_\_aexit\_\_

```python
async def __aexit__(exc_type, exc_val, exc_tb)
```

Async context manager exit

<a id="browser_use.browser.context.BrowserContext.close"></a>

#### close

```python
async def close()
```

Close the browser instance

<a id="browser_use.browser.context.BrowserContext.__del__"></a>

#### \_\_del\_\_

```python
def __del__()
```

Cleanup when object is destroyed

<a id="browser_use.browser.context.BrowserContext.get_session"></a>

#### get\_session

```python
async def get_session() -> BrowserSession
```

Lazy initialization of the browser and related components

<a id="browser_use.browser.context.BrowserContext.get_current_page"></a>

#### get\_current\_page

```python
async def get_current_page() -> Page
```

Get the current page

<a id="browser_use.browser.context.BrowserContext.navigate_to"></a>

#### navigate\_to

```python
async def navigate_to(url: str)
```

Navigate to a URL

<a id="browser_use.browser.context.BrowserContext.refresh_page"></a>

#### refresh\_page

```python
async def refresh_page()
```

Refresh the current page

<a id="browser_use.browser.context.BrowserContext.go_back"></a>

#### go\_back

```python
async def go_back()
```

Navigate back in history

<a id="browser_use.browser.context.BrowserContext.go_forward"></a>

#### go\_forward

```python
async def go_forward()
```

Navigate forward in history

<a id="browser_use.browser.context.BrowserContext.close_current_tab"></a>

#### close\_current\_tab

```python
async def close_current_tab()
```

Close the current tab

<a id="browser_use.browser.context.BrowserContext.get_page_html"></a>

#### get\_page\_html

```python
async def get_page_html() -> str
```

Get the current page HTML content

<a id="browser_use.browser.context.BrowserContext.execute_javascript"></a>

#### execute\_javascript

```python
async def execute_javascript(script: str)
```

Execute JavaScript code on the page

<a id="browser_use.browser.context.BrowserContext.get_state"></a>

#### get\_state

```python
@time_execution_sync('--get_state')
async def get_state(use_vision: bool = False) -> BrowserState
```

Get the current state of the browser

<a id="browser_use.browser.context.BrowserContext.take_screenshot"></a>

#### take\_screenshot

```python
async def take_screenshot(full_page: bool = False) -> str
```

Returns a base64 encoded screenshot of the current page.

<a id="browser_use.browser.context.BrowserContext.remove_highlights"></a>

#### remove\_highlights

```python
async def remove_highlights()
```

Removes all highlight overlays and labels created by the highlightElement function.
Handles cases where the page might be closed or inaccessible.

<a id="browser_use.browser.context.BrowserContext.get_tabs_info"></a>

#### get\_tabs\_info

```python
async def get_tabs_info() -> list[TabInfo]
```

Get information about all tabs

<a id="browser_use.browser.context.BrowserContext.switch_to_tab"></a>

#### switch\_to\_tab

```python
async def switch_to_tab(page_id: int) -> None
```

Switch to a specific tab by its page_id

@You can also use negative indices to switch to tabs from the end (Pure pythonic way)

<a id="browser_use.browser.context.BrowserContext.create_new_tab"></a>

#### create\_new\_tab

```python
async def create_new_tab(url: str | None = None) -> None
```

Create a new tab and optionally navigate to a URL

<a id="browser_use.browser.context.BrowserContext.save_cookies"></a>

#### save\_cookies

```python
async def save_cookies()
```

Save current cookies to file

<a id="browser_use.browser.context.BrowserContext.is_file_uploader"></a>

#### is\_file\_uploader

```python
async def is_file_uploader(element_node: DOMElementNode,
                           max_depth: int = 3,
                           current_depth: int = 0) -> bool
```

Check if element or its children are file uploaders

<a id="browser_use.browser.context.BrowserContext.get_scroll_info"></a>

#### get\_scroll\_info

```python
async def get_scroll_info(page: Page) -> tuple[int, int]
```

Get scroll position information for the current page.

<a id="browser_use.browser.context.BrowserContext.reset_context"></a>

#### reset\_context

```python
async def reset_context()
```

Reset the browser session
Call this when you don't want to kill the context but just kill the state

<a id="browser_use.browser.views"></a>

# browser\_use.browser.views

<a id="browser_use.browser.views.TabInfo"></a>

## TabInfo Objects

```python
class TabInfo(BaseModel)
```

Represents information about a browser tab

<a id="browser_use.browser.views.BrowserError"></a>

## BrowserError Objects

```python
class BrowserError(Exception)
```

Base class for all browser errors

<a id="browser_use.browser.views.URLNotAllowedError"></a>

## URLNotAllowedError Objects

```python
class URLNotAllowedError(BrowserError)
```

Error raised when a URL is not allowed

<a id="browser_use.utils"></a>

# browser\_use.utils

<a id="browser_use.dom.service"></a>

# browser\_use.dom.service

<a id="browser_use.dom.tests.extraction_test"></a>

# browser\_use.dom.tests.extraction\_test

<a id="browser_use.dom.tests.process_dom_test"></a>

# browser\_use.dom.tests.process\_dom\_test

<a id="browser_use.dom"></a>

# browser\_use.dom

<a id="browser_use.dom.history_tree_processor.service"></a>

# browser\_use.dom.history\_tree\_processor.service

<a id="browser_use.dom.history_tree_processor.service.HistoryTreeProcessor"></a>

## HistoryTreeProcessor Objects

```python
class HistoryTreeProcessor()
```

"
Operations on the DOM elements

@dev be careful - text nodes can change even if elements stay the same

<a id="browser_use.dom.history_tree_processor.view"></a>

# browser\_use.dom.history\_tree\_processor.view

<a id="browser_use.dom.history_tree_processor.view.HashedDomElement"></a>

## HashedDomElement Objects

```python
@dataclass
class HashedDomElement()
```

Hash of the dom element to be used as a unique identifier

<a id="browser_use.dom.views"></a>

# browser\_use.dom.views

<a id="browser_use.dom.views.DOMElementNode"></a>

## DOMElementNode Objects

```python
@dataclass(frozen=False)
class DOMElementNode(DOMBaseNode)
```

xpath: the xpath of the element from the last root node (shadow root or iframe OR document if no shadow root or iframe).
To properly reference the element we need to recursively switch the root node until we find the element (work you way up the tree with `.parent`)

<a id="browser_use.dom.views.DOMElementNode.clickable_elements_to_string"></a>

#### clickable\_elements\_to\_string

```python
def clickable_elements_to_string(include_attributes: list[str] = []) -> str
```

Convert the processed DOM content to HTML.

<a id="browser_use.telemetry.service"></a>

# browser\_use.telemetry.service

<a id="browser_use.telemetry.service.ProductTelemetry"></a>

## ProductTelemetry Objects

```python
@singleton
class ProductTelemetry()
```

Service for capturing anonymized telemetry data.

If the environment variable `ANONYMIZED_TELEMETRY=False`, anonymized telemetry will be disabled.

<a id="browser_use.telemetry.views"></a>

# browser\_use.telemetry.views

