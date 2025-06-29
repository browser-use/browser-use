# Betway Automation Research & Strategy Guide

This document summarizes the key principles and strategies for building a well-architected automation system for a dynamic website like Betway using the `browser-use` framework.

## 1. Core `browser-use` Philosophy: Abstracting Complexity

The fundamental goal is not to have the LLM manually control every low-level detail of the browser. Instead, the strategy is to create a high-level, specialized "API" for the website through custom actions.

-   **The Agent's Role:** To be the "brain" that decides *what* to do next based on a high-level goal (e.g., "Place a bet on Chelsea").
-   **The Controller's Role:** To be the "hands" that know *how* to perform specific, high-level actions on the website (e.g., a `place_bet` function).
-   **Your Role as Architect:** To build the bridge between the Agent and the website by creating a custom `Controller` with robust, reliable actions. The agent should be shielded from the messy, dynamic complexity of the UI.

---

## 2. The Analysis Phase: Understand Before You Build

Before writing any code, a deep analysis of the target website is critical.

### High-Level Analysis
-   **Map the Site:** Understand the main sections (Sports, Live, Casino), URL structures, and user journeys (Browse -> Select -> Bet Slip -> Confirm).
-   **Analyze Network Traffic:** Use Chrome DevTools' **Network** tab to see how data is loaded. Look for API calls (`/api/...`) or WebSocket connections that provide match data and live odds. Interacting with the API directly can sometimes be more reliable than scraping the DOM.
-   **Identify State:** Use the **Application** tab in DevTools to see how the site uses `localStorage` and `sessionStorage` to manage state like the bet slip or user information.

### Deep Element Analysis
The core of the research is dissecting individual HTML elements to understand the site's structure and logic. The key is to identify stable patterns.

**The Selector Hierarchy of Reliability:**

When building custom actions, target elements in this order of preference:

1.  **Static ID:** The best-case scenario. Unique and unchanging (e.g., `id="loadMoreButton"`).
2.  **Semantic `data-` Attributes:** Excellent. Designed for machines and stable across redesigns (e.g., `data-markettitle="..."`, `data-translate-key="..."`).
3.  **Visible Text:** Good, but can be language-dependent. Use in combination with other selectors for context.
4.  **Functional CSS Class:** Look for classes that describe function, not appearance (e.g., `.btn-bettingmatch`, `.isSelected`).
5.  **`onclick` Content:** Not for selecting, but for understanding the site's internal JavaScript functions (e.g., `SendToBetslip(...)`).
6.  **Avoid at all costs:** Dynamic IDs (long, random GUIDs) and purely stylistic or positional classes.

---

## 3. Key Learnings from Betway Element Examples

We analyzed four types of elements, each teaching a crucial lesson for building your system.

### Lesson 1: The Basic Button (`All Markets`)
-   **Teaches:** How to differentiate between stable identifiers (`id="AllMarketsButton"`, `data-translate-key="AllMarkets"`) and unreliable ones (style classes).
-   **Takeaway:** Your actions should be built around the most stable identifiers available.

### Lesson 2: The Bet Button (`Both Teams To Score - No`)
-   **Teaches:** How to decode the site's internal data schema from its JavaScript calls (e.g., the `SendToBetslip(...)` function revealed the parameters: `outcome`, `odds`, `market`, `match_name`).
-   **Takeaway:** Use the site's own logic to define the Pydantic models for your custom actions. This ensures your agent provides the correct information.

### Lesson 3: The State-Changing Button (`Load More...`)
-   **Teaches:** The danger of asynchronous operations. Clicking "Load More" doesn't instantly update the page.
-   **Takeaway:** Custom actions that trigger content loading **must handle waiting**. The action should only return *after* the new content has loaded. The best way is to wait for the specific network response that fetches the data.

```python
# Inside a custom action
# 1. Get pre-click state (e.g., number of items)
# 2. Click the button
# 3. Wait for the post-condition (e.g., network response or DOM change)
await page.expect_response("**/api/getMoreMatches/**")
# 4. Return control to the agent
```

### Lesson 4: The Nested/Accordion Element (Market Groups)
-   **Teaches:** Complex UI interactions should be broken down into smaller, single-responsibility actions.
-   **Takeaway:** Instead of one giant, complex action, create a "toolset" for the agent.
    -   `ensure_market_is_visible(market_name)`: An action that finds a market and expands it if it's collapsed. It handles waiting for the animation to finish.
    -   `place_bet(market_name, outcome)`: A simpler action that can now assume the market is already visible.

This allows the agent to reason more effectively: "First, I will make the market visible. Second, I will place the bet."

---

## 4. The Chrome DevTools Workflow

-   **The Golden Rule:** Playwright-specific selectors like `:has-text()` **do not work** in the Chrome DevTools console.
-   **Correct Workflow:**
    1.  **Find Elements in Console:** Use standard selectors and JavaScript to test your logic.
        -   `document.querySelector("[data-markettitle='...']")` (Standard CSS)
        -   Use JavaScript to filter by text: `Array.from(document.querySelectorAll('div')).find(el => el.textContent.includes('My Text'))`
        -   Use XPath for powerful text matching: `document.evaluate("//div[contains(text(), 'My Text')]", ...)`
    2.  **Verify Stability:** Test your chosen selector multiple times. Refresh the page and see if it still works.
    3.  **Translate to Python:** Once you have a reliable method for finding an element in the console, translate that logic into the appropriate Playwright syntax in your Python custom action.

By following this research-driven approach, you can build a `BettingController` with a suite of high-level, robust, and reliable actions. This will empower your `browser-use` agent to navigate and operate effectively on a complex and dynamic site like Betway.

## 5. Documented Workflows (moved)

The detailed workflow specifications (login_user, ensure_market_is_visible, get_account_balance, etc.) have been moved to `docs/actions_blueprint.md` for easier maintenance and to keep this research document focused on methodology and findings.

## 6. Validating the Strategy: Lessons from a Live Test

The successful execution of the `login_user` custom action is the most critical piece of research. It validates our entire approach and provides a blueprint for all future development.

### Lesson 1: The "Sense, Decide, Act" Model is Confirmed
Our strategy is based on the idea that the agent should operate in a three-step loop. The live test proved this works perfectly:

1.  **Sense (Perception):** The agent used its "senses"—the screenshot (`use_vision=True`) and the DOM element list—to correctly identify that it was on the Betway homepage and that a login form was available.
2.  **Decide (Reasoning):** Faced with the goal of logging in, the agent reviewed its available tools. It correctly reasoned that our custom `login_user` action was a more direct and reliable tool than trying to guess which elements to click and type into.
3.  **Act (Execution):** The agent executed our high-level, pre-programmed action, which succeeded on the first attempt because we had already done the research to make it robust.

### Lesson 2: Vision and Custom Actions are a Powerful Synergy
These two features do not conflict; they work together to create a smarter and more reliable agent.

-   **Vision answers "What should I do?"**: By looking at the screenshot, the agent gets the same context a human would. This helps it make a better high-level decision about what its next goal should be.
-   **Custom Actions answer "How do I do it?"**: Once the agent decides on a goal (e.g., "log in"), our custom action provides a rock-solid, pre-programmed method to achieve it, shielding the agent from the complexity of the underlying UI.

### Lesson 3: Explicit Prompting Increases Reliability
For foundational tasks, being direct with the agent is highly effective. The test run succeeded when we explicitly told the agent to use our custom tool.

-   **Initial Prompt (Less Reliable):** `"Go to Betway.co.za and log in..."`
-   **Successful Prompt (More Reliable):** `"Go to www.betway.co.za and use the login_user action to log in with username '...' and password '...'"`

For building complex workflows, you can chain these explicit commands together to create a highly predictable and robust sequence of operations.

### Lesson 4: The Debugging Cycle is Essential
The process we followed is a repeatable template for development:
1.  **Build** a custom action based on research.
2.  **Test** it with a live run.
3.  **Analyze** the logs to see what the agent did and why.
4.  **Identify** bugs (like `browser_session.page` vs. `get_current_page()`).
5.  **Fix** the bug and re-test.

This iterative process is the core development loop for building a reliable automation system. The successful login confirms that this process works and should be followed for all subsequent actions.

---

### Workflow: `get_account_balance`

**1. Goal / User Story:**
As the agent, I want to read the current cash balance from the user's account, ensuring the balance is visible before reading it.

**2. Required Parameters (This will become your Pydantic Model):**
*   None. This is a read-only action.

**3. Pre-conditions (What must be true BEFORE this action runs?):**
*   The agent **must be logged in**. The balance element will not be accurate or possibly not even present otherwise.

**4. Execution Steps & Element Analysis:**

This action involves a conditional step: check if the balance is hidden first, and if so, click the button to reveal it.

### Step A: Locate the Balance Amount Element
*   **Selector Strategy:** The most reliable selector is the specific class for the balance amount.
*   **Primary Selector:** `.cashBalanceAmount`
*   **Element Analysis:**

| Rank | Selector Type | Selector Value | Reliability | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **CSS Class** | `.cashBalanceAmount` | **Excellent** | A semantic, functional class name. Primary choice. |
| **2** | **CSS Class Combo** | `.balance-label.balance-label-amount` | **Very Good** | More specific, but also more verbose. Good fallback. |

*   **Example HTML Snippet:**
    ```html
    <label class="label balance-label balance-label-amount cashBalanceAmount">R0.85</label>
    ```

### Step B: Check if Balance is Hidden (Conditional Step)
*   **Logic:** Before reading the value, the agent must check if the balance is currently hidden. The best way is to check if the `#show-balance-btn` is visible.
*   **Selector for "Show Balance" button:** `#show-balance-btn`
*   **Element Analysis (Show/Hide Buttons):**

| Rank | Selector Type | Selector Value | Reliability | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **ID** | `#show-balance-btn` | **Excellent** | The "show" button, visible when balance is hidden. |
| **2** | **ID** | `#hide-balance-btn` | **Excellent** | The "hide" button, visible when balance is shown. |

*   **Execution Logic:**
    1.  Check if the element `#show-balance-btn` is visible on the page.
    2.  If it is, click on `#show-balance-btn`.
    3.  Wait for the visibility to change (e.g., wait for `.cashBalanceAmount` to become visible).

### Step C: Extract and Clean the Balance Value
*   **Logic:** Once the `.cashBalanceAmount` element is guaranteed to be visible, get its text content.
*   **Example Value:** `"R0.85"`
*   **Cleaning:** The action should parse this string to return a clean number (e.g., `0.85`). This might involve removing the currency symbol ("R") and converting the string to a float.

**5. Success Condition (How do we know it worked?):**
*   The action successfully returns a floating-point number representing the user's balance.

**6. Potential Errors & Edge Cases:**
*   **Not Logged In:** The balance element might not exist. The action should handle this gracefully and return an error.
*   **Extraction Fails:** The text format changes (e.g., from "R0.85" to "R 0.85"), causing the parsing to fail. The cleaning logic should be robust.
*   **Element Not Found:** A UI redesign removes or renames the `.cashBalanceAmount` class.

**7. Dependent Actions (What other actions does this rely on?):**
*   `login_user`: This action is meaningless unless the user is logged in.

**8. Actions That Depend on This:**
*   A future `check_if_sufficient_funds` action before placing a bet.
*   Any reporting or logging action that needs to record the user's balance.

**9. Implementation Notes:**
*   The action must be an `async` function.
*   The logic should be wrapped in a `try...except` block to handle cases where elements aren't found.
*   The return value should be clearly defined, either the balance as a float or an `ActionResult` with an error message.

**10. Example Implementation Logic:**
```python
# Pseudo-code for the custom action
async def get_account_balance(browser_session: BrowserSession) -> ActionResult:
    # 1. Check if the "show balance" button is visible
    show_button = await browser_session.get_current_page().query_selector("#show-balance-btn")
    if show_button and await show_button.is_visible():
        await show_button.click()
        # Wait a moment for the UI to update
        await browser_session.get_current_page().wait_for_timeout(500)

    # 2. Find the balance element
    balance_element = await browser_session.get_current_page().query_selector(".cashBalanceAmount")
    if not balance_element:
        return ActionResult(error="Could not find balance element. Are you logged in?")

    # 3. Get and clean the text
    raw_balance_text = await balance_element.text_content()
    # Example: "R0.85" -> "0.85"
    cleaned_text = ''.join(filter(lambda char: char.isdigit() or char == '.', raw_balance_text))
    
    try:
        balance_value = float(cleaned_text)
        return ActionResult(extracted_content=f"User balance is {balance_value}")
    except ValueError:
        return ActionResult(error=f"Could not parse balance from text: '{raw_balance_text}'")
``` 

## 7. League Filter Component Analysis

The league filter is a complex, multi-level dropdown that allows users to narrow matches by specific competitions. This is critical for betting automation as it directly affects which matches appear in the main feed.

### Structure & Hierarchy
```
League Filter Box (.league-filter-box)
├── Toggle Header (h2 with onclick="filterOptions.toggleFilter")
├── Filter Values Container (#leagueGroup)
    ├── Mobile Header (.mobile-details)
    ├── Country/Region List (#league-ul-container .scroll)
    │   ├── Country Items (.dropdown-submenu)
    │   │   ├── Country Link (.leagueLink with onclick="eventDisplay.closeSubmenu")
    │   │   └── League List (.list-group.dropdown-menu)
    │   │       └── Individual Leagues (.league-item with onclick="filterOptions.addLeague")
    │   │
    └── Filter Footer (.filter-footer)
        ├── Show More/Less Buttons
        ├── Cancel/Reset Actions
        └── Apply Button
```

### Key Selectors & Interaction Patterns

**Main toggle:**
- Selector: `.league-filter-box h2` or element with `onclick*='toggleFilter'`
- Action: `filterOptions.toggleFilter(this)` - expands/collapses entire filter

**Country-level expansion:**
- Selector: `a.leagueLink[id^='leagueLink-submenu_']`
- Pattern: `#leagueLink-submenu_{CountryName}` (e.g., `#leagueLink-submenu_England`)
- Action: `eventDisplay.closeSubmenu('submenu_{Country}', this)`
- Visual state: `class="leagueLink active"` + green background when expanded

**Individual league selection:**
- Selector: `li.league-item[id='{league-uuid}']`
- Action: `onclick="filterOptions.addLeague('{league-uuid}')"`
- State indicator: `span.state-icon.glyphicon-unchecked` → `glyphicon-check` when selected
- Data: `data-checked="False"` → `"True"` when selected

**Filter controls:**
- Show More: `#showMoreLeagues` → `filterOptions.getMoreLeagues(false, true, '{sport-id}')`
- Apply: `#continueBtn` → `filterOptions.confirmLeagues()`
- Cancel: `#cancel-leagues` → `filterOptions.cancel('leagueGroup')`
- Reset: `#reset-leagues` → `filterOptions.resetLeagues()`

### Notable Implementation Details

1. **Duplicate Country Entries**: Some countries (like Kazakhstan) appear twice with different data-value UUIDs - this suggests different league groupings or data inconsistencies.

2. **State Management**: The filter maintains selected state through:
   - `data-checked` attributes on league items
   - Visual checkbox states (glyphicon-unchecked/check)
   - Selected count display: `#selectedLCount`

3. **AJAX Loading**: The "Show More" functionality suggests pagination - not all leagues load initially.

4. **UUID-based Identification**: Each league has a unique GUID for precise selection rather than name-based matching.

### Automation Implications

For reliable league filtering automation:
- Use UUID-based selection when possible (most precise)
- Check `data-checked` state before/after interactions
- Wait for AJAX completion on "Show More" operations
- Handle country-level expansion before league selection
- Verify selected count updates in header

## 8. Betslip Interface Analysis

The betslip is where users review, modify, and finalize their betting selections. It supports both single bets and multi-bets (accumulators) and provides detailed stake/return calculations.

### Overall Structure
```
Betslip Body (#betslipBodyDiv)
├── Bet Type Toggle (Single Bets vs Multi Bets)
│   ├── Single Bets Button (#sb_id) with count
│   └── Multi Bets Button (#mb_id) with count - currently active
├── Settings Icon (onclick="getUserBetslipSettings()")
├── Booking Code Search Section
├── Control Icons (grid view, select all, remove all)
└── Bet List (#betslip-list)
    └── Individual Bet Items (.SelectedOutcomeForBetslip)
```

### Individual Bet Item Structure
Each bet in the betslip has a unique UUID and contains:

**Core Information:**
- **Bet UUID**: Used throughout for identification (e.g., `cb854751-d350-f011-92d6-00155da60c0c`)
- **Team/Outcome**: "Orbit College FC", "Mamelodi Sundowns"
- **Market Type**: "1x2" (win/draw/lose)
- **Match Details**: "Orbit College FC v Cape Town City FC"
- **Odds**: `data-pd="3.35"` (current odds)
- **Live Indicator**: Green dot + "Live" for in-play matches

**Interactive Elements:**
- **Remove Button**: `onclick="RemoveBet('{uuid}')"`
- **Multi-bet Checkbox**: `#SelectedCheckBoxForBetslip-{uuid}` (for accumulator inclusion)
- **Stake Input**: `#wagerAmount{uuid}` - individual bet stake
- **Potential Return**: Calculated display `#potentialReturn{uuid}`

### Key Selectors & Patterns

**Bet type toggles:**
- Single Bets: `#sb_id` → `ToggleBetslip(this)`
- Multi Bets: `#mb_id` → `ToggleBetslip(this)` (currently active: `class="btn btn-primary active"`)

**Individual bet management:**
- Bet container: `#SelectedOutcomeForBetslip-{uuid}`
- Remove bet: `onclick="RemoveBet('{uuid}')"`
- Stake input: `input#wagerAmount{uuid}` with `onchange="UpdatePotentialSingleReturn('{uuid}')"`
- Multi-bet checkbox: `input#SelectedCheckBoxForBetslip-{uuid}` with `onclick="toggleMultiSelectorOutcome(this,'{uuid}')"`

**Bulk operations:**
- Select all: `#chkSelectAll` → `tickAllOutcomes(this)`
- Remove all: `onclick="ClearBetslip()"`
- Settings: `onclick="getUserBetslipSettings()"`

**Booking code functionality:**
- Search input: `#mtSearch` with `onkeyup="enabledLoadBookingCodeBtn(this)"`
- Load button: `#load-booking-code-btn` → `GetBookingCodeBetslip()`

### State Management Details

**Odds & Pricing:**
- Current odds: `data-pd` attribute (e.g., `data-pd="3.80"`)
- Boosted odds: `data-lpd` (line-through styling when boosted)
- Stakes: Individual inputs with R currency prefix
- Returns: Auto-calculated on stake changes

**Multi-bet Logic:**
- Each bet has checkbox for multi-bet inclusion
- Toggle between single/multi changes visibility of stake inputs
- Multi-bet mode: combined odds calculation
- Single-bet mode: individual stake/return per bet

**Live Match Indicators:**
- Green dot + "Live" text for in-play events
- Date/time display for scheduled matches
- Both bets shown are currently live

### Automation Implications

**For stake management:**
- Use UUID-based selectors for reliability: `#wagerAmount{uuid}`
- Stakes default to R10.00, can be modified
- Returns auto-update via `UpdatePotentialSingleReturn(uuid)`

**For bet validation:**
- Check bet count in headers: `#sigleBetsCount`, `#multipleBetsCount`
- Verify bet presence: existence of `#SelectedOutcomeForBetslip-{uuid}`
- Monitor odds changes via `data-pd` attributes

**For bet removal:**
- Individual: `RemoveBet(uuid)` function
- Bulk: `ClearBetslip()` function
- Verify removal by checking container disappearance

## 9. Booking Code Generation Modal

When users generate a shareable booking code for their betslip, Betway displays a modal with sharing options and the generated code.

### Modal Structure
```
Modal Container (#modal-container-bet-confirmation)
├── Header ("Prediction")
│   └── Close Button (data-dismiss="modal")
├── Success Message ("Booking Code has been successfully generated")
├── Booking Code Display
│   ├── Copy to Clipboard Button (onclick="global.copyToClipboard")
│   └── Code Display (e.g., "BW518F0B4")
└── Share Options
    ├── WhatsApp Share
    ├── Twitter Share  
    ├── Facebook Share
    ├── SMS Share
    └── Email Share
└── Continue Betting Button (#continueBettingBtn)
```

### Key Elements & Functionality

**Modal identification:**
- Container: `#modal-container-bet-confirmation`
- Display state: `style="display: block"` when visible
- Z-index: Very high (999999999) to overlay everything

**Booking code details:**
- Generated code: "BW518F0B4" (8-character alphanumeric)
- Copy button: `onclick="global.copyToClipboard(this,'BW518F0B4')"`
- Shareable URL format: `http://www.betway.co.za/bookabet/{code}`

**Share mechanisms:**
- **WhatsApp**: `https://api.whatsapp.com/send?text={url} : {message}`
- **Twitter**: `https://twitter.com/intent/tweet?url={url}&text={message}`
- **Facebook**: `https://www.facebook.com/sharer/sharer.php?u={url}&quote={message}`
- **SMS**: `sms:?body={message}` (mobile-specific handling)
- **Email**: `mailto:?subject={message}&body={url}`

**Modal controls:**
- Close: `data-dismiss="modal"` attribute or close button click
- Continue: `#continueBettingBtn` → `data-dismiss="modal"`

### JavaScript Functions & Variables

**Key variables exposed:**
```javascript
var enableBookABet = true;
var isBookABetResult = true;  
var bookingCode = "BW518F0B4";
```

**Functions called:**
- `SetBookingCode(bookingCode)` - stores the generated code
- `global.copyToClipboard(element, text)` - copies code to clipboard
- `ResetAndBackToBets()` - clears betslip if not keeping bets

### Automation Implications

**For booking code extraction:**
```python
# Wait for modal to appear
await page.wait_for_selector("#modal-container-bet-confirmation[style*='display: block']")

# Extract the booking code
booking_code_element = await page.query_selector(".book-code")
booking_code = await booking_code_element.text_content()
# Extract just the code part (e.g., "BW518F0B4")

# Or get from JavaScript variable
booking_code = await page.evaluate("window.bookingCode")
```

**For automation workflow:**
1. User creates bet selections
2. Clicks share/generate booking code  
3. Modal appears with generated code
4. Automation extracts code for storage/reuse
5. Clicks "Continue Betting" to dismiss modal

**Storage/reuse pattern:**
- Save booking codes for successful betting strategies
- Load codes later using the `#mtSearch` input + `GetBookingCodeBetslip()`
- Share codes between automated instances or manual users

This modal represents the output of the "Book-a-Bet" workflow - turning a configured betslip into a reusable, shareable code that can recreate the exact betting configuration later.
