import asyncio
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from browser_use import ActionResult, Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
#Make sure to set your google credentials in the .env file
# GOOGLE_EMAIL=your_email@gmail.com
# GOOGLE_PASSWORD=your_password
load_dotenv()
controller = Controller()

class Meeting(BaseModel):
    title: str
    time: str
    participants: List[str]
    link: Optional[str] = None

class Email(BaseModel):
    to: str
    subject: str
    body: str

@controller.action('Read credentials')
def read_credentials():
    return {
        "email": os.getenv("GOOGLE_EMAIL"),
        "password": os.getenv("GOOGLE_PASSWORD")
    }
#Make a email.txt file in the same directory as the script and add the email you want to send the reminder to
@controller.action('Read recipient email')
def read_recipient():
    try:
        with open('email.txt', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ActionResult(error="email.txt not found")

async def perform_google_login(browser: BrowserContext):
    credentials = read_credentials()
    if not credentials["email"] or not credentials["password"]:
        return ActionResult(error="Missing Google credentials in .env file")
    
    await browser.goto('https://accounts.google.com')
    await asyncio.sleep(2)
    
    # Enter email
    email_field = await browser.get_dom_element_by_selector('input[type="email"]')
    if not email_field:
        return ActionResult(error="Could not find email field")
    
    await email_field.type_text(credentials["email"])
    await browser.click_element('#identifierNext')
    await asyncio.sleep(2)
    
    # Enter password
    password_field = await browser.get_dom_element_by_selector('input[type="password"]')
    if not password_field:
        return ActionResult(error="Could not find password field")
    
    await password_field.type_text(credentials["password"])
    await browser.click_element('#passwordNext')
    await asyncio.sleep(3)

#Gets the  upcoming meetings from the calendar
async def get_calendar_meetings(browser: BrowserContext) -> List[Meeting]:
    await browser.goto('https://calendar.google.com')
    
    # Check if we need to login
    if "accounts.google.com" in await browser.get_current_url():
        login_result = await perform_google_login(browser)
        if login_result and login_result.error:
            return []
    
    await asyncio.sleep(5)  # Wait for calendar load
    
    meetings = []
    events = await browser.get_dom_elements_by_selector('div[role="gridcell"][data-date]')
    
    for event in events[:5]:
        try:
            await event.click()
            await asyncio.sleep(1)
            
            title_el = await browser.get_dom_element_by_selector('[data-testid="event-title"]')
            time_el = await browser.get_dom_element_by_selector('[data-testid="event-time"]')
            
            meeting = Meeting(
                title=await title_el.get_text(),
                time=await time_el.get_text(),
                participants=[]
            )
            meetings.append(meeting)
            
            await browser.press_key('Escape')
        except Exception as e:
            logging.error(f"Error processing event: {str(e)}")
    
    return meetings

#Sends the reminder email
@controller.action('Send calendar reminder')
async def send_reminder(browser: BrowserContext):
    recipient = read_recipient()
    if isinstance(recipient, ActionResult):
        return recipient
    
    meetings = await get_calendar_meetings(browser)
    
    for meeting in meetings[:3]:
        email = Email(
            to=recipient,
            subject=f"Reminder: {meeting.title}",
            body=f"""Hi there,
            
Meeting reminder for {meeting.title}
Time: {meeting.time}

Don't forget to prepare!
"""
        )
        
        # Compose and send email
        await browser.goto('https://mail.google.com/mail/u/0/#compose')
        await asyncio.sleep(3)
        
        await browser.type_text('[aria-label="To"]', email.to)
        await browser.type_text('[aria-label="Subject"]', email.subject)
        await browser.type_text('[aria-label="Message Body"]', email.body)
        
        await asyncio.sleep(1)
        send_button = await browser.get_dom_element_by_selector('[aria-label="Send ‪(Ctrl-Enter)‬"]')
        await send_button.click()
        await asyncio.sleep(2)

#Creates the browser
browser = Browser(
    config=BrowserConfig(
        headless=False
    )
)

async def main():
    model = ChatOpenAI(
        model='gpt-4o',
        temperature=0
    )

    agent = Agent(
        task="Google Services Automation:\n"
             "1. Login using .env credentials\n"
             "2. Check calendar meetings\n"
             "3. Send reminders via Gmail\n"
             "4. Handle authentication flows",
        llm=model,
        controller=controller,
        browser=browser,
        use_vision=True
    )

    await agent.run()

if __name__ == '__main__':
    asyncio.run(main())