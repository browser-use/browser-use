import asyncio
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent, Browser, BrowserConfig, Controller, ActionResult
from browser_use.browser.context import BrowserContext

# Load environment variables (.env file should contain GMAIL_USER and GMAIL_PASSWORD)
load_dotenv()

# Initialize controller for custom actions
controller = Controller()

@controller.action('Analyze email content')
async def analyze_email_content(browser: BrowserContext, email_text: str, email_sender: str, email_subject: str):
    """
    Analyze email content to determine if it's promotional.
    Returns an ActionResult with is_promotional boolean.
    """
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
    is_promotional = (
        subject_matches >= 1 or 
        sender_matches >= 1 or 
        content_matches >= 2
    )
    
    reason = ""
    if is_promotional:
        reason = "Classified as promotional because of "
        if subject_matches >= 1:
            reason += f"promotional terms in subject ({subject_matches} matches), "
        if sender_matches >= 1:
            reason += f"promotional sender patterns ({sender_matches} matches), "
        if content_matches >= 2:
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

async def main():
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
    
    print("Starting Gmail email segregation...")
    await agent.run()
    
    # Close the browser when done
    await browser.close()
    print("Email segregation completed!")

if __name__ == "__main__":
    asyncio.run(main())
