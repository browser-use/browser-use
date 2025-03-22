import logging

from playwright_recaptcha import recaptchav2

from browser_use.agent.service import Agent

logger = logging.getLogger("captcha_solver")

class ReCaptchaSolver:
    async def solve_captcha(self, context: Agent) -> None:
        try:
            page = await context.browser_context.get_current_page()

            recaptcha_frame_locator = page.frame_locator("iframe[title='reCAPTCHA']")
            recaptcha_iframes = await page.locator("iframe[title='reCAPTCHA']").count()

            if recaptcha_iframes:
                # Check is reCAPTCHA already solved
                checkbox_locator = recaptcha_frame_locator.locator("span[aria-checked='true']")
                if await checkbox_locator.count() > 0:
                    logger.info("reCAPTCHA already solved.")
                    return

                logger.info("reCAPTCHA found, solving using audio...")
                solver = recaptchav2.AsyncSolver(page)
                await solver.solve_recaptcha(wait=True, image_challenge=False)
            else:
                logger.info("reCAPTCHA not found.")
        except Exception as e:
            logger.error(f"Error during solving reCAPTCHA: {e}")
