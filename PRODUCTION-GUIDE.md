# 🚀 Production Guide - Making the Agent Actually Work

## Why Your Agent Isn't Doing Anything

Common issues and fixes:

### ❌ Problem 1: Vision is Disabled
**Symptom:** Agent can't find login buttons, can't see forms, does nothing

**Fix:** Add `use_vision=True` to your Agent
```python
agent = Agent(
    task="...",
    llm=llm,
    use_vision=True,  # <-- ADD THIS!
)
```

**Why:** Without vision, the agent is basically blind. It can only see HTML text, not buttons, images, or visual elements.

---

### ❌ Problem 2: Not Enough Steps
**Symptom:** Agent starts working but stops before finishing

**Fix:** Increase `max_steps`
```python
await agent.run(max_steps=30)  # Default is only 10!
```

**Why:** Logging in, navigating, and doing tasks takes many steps. 10 is rarely enough.

---

### ❌ Problem 3: Using Haiku for Complex Tasks
**Symptom:** Works for simple tasks (go to website), fails at complex ones (login, multi-step)

**Fix:** Use Sonnet for complex tasks
```python
# For complex tasks (logins, multi-step workflows):
llm = ChatAnthropic(model_name='claude-3-5-sonnet-20240620')

# For simple tasks (search, navigate, extract text):
llm = ChatAnthropic(model_name='claude-haiku-4-5-20251001')
```

**Why:** Haiku is cheap but less capable. Sonnet is better at reasoning through complex multi-step tasks.

**Cost comparison:**
- Haiku: $0.15 per 100 tasks
- Sonnet: $0.50 per 100 tasks
- Still very cheap! Use Sonnet for tasks that matter.

---

### ❌ Problem 4: Vague Task Instructions
**Symptom:** Agent does random things or nothing at all

**Bad task:**
```python
task = "login to facebook"
```

**Good task:**
```python
task = """
Go to facebook.com

If not logged in:
1. Click the 'Log In' button
2. Enter email: myemail@example.com
3. Enter password: mypassword123
4. Click 'Log In'
5. Wait for page to load

Once logged in:
- Go to my profile
- Tell me how many friends I have
"""
```

**Why:** The more specific you are, the better it works. Break tasks into numbered steps.

---

## 📋 How to Write Good Task Instructions

### ✅ Template for Login Tasks

```python
task = """
STEP 1: Navigation
Go to [website URL]

STEP 2: Login (if needed)
If I see a login page:
- Click the login/sign-in button
- Enter username: [your username]
- Enter password: [your password]
- Click submit/login button
- Wait for login to complete

STEP 3: Main Task
[What you want it to do after login]

STEP 4: Confirmation
Tell me when you're done and what the result was
"""
```

### ✅ Template for Form Filling

```python
task = """
Go to [form URL]

Fill out the form with these details:
- Field 1: value1
- Field 2: value2
- Field 3: value3

Then:
- Click the Submit button
- Wait for confirmation
- Tell me what the confirmation message says
"""
```

### ✅ Template for Data Collection

```python
task = """
Go to [website]

Search for: [search term]

Collect this information from the first 5 results:
- Name
- Price
- Rating

Save the results to a file called results.txt
"""
```

---

## 🔐 Handling Logins Securely

### Option 1: Store Credentials in Environment Variables

**In your `.env` file:**
```
ANTHROPIC_API_KEY=sk-ant-...
FACEBOOK_EMAIL=myemail@example.com
FACEBOOK_PASSWORD=mypassword123
```

**In your script:**
```python
import os

email = os.getenv('FACEBOOK_EMAIL')
password = os.getenv('FACEBOOK_PASSWORD')

task = f"""
Go to facebook.com
Login with:
- Email: {email}
- Password: {password}
"""
```

### Option 2: Use Browser Profiles (Stay Logged In)

```python
from browser_use import Agent, BrowserProfile, BrowserSession

# Create a persistent browser profile
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=False,  # See what's happening
        disable_security=False,
        extra_chromium_args=[],
        user_data_dir='./browser_profile',  # Saves cookies/sessions
    )
)

await browser_session.start()

agent = Agent(
    task="Go to facebook.com and check my messages",
    llm=llm,
    browser_session=browser_session,
)

await agent.run()
```

**Benefit:** After logging in once, you stay logged in. Faster and more reliable!

---

## 🐛 Debugging When Things Go Wrong

### 1. Save Conversation History

```python
agent = Agent(
    task="...",
    llm=llm,
    save_conversation_path='./debug.json',  # Saves everything
)
```

Then open `debug.json` to see exactly what the agent tried to do.

### 2. Disable Headless Mode (Watch It Work)

```python
from browser_use import BrowserProfile, BrowserSession

browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        headless=False,  # See the browser!
    )
)

await browser_session.start()

agent = Agent(
    task="...",
    llm=llm,
    browser_session=browser_session,
)
```

### 3. Add Logging

```python
import logging

logging.basicConfig(level=logging.INFO)

# Now you'll see detailed logs of what's happening
```

### 4. Test Simple Tasks First

Don't start with complex logins. Test incrementally:

```python
# Test 1: Can it navigate?
task = "Go to google.com"

# Test 2: Can it interact?
task = "Go to google.com and type 'hello' in the search box"

# Test 3: Can it complete an action?
task = "Go to google.com, search for 'puppies', and click the first result"

# Test 4: Now try login
task = "Go to facebook.com and login..."
```

---

## 🎯 Real-World Examples

### Example 1: Facebook Posting

```python
task = """
Go to facebook.com

If not logged in, login with:
- Email: {os.getenv('FB_EMAIL')}
- Password: {os.getenv('FB_PASSWORD')}

Once logged in:
1. Click on "What's on your mind?"
2. Type this post: "Happy Friday everyone! 🎉"
3. Click the Post button
4. Wait for the post to appear
5. Tell me when it's done
"""

agent = Agent(
    task=task,
    llm=ChatAnthropic(model_name='claude-3-5-sonnet-20240620'),
    use_vision=True,
    max_actions_per_step=10,
)

await agent.run(max_steps=30)
```

### Example 2: Lead Generation Form

```python
task = """
Go to https://example.com/contact

Fill out the contact form:
- First Name: John
- Last Name: Smith
- Email: john@company.com
- Phone: 555-1234
- Company: ABC Corp
- Message: Interested in your roofing services for a commercial project

Click Submit

Wait for confirmation and tell me if it was successful
"""

agent = Agent(
    task=task,
    llm=ChatAnthropic(model_name='claude-haiku-4-5-20251001'),  # Simple task, use Haiku
    use_vision=True,
)

await agent.run(max_steps=20)
```

### Example 3: Data Scraping

```python
task = """
Go to Yelp.com

Search for: roofing contractors in Charlotte NC

For the top 5 results, collect:
- Business name
- Rating (stars)
- Number of reviews
- Phone number

Save all this to a file called yelp_results.txt with each business on a new line
"""

agent = Agent(
    task=task,
    llm=ChatAnthropic(model_name='claude-3-5-sonnet-20240620'),  # Complex extraction
    use_vision=True,
)

await agent.run(max_steps=40)
```

---

## 💰 Cost Optimization for Production

### Strategy 1: Use the Right Model for the Job

```python
# Simple navigation/clicking: Haiku ($1/$5 per M tokens)
# Complex reasoning/logins: Sonnet ($3/$15 per M tokens)

def get_llm_for_task(task_type):
    if task_type in ['navigate', 'click', 'simple_form']:
        return ChatAnthropic(model_name='claude-haiku-4-5-20251001')
    elif task_type in ['login', 'complex_workflow', 'data_extraction']:
        return ChatAnthropic(model_name='claude-3-5-sonnet-20240620')
    else:
        return ChatAnthropic(model_name='claude-haiku-4-5-20251001')
```

### Strategy 2: Use Browser Profiles (Avoid Re-Login)

```python
# Login once, reuse for all tasks
browser_session = BrowserSession(
    browser_profile=BrowserProfile(
        user_data_dir='./my_browser_profile',
    )
)
```

### Strategy 3: Batch Multiple Tasks

```python
task = """
Task 1: Go to facebook.com and post "Hello"
Task 2: Go to twitter.com and post "Hello"
Task 3: Go to linkedin.com and post "Hello"
"""

# One agent session does all 3 - more efficient than 3 separate runs
```

---

## 🚨 Common Errors and Fixes

### "Agent did nothing"
- ✅ Add `use_vision=True`
- ✅ Increase `max_steps` to 30+
- ✅ Make task instructions more specific

### "Agent keeps failing at login"
- ✅ Use Sonnet instead of Haiku
- ✅ Increase `timeout` in ChatAnthropic
- ✅ Add explicit wait steps: "Wait 5 seconds for page to load"
- ✅ Use browser profiles to stay logged in

### "Agent clicks wrong things"
- ✅ Be more specific in instructions: "Click the blue 'Login' button in the top right"
- ✅ Use CSS selectors if needed (advanced)

### "Rate limit exceeded"
- ✅ Wait 60 seconds between tasks
- ✅ Check your API usage at console.anthropic.com
- ✅ Add delays: `await asyncio.sleep(2)` between agent runs

### "Browser crashes or hangs"
- ✅ Close and restart browser session every 10-20 tasks
- ✅ Add `timeout` to agent.run(): `await agent.run(max_steps=30, timeout=300)`

---

## 🎓 Next Steps

1. **Start with `example-production.py`** - Edit it for your use case
2. **Test incrementally** - Simple tasks first, then complex
3. **Watch it work** - Use `headless=False` while developing
4. **Save conversations** - Use `save_conversation_path` to debug
5. **Use the right model** - Sonnet for complex, Haiku for simple

---

## 📞 Still Stuck?

Post in Discord with:
- Your exact task string
- The error message or unexpected behavior
- Whether you're using `use_vision=True`
- Which model you're using

Discord: https://link.browser-use.com/discord

Someone will help!
