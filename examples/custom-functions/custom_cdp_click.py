"""
# @file purpose: Demonstrates advanced custom click actions using CDP with detailed session and event system integration

Advanced Custom CDP Click Actions for Browser-Use

This example demonstrates how to create sophisticated custom click actions using Chrome DevTools Protocol (CDP)
within the browser-use framework. It showcases:

1. Different types of clicks (single, double, right-click, with modifiers)
2. Proper CDP session management and event handling
3. Custom timing and coordination controls
4. Integration with browser-use's event system
5. Error handling and edge case management

The examples show both direct CDP usage and integration with browser-use's event bus system,
providing patterns for creating robust custom browser automation actions.
"""

import asyncio
import logging
import platform
from typing import Literal, Optional

from pydantic import BaseModel, Field

from browser_use import Agent, Controller, ActionResult
from browser_use.browser.session import BrowserSession


logger = logging.getLogger(__name__)


# =============================================================================
# Custom Click Action Models
# =============================================================================

class CustomClickAction(BaseModel):
    """Advanced click action with CDP-specific options."""
    
    x: int = Field(..., description="X coordinate to click")
    y: int = Field(..., description="Y coordinate to click") 
    button: Literal['left', 'right', 'middle'] = Field(default='left', description="Mouse button to click")
    click_count: int = Field(default=1, description="Number of clicks (1=single, 2=double, etc.)")
    modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] = Field(
        default=[], description="Modifier keys to hold during click"
    )
    delay_before_ms: int = Field(default=100, description="Delay before clicking in milliseconds")
    delay_after_ms: int = Field(default=150, description="Delay after clicking in milliseconds")
    move_mouse_first: bool = Field(default=True, description="Move mouse to position before clicking")


class ElementClickAction(BaseModel):
    """Click an element by index with advanced CDP options."""
    
    element_index: int = Field(..., description="Element index from browser state")
    button: Literal['left', 'right', 'middle'] = Field(default='left', description="Mouse button to click")
    click_count: int = Field(default=1, description="Number of clicks")
    force_coordinates: bool = Field(
        default=False, description="Use coordinate-based clicking instead of element-based"
    )
    offset_x: int = Field(default=0, description="X offset from element center")
    offset_y: int = Field(default=0, description="Y offset from element center")
    modifiers: list[Literal['Alt', 'Control', 'Meta', 'Shift']] = Field(default=[])


# =============================================================================
# CDP Helper Functions
# =============================================================================

def calculate_modifier_bits(modifiers: list[str]) -> int:
    """
    Calculate CDP modifier bitmask from modifier names.
    
    CDP Modifier bits:
    - Alt = 1
    - Control = 2  
    - Meta/Command = 4
    - Shift = 8
    """
    modifier_map = {
        'Alt': 1,
        'Control': 2,
        'Meta': 4,
        'Shift': 8
    }
    
    bits = 0
    for modifier in modifiers:
        if modifier in modifier_map:
            bits |= modifier_map[modifier]
    
    return bits


async def execute_cdp_click_sequence(
    browser_session: BrowserSession,
    x: int,
    y: int,
    button: str = 'left',
    click_count: int = 1,
    modifiers: int = 0,
    delay_before_ms: int = 100,
    delay_after_ms: int = 150,
    move_mouse_first: bool = True
) -> dict:
    """
    Execute a complete click sequence using CDP with precise timing control.
    
    Args:
        browser_session: Active browser session with CDP access
        x, y: Click coordinates
        button: Mouse button ('left', 'right', 'middle')
        click_count: Number of clicks for multi-click actions
        modifiers: CDP modifier bitmask
        delay_before_ms: Delay before clicking
        delay_after_ms: Delay after clicking
        move_mouse_first: Whether to move mouse to position first
        
    Returns:
        Dict with click metadata including timing information
    """
    if not browser_session.agent_focus:
        raise RuntimeError("No active CDP session available")
    
    cdp_session = browser_session.agent_focus
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Pre-click delay
        if delay_before_ms > 0:
            await asyncio.sleep(delay_before_ms / 1000.0)
        
        # Move mouse to position first (recommended for better compatibility)
        if move_mouse_first:
            logger.debug(f"Moving mouse to ({x}, {y})")
            await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
                params={
                    'type': 'mouseMoved',
                    'x': x,
                    'y': y,
                },
                session_id=cdp_session.session_id,
            )
            # Small delay after mouse move for stability
            await asyncio.sleep(0.05)
        
        # Perform the click sequence
        logger.debug(f"Executing {click_count} {button} click(s) at ({x}, {y}) with modifiers: {modifiers}")
        
        # Mouse down
        await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
            params={
                'type': 'mousePressed',
                'x': x,
                'y': y,
                'button': button,
                'clickCount': click_count,
                'modifiers': modifiers,
            },
            session_id=cdp_session.session_id,
        )
        
        # Brief delay between down and up for realistic timing
        await asyncio.sleep(0.02)
        
        # Mouse up
        await cdp_session.cdp_client.send.Input.dispatchMouseEvent(
            params={
                'type': 'mouseReleased',
                'x': x,
                'y': y,
                'button': button,
                'modifiers': modifiers,
            },
            session_id=cdp_session.session_id,
        )
        
        # Post-click delay
        if delay_after_ms > 0:
            await asyncio.sleep(delay_after_ms / 1000.0)
        
        end_time = asyncio.get_event_loop().time()
        total_time_ms = (end_time - start_time) * 1000
        
        return {
            'success': True,
            'coordinates': {'x': x, 'y': y},
            'button': button,
            'click_count': click_count,
            'modifiers': modifiers,
            'total_time_ms': round(total_time_ms, 2),
            'target_id': cdp_session.target_id,
            'session_id': cdp_session.session_id
        }
        
    except Exception as e:
        logger.error(f"CDP click failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'coordinates': {'x': x, 'y': y},
        }


# =============================================================================
# Custom Action Implementations  
# =============================================================================

def register_custom_click_actions(controller: Controller):
    """Register all custom CDP click actions with the controller."""
    
    @controller.action(
        "Perform an advanced custom click at specific coordinates with precise timing and modifier control",
        param_model=CustomClickAction
    )
    async def custom_cdp_click(params: CustomClickAction, browser_session: BrowserSession) -> ActionResult:
        """
        Execute a custom click action using direct CDP commands.
        
        This action provides fine-grained control over click behavior including:
        - Exact coordinate targeting
        - Custom button selection (left/right/middle)
        - Multi-click support (double-click, triple-click, etc.)
        - Modifier key combinations (Ctrl, Alt, Shift, Meta)
        - Precise timing control for delays
        - Optional mouse movement coordination
        
        This is useful for:
        - Clicking on elements that don't have reliable selectors
        - Performing complex click combinations
        - Automating interactions that require precise timing
        - Working with custom web applications that need specific click patterns
        """
        if not browser_session.agent_focus:
            return ActionResult(error="No active browser session available")
        
        # Convert modifier names to CDP bitmask
        modifier_bits = calculate_modifier_bits(params.modifiers)
        
        # Log the action details
        modifier_str = ", ".join(params.modifiers) if params.modifiers else "none"
        logger.info(f"Custom CDP click: {params.click_count}x {params.button} at ({params.x}, {params.y}) with modifiers: {modifier_str}")
        
        # Execute the click
        result = await execute_cdp_click_sequence(
            browser_session=browser_session,
            x=params.x,
            y=params.y,
            button=params.button,
            click_count=params.click_count,
            modifiers=modifier_bits,
            delay_before_ms=params.delay_before_ms,
            delay_after_ms=params.delay_after_ms,
            move_mouse_first=params.move_mouse_first
        )
        
        if result['success']:
            click_type = "double-click" if params.click_count == 2 else f"{params.click_count}x click"
            message = f"Successfully executed {click_type} with {params.button} button at ({params.x}, {params.y})"
            if params.modifiers:
                message += f" with {', '.join(params.modifiers)} modifier(s)"
            
            return ActionResult(
                extracted_content=message,
                include_in_memory=True,
                long_term_memory=f"Custom CDP click: {click_type} at ({params.x}, {params.y})",
                metadata=result
            )
        else:
            return ActionResult(
                error=f"Custom CDP click failed: {result.get('error', 'Unknown error')}",
                metadata=result
            )

    
    @controller.action(
        "Click an element by index using advanced CDP options with coordinate override capability",
        param_model=ElementClickAction
    )
    async def enhanced_element_click(params: ElementClickAction, browser_session: BrowserSession) -> ActionResult:
        """
        Enhanced element clicking with CDP integration.
        
        This action combines element-based targeting with CDP's advanced click capabilities.
        It can:
        - Click elements by their browser-use index
        - Override with direct coordinate clicking if needed
        - Apply custom offsets from element center
        - Use modifier keys for special behaviors
        - Support multi-click actions
        
        The action automatically handles:
        - Element visibility and scroll-into-view
        - Coordinate calculation from element bounds
        - Fallback to coordinate-based clicking
        - Integration with browser-use's element tracking
        """
        if not browser_session.agent_focus:
            return ActionResult(error="No active browser session available")
        
        try:
            # Get the element from browser-use's element tracking
            element = await browser_session.get_element_by_index(params.element_index)
            if not element:
                return ActionResult(error=f"Element with index {params.element_index} not found")
            
            if params.force_coordinates or not element.absolute_position:
                # Use coordinate-based clicking - get element bounds first
                cdp_session = browser_session.agent_focus
                
                # Get element box model from CDP
                box_model_result = await cdp_session.cdp_client.send.DOM.getBoxModel(
                    params={'nodeId': element.node_id},
                    session_id=cdp_session.session_id
                )
                
                if 'model' not in box_model_result:
                    return ActionResult(error=f"Could not get box model for element {params.element_index}")
                
                # Calculate center coordinates from content box
                content_box = box_model_result['model']['content']
                # content_box is [x1, y1, x2, y1, x2, y2, x1, y2] - corners of the rectangle
                center_x = (content_box[0] + content_box[4]) / 2 + params.offset_x
                center_y = (content_box[1] + content_box[5]) / 2 + params.offset_y
                
                # Convert modifier names to CDP bitmask
                modifier_bits = calculate_modifier_bits(params.modifiers)
                
                # Execute click using CDP
                result = await execute_cdp_click_sequence(
                    browser_session=browser_session,
                    x=int(center_x),
                    y=int(center_y),
                    button=params.button,
                    click_count=params.click_count,
                    modifiers=modifier_bits
                )
                
                if result['success']:
                    click_type = "double-click" if params.click_count == 2 else f"{params.click_count}x click"
                    message = f"Enhanced element click: {click_type} on element {params.element_index}"
                    if params.modifiers:
                        message += f" with {', '.join(params.modifiers)} modifier(s)"
                    
                    return ActionResult(
                        extracted_content=message,
                        include_in_memory=True,
                        long_term_memory=f"Enhanced click on element {params.element_index}",
                        metadata={**result, 'element_index': params.element_index}
                    )
                else:
                    return ActionResult(
                        error=f"Enhanced element click failed: {result.get('error', 'Unknown error')}",
                        metadata=result
                    )
            
            else:
                # Use browser-use's built-in element clicking with event system
                from browser_use.browser.events import ClickElementEvent
                
                # For modifier support, we need to handle this specially
                if params.modifiers or params.click_count > 1 or params.button != 'left':
                    # Fall back to coordinate-based clicking for advanced features
                    if element.absolute_position:
                        center_x = element.absolute_position['x'] + element.absolute_position['width'] / 2 + params.offset_x
                        center_y = element.absolute_position['y'] + element.absolute_position['height'] / 2 + params.offset_y
                        
                        modifier_bits = calculate_modifier_bits(params.modifiers)
                        
                        result = await execute_cdp_click_sequence(
                            browser_session=browser_session,
                            x=int(center_x),
                            y=int(center_y),
                            button=params.button,
                            click_count=params.click_count,
                            modifiers=modifier_bits
                        )
                        
                        if result['success']:
                            message = f"Enhanced element click with advanced options on element {params.element_index}"
                            return ActionResult(
                                extracted_content=message,
                                include_in_memory=True,
                                metadata={**result, 'element_index': params.element_index}
                            )
                        else:
                            return ActionResult(error=f"Enhanced element click failed: {result.get('error')}")
                    else:
                        return ActionResult(error="Element position not available for advanced click options")
                
                else:
                    # Use standard browser-use event system for simple clicks
                    event = browser_session.event_bus.dispatch(ClickElementEvent(node=element))
                    await event
                    click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
                    
                    return ActionResult(
                        extracted_content=f"Clicked element {params.element_index} using event system",
                        include_in_memory=True,
                        metadata={'element_index': params.element_index, 'event_result': click_metadata}
                    )
        
        except Exception as e:
            logger.error(f"Enhanced element click failed: {e}")
            return ActionResult(error=f"Enhanced element click failed: {str(e)}")


    @controller.action(
        "Perform a platform-aware 'open in new tab' click that uses the correct modifier key for the current OS"
    )
    async def smart_new_tab_click(element_index: int, browser_session: BrowserSession) -> ActionResult:
        """
        Smart new tab click that automatically uses the correct modifier for the current platform.
        
        - macOS: Uses Cmd+Click (Meta modifier)
        - Windows/Linux: Uses Ctrl+Click (Control modifier)
        
        This demonstrates platform-aware CDP actions and automatic modifier selection.
        """
        if not browser_session.agent_focus:
            return ActionResult(error="No active browser session available")
        
        try:
            # Get the element
            element = await browser_session.get_element_by_index(element_index)
            if not element:
                return ActionResult(error=f"Element with index {element_index} not found")
            
            # Determine correct modifier for platform
            if platform.system() == 'Darwin':
                modifiers = ['Meta']  # Cmd key on macOS
                modifier_name = "Cmd"
            else:
                modifiers = ['Control']  # Ctrl key on Windows/Linux
                modifier_name = "Ctrl"
            
            logger.info(f"Using {modifier_name}+Click for new tab on {platform.system()}")
            
            # Use our enhanced element click with the platform-appropriate modifier
            enhanced_click = ElementClickAction(
                element_index=element_index,
                modifiers=modifiers
            )
            
            result = await enhanced_element_click(enhanced_click, browser_session)
            
            if not result.error:
                # Update the message to reflect the smart modifier selection
                result.extracted_content = f"Smart new-tab click on element {element_index} using {modifier_name}+Click"
                result.long_term_memory = f"Opened element {element_index} in new tab using {modifier_name}+Click"
            
            return result
            
        except Exception as e:
            logger.error(f"Smart new tab click failed: {e}")
            return ActionResult(error=f"Smart new tab click failed: {str(e)}")


# =============================================================================
# Usage Example and Testing
# =============================================================================

async def demonstrate_custom_click_actions():
    """
    Demonstration of custom CDP click actions.
    
    This function shows how to use the custom click actions in practice,
    including session setup, action execution, and result handling.
    """
    from browser_use import Agent
    from langchain_openai import ChatOpenAI
    
    # Create controller with custom actions
    controller = Controller()
    register_custom_click_actions(controller)
    
    # Set up the LLM
    llm = ChatOpenAI(model="gpt-4o-mini")
    
    # Create and run an agent with the custom actions
    task = """
    Navigate to https://example.com and then:
    1. Use a custom CDP click to click at coordinates (100, 200)
    2. Use the enhanced element click to double-click on a link
    3. Use the smart new tab click to open a link in a new tab
    
    Demonstrate the different types of custom click actions available.
    """
    
    agent = Agent(task=task, llm=llm, controller=controller)
    
    # Run the agent
    result = await agent.run()
    
    print("Demonstration completed!")
    print(f"Final result: {result}")


if __name__ == "__main__":
    # Example of how to run the demonstration
    print("Custom CDP Click Actions Example")
    print("=" * 50)
    print(__doc__)
    
    # Note: This would require proper OpenAI API key setup to run
    # asyncio.run(demonstrate_custom_click_actions())
    
    print("\nTo use these custom actions in your own code:")
    print("1. Import this module")
    print("2. Create a Controller instance")
    print("3. Call register_custom_click_actions(controller)")
    print("4. Use the controller with your Agent")