"""
Browser actions module.
"""

from datetime import datetime
from typing import Optional, Union

from dateutil.parser import parse, ParserError
from playwright.async_api import ElementHandle, Locator, TimeoutError

class DatePickerAction:
    """Action for handling date picker inputs."""

    def __init__(self, context):
        """Initialize the action."""
        self.context = context
        self.last_error = None

    async def execute(
        self,
        element: Union[ElementHandle, Locator, str],
        date_value: Union[str, datetime],
        format: Optional[str] = None
    ) -> bool:
        """Execute the date picker action.
        
        Args:
            element: The date picker element or selector
            date_value: Date to set (string or datetime)
            format: Expected date format
            
        Returns:
            True if successful, False otherwise
        """
        try:
            page = await self.context.get_current_page()
            
            # Get element if selector
            if isinstance(element, str):
                try:
                    element = await page.wait_for_selector(element)
                    if not element:
                        self.last_error = ValueError(f"Element not found: {element}")
                        return False
                except TimeoutError:
                    self.last_error = ValueError(f"Element not found: {element}")
                    return False

            # Parse date if string
            if isinstance(date_value, str):
                try:
                    date_obj = parse(date_value)
                    date_str = date_obj.strftime(format or "%Y-%m-%d")
                except ParserError:
                    self.last_error = ValueError(f"Invalid date: {date_value}")
                    return False
            else:
                date_str = date_value.strftime(format or "%Y-%m-%d")

            # Clear existing value
            await element.fill("")
            
            # Input the date
            await element.fill(date_str)
            
            # Verify the input
            value = await element.input_value()
            return bool(value)

        except Exception as e:
            self.last_error = e
            return False 