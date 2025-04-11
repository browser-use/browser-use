# An email segregator that segregates your latest top 10 emails and moves the promotional ones to trash 


import asyncio
import os
import logging
import sys
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig, Controller, ActionResult
from browser_use.browser.context import BrowserContext
from playwright.async_api import TimeoutError, Error as PlaywrightError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables (.env file should contain GMAIL_USER and GMAIL_PASSWORD)
load_dotenv()

# Validate required environment variables
def validate_environment():
    """Validate that all required environment variables are set."""
    required_vars = {
        "GMAIL_USER": os.getenv("GMAIL_USER"),
        "GMAIL_PASSWORD": os.getenv("GMAIL_PASSWORD")
    }
    
    missing_vars = [var for var, value in required_vars.items() if not value]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these variables in your .env file or environment.")
        logger.error("Example .env file content:")
        logger.error("GMAIL_USER=your.email@gmail.com")
        logger.error("GMAIL_PASSWORD=your_app_password")
        return False
    
    logger.info("Environment variables validated successfully")
    return True

# Email classification configuration
# These thresholds determine when an email is considered promotional
SUBJECT_MATCH_THRESHOLD = 1  # Number of promotional terms in subject required
SENDER_MATCH_THRESHOLD = 1  # Number of promotional patterns in sender required
CONTENT_MATCH_THRESHOLD = 2  # Number of promotional terms in content required

# Initialize controller for custom actions
controller = Controller()

@controller.action('Analyze email content')
async def analyze_email_content(browser: BrowserContext, email_text: str, email_sender: str, email_subject: str):
    """
    Analyze email content to determine if it's promotional.
    Returns an ActionResult with is_promotional boolean.
    """
    try:
        # Common promotional terms and signals
        promo_terms = [
            "offer", "discount", "sale", "promotion", "deal", "limited time", 
            "exclusive", "save", "free", "coupon", "subscribe", "unsubscribe",
            "marketing", "newsletter", "% off", "click here", "shop now"
        ]
        
        # Common promotional senders
        promo_senders = [
            "no-reply", "noreply", "newsletter", "marketing", "info@", "offers",
            "promotions", "sales", "deals", "updates"
        ]
        
        # Check if email contains promotional terms
        email_text_lower = email_text.lower()
        email_subject_lower = email_subject.lower()
        email_sender_lower = email_sender.lower()
        
        # Count matches in content
        content_matches = sum(1 for term in promo_terms if term.lower() in email_text_lower)
        subject_matches = sum(1 for term in promo_terms if term.lower() in email_subject_lower)
        sender_matches = sum(1 for term in promo_senders if term.lower() in email_sender_lower)
        
        # Decide if promotional based on combined factors
        # An email is considered promotional if it meets any of these criteria:
        # 1. Contains promotional terms in the subject line
        # 2. Has a sender email that matches promotional patterns
        # 3. Contains multiple promotional terms in the content
        is_promotional = (
            subject_matches >= SUBJECT_MATCH_THRESHOLD or 
            sender_matches >= SENDER_MATCH_THRESHOLD or 
            content_matches >= CONTENT_MATCH_THRESHOLD
        )
        
        reason = ""
        if is_promotional:
            reason = "Classified as promotional because of "
            if subject_matches >= SUBJECT_MATCH_THRESHOLD:
                reason += f"promotional terms in subject ({subject_matches} matches), "
            if sender_matches >= SENDER_MATCH_THRESHOLD:
                reason += f"promotional sender patterns ({sender_matches} matches), "
            if content_matches >= CONTENT_MATCH_THRESHOLD:
                reason += f"promotional content ({content_matches} matches), "
            reason = reason.rstrip(", ")
        else:
            reason = "Not classified as promotional"
        
        return ActionResult(
            is_promotional=is_promotional,
            reason=reason,
            subject=email_subject,
            sender=email_sender
        )
    except Exception as e:
        logger.error(f"Error analyzing email content: {str(e)}")
        # Return a default result in case of error
        return ActionResult(
            is_promotional=False,
            reason=f"Error during analysis: {str(e)}",
            subject=email_subject,
            sender=email_sender
        )

async def main():
    # Validate environment variables before proceeding
    if not validate_environment():
        logger.error("Exiting due to missing environment variables")
        sys.exit(1)
        
    browser = None
    try:
        # Initialize browser
        browser = Browser(
            config=BrowserConfig(
                headless=False,
                chrome_instance_path="C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"  # Set to True for background operation
                # Specify your browser path if needed
                # chrome_instance_path='C:/Program Files/Google/Chrome/Application/chrome.exe',
            )
        )
        
        # Initialize AI model
        model = ChatOpenAI(model="gpt-4o")
        
        # Create agent with task instructions
        agent = Agent(
            task="Gmail Email Segregator Task:\n"
                 "1. Navigate to Gmail: https://mail.google.com/mail/u/0/?tab=rm&ogbl#inbox\n"
                 "2. Log in using credentials from environment variables\n"
                 "3. Examine the first 10 emails in the inbox\n"
                 "4. For each email:\n"
                 "   a. Open the email by clicking on the text of the email\n"
                 "   b. Analyze if it appears to be promotional\n"
                 "   c. If promotional, move it to trash\n"
                 "   d. If not promotional, leave it in the inbox\n"
                 "   e. Go back to the inbox for the next email\n"
                 "5. Provide a summary of how many emails were moved to trash\n\n"
                 "When analyzing if an email is promotional, consider:\n"
                 "- The sender's email domain\n"
                 "- Words in the subject line (offers, discounts, etc.)\n"
                 "- The content of the email (marketing language, promotional graphics)\n"
                 "- Presence of unsubscribe links\n",
            llm=model,
            controller=controller,
            browser=browser,
            use_vision=True
        )
        
        logger.info("Starting Gmail email segregation...")
        await agent.run()
        logger.info("Email segregation completed successfully!")
        
    except TimeoutError as e:
        logger.error(f"Timeout error during browser automation: {str(e)}")
        logger.info("The operation timed out. This could be due to slow internet or Gmail being unresponsive.")
    except PlaywrightError as e:
        logger.error(f"Playwright error during browser automation: {str(e)}")
        logger.info("There was an issue with the browser automation. Please check your browser configuration.")
    except Exception as e:
        logger.error(f"Unexpected error during email segregation: {str(e)}")
        logger.info("An unexpected error occurred. Please check the logs for details.")
    finally:
        # Ensure browser is closed even if an error occurs
        if browser:
            try:
                await browser.close()
                logger.info("Browser closed successfully")
            except Exception as e:
                logger.error(f"Error closing browser: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
