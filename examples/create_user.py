import asyncio
from dotenv import load_dotenv

load_dotenv()
from browser_use import Agent, ChatOpenAI, BrowserProfile


async def main():
    # Configure browser for better accuracy
    browser_profile = BrowserProfile(
        headless=False,  # Run in headed mode to see what's happening
        highlight_elements=True,
    )

    task = """
    Please complete the following user management task:

    1. INITIAL LOGIN:
       - Navigate to https://localhost
       - Log in using credentials: username="admin", password="pass"
       - Wait for the dashboard/main interface to load completely

    2. Look for and navigate to the user management section (this may be labeled as "Users", "User Management", 
       "People", "Members", or similar). This section can be located anywhere including submenus.

    3. CREATE NEW USER WITH PRECISION:
       - Once in user management area, look for action buttons:
         * "Add User", "New User", "Create User", "+" button
         * These are often prominently placed (top-right, above user lists)

       **FORM FILLING STRATEGY**:
       - Click each form field individually and wait for focus
       - Clear any existing content before typing new values
       - Use realistic data:
         * First Name: pick an ABSOLUTELY random realistic first name! Never pick the same first name after running again, make sure it's fully random.
         * Last Name: pick an ABSOLUTELY random realistic last name! Never pick the same last name after running again, make sure it's fully random.
         * Username: any variation based on letters from first and last name in recognizable way. Also make sure it's ABSOLUTELY random combination.
         * Email: use Username from above and add @company.com 
         * Password: Use a standard format like "TempPass123!"

       **FIELD VALIDATION**:
       - After filling each field, verify the content was entered correctly
       - If a field didn't accept input, click it again and retry

    4. HANDLE AUTHENTICATION AND COMPLETION:
       ** ABSOLUTELY MANDATORY!!! **
       ALWAYS CHECK IF SOMETHING IS CHANGED ON THE PAGE. IF IT DOES (FOR EXAMPLE, YOU NO LONGER DETECT Save Users BUTTON OR SIMILAR
       ASSUME THAT User Management FORM WAS CLOSED AND PROCEED TO STEP 5 (FINAL VERIFICATION)       
       - For password confirmations, use: username="admin", password="pass". If only password confirmation is required, use password, not username.
       - Look for save/submit buttons (often labeled "Save", "Create", "Add User", "Submit")
       - **SAVE BUTTON TARGETING**: These buttons are usually at the bottom of forms or in modal footers
       - Wait for success confirmations or error messages
       - Verify user appears in user list if available
        
    5. FINAL VALIDATION
       - Wait for success confirmations or error messages
       - Verify user appears in user list if available
       - Confirm successful user creation by looking for:
         * Success message/notification
         * New user in user list (IF YOU DON'T SEE USER LIST - LOCATE ONE)
         * Redirect to user management page showing the created user

    **CRITICAL CLICKING RULES**:
    - NEVER click rapidly or without visual confirmation
    - ALWAYS wait for hover effects or visual feedback before clicking
    - If you see your cursor is not on the intended target, reposition before clicking
    - Take time to distinguish between similar menu items
    - If a click doesn't produce the expected result, acknowledge the error and correct course

    **DEBUGGING APPROACH**:
    - Narrate your actions: "I see three menu options: System, Users, Reports. I will click Users because it's most likely to contain user management."
    - If navigation fails: "The click on Users didn't work as expected. I can see I'm still on the same page. Let me try clicking more precisely on the Users menu item."
    """

    agent = Agent(
        task=task,
        enable_bbox_filtering=False,
        browser_profile=browser_profile,
        llm=ChatOpenAI(model="gpt-4o"),
    )
    result = await agent.run()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())