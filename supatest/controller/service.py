import asyncio
import json
import logging
from typing import Dict, Generic, Optional, Type, TypeVar, Union, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel


from browser_use.controller.service import Controller
from browser_use.utils import time_execution_sync

from supatest.browser.context import SupatestBrowserContext
from supatest.agent.views import SupatestActionResult
from supatest.controller.registry.service import SupatestRegistry
from supatest.controller.views import (
    ClickElementAction,
    DoneAction,
    GoBackAction,
    GoToUrlAction,
    InputTextAction,
    NoParamsAction,
    OpenTabAction,
    ScrollAction,
    SendKeysAction,
    SwitchTabAction,
    SelectDropdownOptionAction,
    GetDropdownOptionsAction,
    WaitAction,
)

logger = logging.getLogger(__name__)

Context = TypeVar('Context')


class SupatestController(Controller[Context]):
    """Extended version of Controller that supports supatest functionality"""

    def __init__(
        self,
        exclude_actions: list[str] = [],
        output_model: Optional[Type[BaseModel]] = None,
    ):
        # Initialize with our custom Registry instead of the base one
        self.registry = SupatestRegistry[Context](exclude_actions)

        """Register all default browser actions with supatest support"""

        if output_model is not None:
            # Create a new model that extends the output model with success parameter
            class ExtendedOutputModel(output_model):  # type: ignore
                success: bool = True

            @self.registry.action(
                'Complete task - with return text and if the task is finished (success=True) or not yet completely finished (success=False)',
                param_model=ExtendedOutputModel,
            )
            async def done(params: ExtendedOutputModel):
                output_dict = params.model_dump(exclude={'success'})
                return SupatestActionResult(is_done=True, success=params.success, extracted_content=json.dumps(output_dict))
        else:
            @self.registry.action(
                'Complete task - with return text and if the task is finished (success=True) or not yet  completly finished (success=False), because last step is reached',
                param_model=DoneAction,
            )
            async def done(params: DoneAction):
                return SupatestActionResult(is_done=True, success=params.success, extracted_content=params.text)

        @self.registry.action('Navigate to URL in the current tab', param_model=GoToUrlAction)
        async def go_to_url(params: GoToUrlAction, browser: SupatestBrowserContext):
            page = await browser.get_current_page()
            await page.goto(params.url)
            await page.wait_for_load_state()
            msg = f'🔗  Navigated to {params.url}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Go back', param_model=GoBackAction)
        async def go_back(_: GoBackAction, browser: SupatestBrowserContext):
            await browser.go_back()
            msg = '🔙  Navigated back'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Wait for x seconds default 3', param_model=WaitAction)
        async def wait(params: WaitAction, browser: SupatestBrowserContext):
            page = await browser.get_current_page()
            await page.wait_for_timeout(params.seconds * 1000)
            msg = f'🕒  Waiting for {params.seconds} seconds'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Click element', param_model=ClickElementAction)
        async def click_element(params: ClickElementAction, browser: SupatestBrowserContext):
            session = await browser.get_session()
            element_node = None

            if element_node is None:
                if params.index not in await browser.get_selector_map():
                    message = f'Element with index {params.index} does not exist - retry or use alternative actions'
                    return SupatestActionResult(error=message, isExecuted='failure')
                element_node = await browser.get_dom_element_by_index(params.index)

            initial_pages = len(session.context.pages)

            if await browser.is_file_uploader(element_node):
                msg = f'Index {params.index} - has an element which opens file upload dialog'
                logger.info(msg)
                return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

            try:
                download_path = await browser._click_element_node(element_node)
                if download_path:
                    msg = f'💾  Downloaded file to {download_path}'
                else:
                    msg = f'🖱️  Clicked element with index {params.index}'
                    msg += f': {element_node.get_all_text_till_next_clickable_element(max_depth=2)}'

                logger.info(msg)
                logger.debug(f'Element xpath: {element_node.xpath}')
                
                if len(session.context.pages) > initial_pages:
                    new_tab_msg = 'New tab opened - switching to it'
                    msg += f' - {new_tab_msg}'
                    logger.info(new_tab_msg)
                    await browser.switch_to_tab(-1)
                return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')
            except Exception as e:
                logger.warning(f'Element not clickable - most likely the page changed')
                return SupatestActionResult(error=str(e), isExecuted='failure')

        @self.registry.action('Input text into an interactive element', param_model=InputTextAction)
        async def input_text(params: InputTextAction, browser: SupatestBrowserContext, has_sensitive_data: bool = False):
            element_node = None
            if element_node is None:
                if params.index not in await browser.get_selector_map():
                    message = f'Element index {params.index} does not exist - retry or use alternative actions'
                    SupatestActionResult(error=message, isExecuted='failure')
                    raise Exception(message)
                element_node = await browser.get_dom_element_by_index(params.index)

            await browser._input_text_element_node(element_node, params.text)
            
            if not has_sensitive_data:
                msg = f'⌨️  Input {params.text} into element'
                msg += f' with index {params.index}'
            else:
                msg = f'⌨️  Input sensitive data into element'
                msg += f' with index {params.index}'

            logger.info(msg)
            logger.debug(f'Element xpath: {element_node.xpath}')
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Switch tab', param_model=SwitchTabAction)
        async def switch_tab(params: SwitchTabAction, browser: SupatestBrowserContext):
            await browser.switch_to_tab(params.page_id)
            page = await browser.get_current_page()
            await page.wait_for_load_state()
            msg = f'🔄  Switched to tab {params.page_id}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Open url in new tab', param_model=OpenTabAction)
        async def open_tab(params: OpenTabAction, browser: SupatestBrowserContext):
            await browser.create_new_tab(params.url)
            msg = f'🔗  Opened new tab with {params.url}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Scroll down the page by pixel amount - if no amount is specified, scroll down one page', param_model=ScrollAction)
        async def scroll_down(params: ScrollAction, browser: SupatestBrowserContext):
            page = await browser.get_current_page()
            if params.amount is not None:
                await page.evaluate(f'window.scrollBy(0, {params.amount});')
            else:
                await page.evaluate('window.scrollBy(0, window.innerHeight);')

            amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
            msg = f'🔍  Scrolled down the page by {amount}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Scroll up the page by pixel amount - if no amount is specified, scroll up one page', param_model=ScrollAction)
        async def scroll_up(params: ScrollAction, browser: SupatestBrowserContext):
            page = await browser.get_current_page()
            if params.amount is not None:
                await page.evaluate(f'window.scrollBy(0, -{params.amount});')
            else:
                await page.evaluate('window.scrollBy(0, -window.innerHeight);')

            amount = f'{params.amount} pixels' if params.amount is not None else 'one page'
            msg = f'🔍  Scrolled up the page by {amount}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

        @self.registry.action('Send keyboard keys', param_model=SendKeysAction)
        async def send_keys(params: SendKeysAction, browser: SupatestBrowserContext):
            page = await browser.get_current_page()

            try:
                await page.keyboard.press(params.keys)
            except Exception as e:
                if 'Unknown key' in str(e):
                    for key in params.keys:
                        try:
                            await page.keyboard.press(key)
                        except Exception as e:
                            logger.debug(f'Error sending key {key}: {str(e)}')
                            raise e
                else:
                    raise e
            msg = f'⌨️  Sent keys: {params.keys}'
            logger.info(msg)
            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')
        
        @self.registry.action(
            description='Get all options from a native dropdown',
            param_model=GetDropdownOptionsAction,
        )
        async def get_dropdown_options(params: GetDropdownOptionsAction, browser: SupatestBrowserContext) -> SupatestActionResult:
            """Get all options from a native dropdown"""
            page = await browser.get_current_page()
            selector_map = await browser.get_selector_map()
            dom_element = selector_map[params.index]

            try:
                # Frame-aware approach since we know it works
                all_options = []
                frame_index = 0

                for frame in page.frames:
                    try:
                        options = await frame.evaluate(
                            """
                            (xpath) => {
                                const select = document.evaluate(xpath, document, null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                if (!select) return null;

                                return {
                                    options: Array.from(select.options).map(opt => ({
                                        text: opt.text, //do not trim, because we are doing exact match in select_dropdown_option
                                        value: opt.value,
                                        index: opt.index
                                    })),
                                    id: select.id,
                                    name: select.name
                                };
                            }
                        """,
                            dom_element.xpath,
                        )

                        if options:
                            logger.debug(f'Found dropdown in frame {frame_index}')
                            logger.debug(f'Dropdown ID: {options["id"]}, Name: {options["name"]}')

                            formatted_options = []
                            for opt in options['options']:
                                # encoding ensures AI uses the exact string in select_dropdown_option
                                encoded_text = json.dumps(opt['text'])
                                formatted_options.append(f'{opt["index"]}: text={encoded_text}')

                            all_options.extend(formatted_options)

                    except Exception as frame_e:
                        logger.debug(f'Frame {frame_index} evaluation failed: {str(frame_e)}')

                    frame_index += 1

                if all_options:
                    msg = '\n'.join(all_options)
                    msg += '\nUse the exact text string in select_dropdown_option'
                    logger.info(msg)
                    return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')
                else:
                    msg = 'No options found in any frame for dropdown'
                    logger.info(msg)
                    return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

            except Exception as e:
                logger.error(f'Failed to get dropdown options: {str(e)}')
                msg = f'Error getting options: {str(e)}'
                logger.info(msg)
                return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='failure')

        @self.registry.action(
            description='Select dropdown option for interactive element index by the text of the option you want to select',
            param_model=SelectDropdownOptionAction,
        )
        async def select_dropdown_option(
            params: SelectDropdownOptionAction,
            browser: SupatestBrowserContext,
        ) -> SupatestActionResult:
            """Select dropdown option by the text of the option you want to select"""
            page = await browser.get_current_page()
            selector_map = await browser.get_selector_map()
            dom_element = selector_map[params.index]

            # Validate that we're working with a select element
            if dom_element.tag_name != 'select':
                logger.error(f'Element is not a select! Tag: {dom_element.tag_name}, Attributes: {dom_element.attributes}')
                msg = f'Cannot select option: Element with index {params.index} is a {dom_element.tag_name}, not a select'
                return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='failure')

            logger.debug(f"Attempting to select '{params.text}' using xpath: {dom_element.xpath}")
            logger.debug(f'Element attributes: {dom_element.attributes}')
            logger.debug(f'Element tag: {dom_element.tag_name}')

            xpath = '//' + dom_element.xpath

            try:
                frame_index = 0
                for frame in page.frames:
                    try:
                        logger.debug(f'Trying frame {frame_index} URL: {frame.url}')

                        # First verify we can find the dropdown in this frame
                        find_dropdown_js = """
                            (xpath) => {
                                try {
                                    const select = document.evaluate(xpath, document, null,
                                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                    if (!select) return null;
                                    if (select.tagName.toLowerCase() !== 'select') {
                                        return {
                                            error: `Found element but it's a ${select.tagName}, not a SELECT`,
                                            found: false
                                        };
                                    }
                                    return {
                                        id: select.id,
                                        name: select.name,
                                        found: true,
                                        tagName: select.tagName,
                                        optionCount: select.options.length,
                                        currentValue: select.value,
                                        availableOptions: Array.from(select.options).map(o => o.text.trim())
                                    };
                                } catch (e) {
                                    return {error: e.toString(), found: false};
                                }
                            }
                        """

                        dropdown_info = await frame.evaluate(find_dropdown_js, dom_element.xpath)

                        if dropdown_info:
                            if not dropdown_info.get('found'):
                                logger.error(f'Frame {frame_index} error: {dropdown_info.get("error")}')
                                continue

                            logger.debug(f'Found dropdown in frame {frame_index}: {dropdown_info}')

                            # "label" because we are selecting by text
                            # nth(0) to disable error thrown by strict mode
                            # timeout=1000 because we are already waiting for all network events, therefore ideally we don't need to wait a lot here (default 30s)
                            selected_option_values = (
                                await frame.locator('//' + dom_element.xpath).nth(0).select_option(label=params.text, timeout=1000)
                            )

                            msg = f'selected option {params.text} with value {selected_option_values}'
                            logger.info(msg + f' in frame {frame_index}')

                            return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='success')

                    except Exception as frame_e:
                        logger.error(f'Frame {frame_index} attempt failed: {str(frame_e)}')
                        logger.error(f'Frame type: {type(frame)}')
                        logger.error(f'Frame URL: {frame.url}')

                    frame_index += 1

                msg = f"Could not select option '{params.text}' in any frame"
                logger.info(msg)
                return SupatestActionResult(extracted_content=msg, include_in_memory=True, isExecuted='failure')

            except Exception as e:
                msg = f'Selection failed: {str(e)}'
                logger.error(msg)
                return SupatestActionResult(error=msg, include_in_memory=True, isExecuted='failure')


      
    @time_execution_sync('--act')
    async def act(
        self,
        action: BaseModel,  # Using BaseModel instead of ActionModel to support both formats
        browser_context: SupatestBrowserContext,
        page_extraction_llm: Optional[BaseChatModel] = None,
        sensitive_data: Optional[Dict[str, str]] = None,
        available_file_paths: Optional[list[str]] = None,
        context: Context | None = None,
    ) -> SupatestActionResult:
        """Execute an action with supatest support"""
        try:
            # Process action in the new non-nested format
            action_data = action.model_dump(exclude_unset=True)
            for action_name, params in action_data.items():
                if params is not None:
                    # Execute the action
                    result = await self.registry.execute_action(
                        action_name,
                        params,
                        browser=browser_context,
                        page_extraction_llm=page_extraction_llm,
                        sensitive_data=sensitive_data,
                        available_file_paths=available_file_paths,
                        context=context,
                    )
                    return self._process_result(result)
            return SupatestActionResult()
        except Exception as e:
            raise e

    def _process_result(self, result):
        """Process the result of an action execution"""
        if isinstance(result, str):
            return SupatestActionResult(extracted_content=result)
        elif isinstance(result, SupatestActionResult):
            return result
        elif result is None:
            return SupatestActionResult()
        else:
            raise ValueError(f'Invalid action result type: {type(result)} of {result}') 