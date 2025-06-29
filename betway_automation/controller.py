import asyncio
from browser_use import Controller, ActionResult, BrowserSession

# Fix the import to work when running scripts directly
try:
    from .models import LoginAction, MarketAction, BetAction
except ImportError:
    # Fallback for when running the script directly
    from models import LoginAction, MarketAction, BetAction


class BetWayController(Controller):
    """
    A specialized controller for Betway betting automation.
    Extends the base Controller with Betway-specific actions.
    """

    def __init__(self):
        # Call the parent constructor to get default actions
        super().__init__()

        # Register our custom login action
        @self.registry.action(
            "Log into Betway using username/mobile and password",
            param_model=LoginAction,
            domains=["betway.co.za", "www.betway.co.za"],
        )
        async def login_user(
            params: LoginAction, browser_session: BrowserSession
        ) -> ActionResult:
            """
            Logs into Betway using the provided credentials.
            """
            print(
                "🎯 CUSTOM LOGIN ACTION CALLED! Using our specialized login_user action"
            )
            print(f"🔑 Username: {params.username}")
            print(
                f"🔐 Password: {'*' * len(params.password)} (length: {len(params.password)})"
            )

            try:
                page = await browser_session.get_current_page()

                # Step 1: Find and fill the mobile/username field
                # Using the ID selector we identified as most reliable
                username_field = await page.query_selector("#MobileNumber")
                if not username_field:
                    # Fallback selector
                    username_field = await page.query_selector(
                        "input[name='MobileNumber']"
                    )

                if not username_field:
                    return ActionResult(
                        error="Could not find username/mobile field on the page."
                    )

                await username_field.fill(params.username)

                # Step 2: Find and fill the password field
                password_field = await page.query_selector("#Password")
                if not password_field:
                    return ActionResult(
                        error="Could not find password field on the page."
                    )

                await password_field.fill(params.password)

                # Step 3: Find and click the login button
                login_button = await page.query_selector("#Login")
                if not login_button:
                    # Fallback selector
                    login_button = await page.query_selector(
                        "button[type='submit']:has-text('Login')"
                    )

                if not login_button:
                    return ActionResult(
                        error="Could not find login button on the page."
                    )

                await login_button.click()

                # Step 4: Wait for navigation or login completion
                # Give it a few seconds to process the login
                await page.wait_for_timeout(7000)

                # Step 5: Check if login was successful
                # Look for indicators that we're logged in
                current_url = page.url

                # Simple success check - if we're redirected away from login page
                if (
                    "login" not in current_url.lower()
                    or "account" in current_url.lower()
                ):
                    return ActionResult(
                        extracted_content=f"✅ Successfully logged into Betway. Current URL: {current_url}"
                    )
                else:
                    # Check for error messages on the page
                    error_element = await page.query_selector(
                        ".error-message, .alert-danger, [class*='error']"
                    )
                    if error_element:
                        error_text = await error_element.text_content()
                        return ActionResult(error=f"Login failed: {error_text}")
                    else:
                        return ActionResult(
                            error="Login may have failed - still on login page with no clear error message."
                        )

            except Exception as e:
                return ActionResult(
                    error=f"Login action failed with exception: {str(e)}"
                )

        # Register market visibility action (placeholder for now)
        @self.registry.action(
            "Ensure a betting market is expanded and visible",
            param_model=MarketAction,
            domains=["betway.co.za", "www.betway.co.za"],
        )
        async def ensure_market_is_visible(
            params: MarketAction, browser_session: BrowserSession
        ) -> ActionResult:
            """
            Ensures that a specific betting market is expanded and visible.
            """
            # TODO: Implement based on our research
            return ActionResult(
                extracted_content=f"Market visibility action for '{params.market_name}' - TO BE IMPLEMENTED"
            )
