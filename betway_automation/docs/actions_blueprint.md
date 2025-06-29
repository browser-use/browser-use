# Betway Actions Blueprint

This document distills the research from `Betway_auto_research.md` into a concise, action-oriented specification.  Each section represents a **custom action** that will be registered on the `BetWayController`.  The goal is to keep all implementation-relevant details in one place so that engineers can translate them directly into code.

---

## 1. `login_user`
High-level goal: log the user into Betway with a mobile number / username and password.

| Field | Type | Description |
|-------|------|-------------|
| `username` | `str` | Mobile number or username. |
| `password` | `str` | Account password. |

**Pre-conditions**
1. Betway login form is visible (homepage header or dedicated `/login` route).
2. Agent is not already authenticated.

**Execution outline**
1. Locate `#MobileNumber` (fallback: `input[name='MobileNumber']`) and fill `username`.
2. Locate `#Password` (fallback: `input[name='Password']`) and fill `password`.
3. Click `#Login` (fallback: `button:has-text("Login")`).
4. Wait for navigation / DOM change indicating logged-in state (URL no longer contains `login`).

**Success criteria**
• Redirected away from the login page.
• Presence of user-account elements, balance label, or logout button.

**Common errors / edge cases**
• Invalid credentials → error banner.
• CAPTCHA challenge.
• Network timeout.

---

## 2. `ensure_market_is_visible`
High-level goal: expand an accordion-style market section so its betting options are visible.

| Field | Type | Description |
|-------|------|-------------|
| `market_name` | `str` | Exact market title (e.g., `"Both Teams To Score"`). |

**Pre-conditions**
1. Agent is on a match / sports page that contains the desired market.
2. Page has fully loaded.

**Execution outline**
1. Locate container `[data-markettitle="{market_name}"]`.
2. Inspect child `.panel-collapse` to see if it is already visible.
3. If collapsed, click the toggle element `[onclick*='toggleMultimarketAccordion']` inside the container.
4. Wait for `.panel-collapse` to become visible (`page.wait_for_element_state('visible')`).

**Success criteria**
• `.panel-collapse` for the market is visible and interactive.

**Common errors / edge cases**
• Market not found.
• Already expanded (return gracefully).
• Animation timeout.

---

## 3. `place_bet`
High-level goal: select a specific betting outcome within a visible market and add it to the bet-slip.

| Field | Type | Description |
|-------|------|-------------|
| `outcome_text` | `str` | Exact outcome label (e.g., "Over 2.5", "Chelsea", "No"). |
| `market_title` | `str` | Market name for context (e.g., "Overs/Unders (Total 2.5)", "1x2"). |
| `expected_odds` | `Optional[float]` | Expected odds for validation (e.g., 2.65). |
| `match_description` | `Optional[str]` | Human-readable match identifier for verification. |

### Pre-conditions
1. User is logged in
2. Target market is visible (call `ensure_market_is_visible` first)  
3. Match page or betting feed is loaded with outcome buttons present

### Betting Outcome Button Structure
All betting outcomes use the following HTML structure:
```html
<div class="btn btn-group btn-bettingmatch" 
     id="{unique-uuid}"
     data-markettitle="{market_name}"
     data-lip-sbv="{market_variation}"
     onclick="SendToBetslip('{outcome_id}', '{outcome_text}', '{odds}', '{sport}', '{market_title}', '{market_variation}', '{match_name}', '{match_datetime}', '{match_id}', '{is_live}', '{market_type_id}', '{allow_cashout}', {other_params}...)">
  
  <div class="outcome-title">
    <span data-translate-key="{outcome_text}">{outcome_text}</span>
  </div>
  
  <div class="outcome-pricedecimal" data-pd="{odds}">
    {display_odds}
  </div>
</div>
```

### Execution Outline
1. **Locate target outcome button**
   - Primary selector: `.btn-bettingmatch` containing outcome text
   - Filter by market: `[data-markettitle*="{market_title}"]` if provided
   - Verify outcome text in `.outcome-title span` content
   - Alternative: Use exact text match in outcome button

2. **Validate outcome before selection**
   - Extract current odds from `.outcome-pricedecimal[data-pd]` attribute
   - If `expected_odds` provided, verify odds match within tolerance (±0.05)
   - Check button is not disabled or grayed out
   - Verify match context if `match_description` provided

3. **Execute bet selection**
   - Click the `.btn-bettingmatch` button
   - This triggers `SendToBetslip()` JavaScript function automatically
   - Wait for visual confirmation (button highlight, betslip update)

4. **Verify bet added to betslip**
   - Check betslip sidebar for new entry
   - Verify outcome appears with correct odds and match details
   - Confirm betslip count increases

### Success Criteria
- Outcome button is successfully clicked
- `SendToBetslip()` function executes without errors
- Bet appears in betslip with correct details
- Button shows selected state (if applicable)

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Outcome not found | Incorrect text or market not visible | Verify market is expanded, check exact text |
| Odds mismatch | Market moved since validation | Report new odds, ask user to confirm |
| Button disabled | Market suspended or unavailable | Report market status, skip bet |
| Betslip not updated | JavaScript error or network issue | Retry click, verify betslip state |
| Duplicate selection | Outcome already in betslip | Handle gracefully, verify existing bet |

### SendToBetslip Function Parameters
The JavaScript function receives these parameters (extracted from onclick attribute):
- `outcome_id` (UUID): Unique identifier for the bet
- `outcome_text`: Display name ("Over 2.5", "Chelsea Win", etc.)
- `odds`: Current decimal odds (e.g., "2.6500")
- `sport`: Sport category ("Soccer", "Tennis", etc.)
- `market_title`: Market name ("Overs/Unders (Total 2.5)")
- `market_variation`: Additional context ("(Total 2.5)")
- `match_name`: Full match description ("Orbit College FC v Cape Town City FC")
- `match_datetime`: Match time ("6/25/2025 3:00:00 PM")
- `match_id` (UUID): Unique match identifier
- Additional technical parameters for tracking and validation

### Notes
- Each outcome button has a unique UUID in both `id` and `onclick` parameters
- The `data-pd` attribute contains precise odds for validation
- Market context helps disambiguate identical outcome names across different markets
- Button structure is consistent across all sports and market types

---

## 4. `get_account_balance`
High-level goal: return the current cash balance for the logged-in user.

| Field | Type | Description |
|-------|------|-------------|
| *none* | – | Read-only action |

**Pre-conditions**
1. Agent is authenticated.

**Execution outline**
1. If `#show-balance-btn` is visible, click it and wait 500 ms.
2. Read text from `.cashBalanceAmount`.
3. Strip currency symbol and convert to `float`.

**Success criteria**
• Parsed numerical balance returned.

**Common errors / edge cases**
• Not logged in → element missing.
• Unexpected text format.

---

## `show_all_markets`
Goal: Expand the full list of markets for the current event.

| Field | Type | Description |
|-------|------|-------------|
| *none* | – | Read-only click action |

Pre-conditions  
• On a match page; button `#AllMarketsButton` present.

Execution outline  
1. Locate `#AllMarketsButton`.  
2. Click it.  
3. Wait for network response or DOM change that indicates markets loaded (e.g., first `.row.search-link` appears).

Success criteria  
• Market accordion containers become present in DOM.  
• No error banner.

Common errors  
• Button not found (wrong page).  
• Network timeout.

---

## 5. `filter_by_leagues`
High-level goal: Filter the sports betting feed to show only matches from specific leagues/competitions.

| Field | Type | Description |
|-------|------|-------------|
| `league_names` | `List[str]` | List of league names to filter by (e.g., ["Premier League", "Serie A"]). |
| `country_names` | `Optional[List[str]]` | Optional country names to limit search scope. |
| `league_uuids` | `Optional[List[str]]` | Optional UUID list for precise league identification. |

### Pre-conditions
- User must be on a sports betting page with the league filter visible
- Filter must be in collapsed or expanded state

### Execution Outline
1. **Locate and expand main filter**
   - Find: `.league-filter-box h2` or element with `onclick*='toggleFilter'`
   - Click to expand if `#leagueGroup` has `style="display: none"`

2. **For each target league:**
   - If `country_names` provided, first expand relevant country sections:
     - Find: `#leagueLink-submenu_{CountryName}`
     - Click if corresponding `#submenu_{CountryName}` has `style="display: none"`
   
   - Locate specific league:
     - Primary: Use `league_uuids` if provided → `li.league-item[id='{uuid}']`
     - Fallback: Search by text content in `.league-item` elements
   
   - Select league:
     - Check current state: `data-checked` attribute
     - Click if `data-checked="False"`
     - Verify state change: `data-checked="True"` and icon becomes `glyphicon-check`

3. **Handle pagination if needed**
   - If league not found, click `#showMoreLeagues` if visible
   - Wait for AJAX completion (watch for DOM changes in `#league-ul-container`)
   - Repeat search

4. **Apply filters**
   - Click `#continueBtn` (Apply button)
   - Wait for page/content refresh
   - Verify selected count in header updates: `#selectedLCount`

### Success Criteria
- All specified leagues show `data-checked="True"`
- Selected count in filter header reflects number of chosen leagues
- Main betting feed updates to show only matches from selected leagues
- League filter collapses after applying

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| League not found | Typo in name, or not loaded yet | Try "Show More", then fallback to similar name matching |
| Country expansion fails | JavaScript error or timing | Retry with delay, use fallback selectors |
| Filter doesn't apply | Network/timing issue | Verify DOM state before clicking Apply |
| Duplicate league names | Multiple countries have same league | Use `country_names` parameter to disambiguate |

### Notes
- Prefer UUID-based selection when available (most reliable)
- Some countries appear multiple times in the filter - handle gracefully
- Filter state persists across page navigations within the same session
- AJAX loading means not all leagues are initially visible

---

### Future / Nice-to-have Actions
* `get_market_odds`
* `load_more_matches`
* `view_bet_history`
* `check_if_sufficient_funds`

These will follow the same template once researched. 

# Wait for and click the Apply button
apply_button = await page.query_selector("#continueBtn")
if not apply_button:
    apply_button = await page.query_selector(".btn.btn-primary.continue-btn-mobile")

await apply_button.click()

# Wait for the filter to apply and page content to update
# The filter should collapse and betting feed should refresh
await page.wait_for_function(
    "document.querySelector('#leagueGroup').style.display === 'none'"
)

# Optional: Wait for selected count to update in header
await page.wait_for_function(
    "parseInt(document.querySelector('#selectedLCount').textContent) > 0"
)

---

## 6. `open_betslip`
High-level goal: Open the betslip interface to review and manage selected bets before placement.

| Field | Type | Description |
|-------|------|-------------|
| `verify_selections` | `bool` | Whether to verify bet selections are present before opening (default: True). |

### Pre-conditions
- User must have made at least one bet selection
- Betslip button must be visible and clickable
- User must be on a betting page (Sports, Live, etc.)

### Execution Outline
1. **Verify bet selections exist** (if `verify_selections=True`)
   - Check that betslip button is present and enabled: `#betslipBtn`
   - Optional: Verify button text shows bet count or is highlighted

2. **Click betslip button**
   - Primary selector: `#betslipBtn`
   - Fallback: `button:has-text("Betslip")` or `[onclick*="mobileBetSlipButtonClick"]`
   - Execute: `homePage.mobileBetSlipButtonClick()`

3. **Wait for betslip interface to load**
   - Wait for betslip panel/modal to appear
   - Verify bet selections are displayed
   - Check for stake input fields and place bet controls

### Success Criteria
- Betslip interface opens successfully
- All previously selected bets are visible in the slip
- Stake input fields are available and functional
- "Place Bet" or equivalent action button is present

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Button not found | No bets selected yet | Return error indicating no selections made |
| Button disabled/grayed | Bets invalid or expired | Check bet status, retry selection if needed |
| Betslip doesn't open | JavaScript error or network issue | Retry click, check for error messages |
| Empty betslip | Bet selections lost/expired | Return to selection phase |

### Notes
- Button only appears/activates after successful bet selections
- Betslip state can be lost if session expires or odds change significantly
- Mobile vs desktop interfaces may vary in betslip presentation
- This action bridges bet selection and bet placement phases 

---

## 7. `set_bet_stakes`
High-level goal: Set stake amounts on selected bets in the betslip and configure bet type (single vs multi).

| Field | Type | Description |
|-------|------|-------------|
| `bet_type` | `str` | "single" or "multi" - determines betting mode. |
| `stakes` | `Dict[str, float]` | Dictionary mapping bet UUIDs to stake amounts in local currency. |
| `default_stake` | `Optional[float]` | Default stake for bets not specifically mentioned (default: 10.00). |

### Pre-conditions
- Betslip must be open with selected bets visible
- Bets must be present in `#betslip-list`
- Stakes must be valid positive numbers

### Execution Outline
1. **Set bet type mode**
   - If `bet_type="single"`: click `#sb_id` if not already active
   - If `bet_type="multi"`: click `#mb_id` if not already active
   - Verify mode change by checking `class="btn btn-primary active"`

2. **Configure individual stakes**
   - For each bet UUID in betslip:
     - Locate stake input: `#wagerAmount{uuid}`
     - Clear existing value and enter new stake from `stakes` dict or `default_stake`
     - Trigger change event: `UpdatePotentialSingleReturn('{uuid}')`
     - Verify potential return updates: `#potentialReturn{uuid}`

3. **Validate stake configuration**
   - Ensure all stake inputs have valid values > 0
   - Check that potential returns are calculated and displayed
   - Verify no error messages appear in betslip

### Success Criteria
- Correct bet type is selected (single/multi mode active)
- All stake inputs contain specified amounts
- Potential returns are calculated and displayed correctly
- No validation errors in betslip interface

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Stake input not found | Bet UUID invalid or bet removed | Refresh betslip, verify bet still exists |
| Invalid stake amount | Amount too low/high or format error | Use valid decimal format (e.g., "10.00") |
| Return calculation fails | Odds changed or network issue | Wait and retry, verify odds stability |
| Mode toggle fails | JavaScript error | Retry with delay, check element state |

### Notes
- Stakes are in local currency (R for South Africa)
- Multi-bet mode combines all selected bets into single accumulator
- Single-bet mode allows individual stakes per bet
- Returns auto-calculate but may change if odds update

---

## 8. `finalize_bet_placement`
High-level goal: Complete the betting process by placing all configured bets in the betslip.

| Field | Type | Description |
|-------|------|-------------|
| `confirm_stakes` | `bool` | Whether to verify stakes before placing (default: True). |
| `accept_odds_changes` | `bool` | Whether to proceed if odds have changed (default: False). |

### Pre-conditions
- Betslip is open with bets and stakes configured
- All stake amounts are valid and within betting limits
- User has sufficient balance for total stake amount

### Execution Outline
1. **Pre-placement validation**
   - Verify all bets still present in `#betslip-list`
   - Check stake inputs contain valid amounts
   - Confirm bet type mode is set correctly
   - Validate total stake against account balance

2. **Handle odds changes** (if any)
   - Check for odds change notifications/warnings
   - If `accept_odds_changes=True`: proceed
   - If `accept_odds_changes=False`: return error with details

3. **Locate and click place bet button**
   - Find final place bet button (likely at bottom of betslip)
   - Button may be labeled "Place Bet", "Place Bets", or similar
   - Click to initiate bet placement

4. **Handle confirmation dialogs**
   - Wait for any confirmation dialogs or final stake verification
   - Accept terms if required
   - Confirm final bet placement

5. **Verify placement success**
   - Wait for success confirmation or bet receipt
   - Check for error messages or failed placement notifications
   - Capture bet reference numbers/confirmation details

### Success Criteria
- Bet placement completes without errors
- Success confirmation or bet receipt is displayed
- Betslip clears after successful placement
- Account balance updates to reflect stake deduction

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Insufficient funds | Account balance too low | Return specific balance error |
| Odds changed | Market movements during placement | Handle based on `accept_odds_changes` setting |
| Bet limits exceeded | Stakes too high for user/market | Reduce stakes and retry |
| Market suspended | Event started or market closed | Remove affected bets, proceed with remainder |
| Network timeout | Connection issues during placement | Retry placement, verify if bet was placed |

### Notes
- This is the final irreversible step in the betting process
- Always verify success before reporting completion
- Capture all confirmation details for audit trail
- Failed bets may require manual intervention 

---

## 9. `generate_booking_code`
High-level goal: Generate a shareable booking code from the current betslip configuration for later reuse or sharing.

| Field | Type | Description |
|-------|------|-------------|
| `save_code` | `bool` | Whether to save the generated code for later use (default: True). |
| `dismiss_modal` | `bool` | Whether to automatically dismiss the booking code modal (default: True). |

### Pre-conditions
- Betslip must be open with at least one bet selection
- User must be logged in (booking codes may require authentication)
- Bet selections must be valid and current

### Execution Outline
1. **Trigger booking code generation**
   - Locate and click the share button: `#shareBookABet`
   - Wait for booking code generation process to complete

2. **Wait for confirmation modal**
   - Wait for modal to appear: `#modal-container-bet-confirmation[style*='display: block']`
   - Verify success message: "Booking Code has been successfully generated"

3. **Extract booking code**
   - Get code from display element or JavaScript variable
   - Primary: Extract from `.book-code` text content
   - Fallback: `await page.evaluate("window.bookingCode")`
   - Validate code format (typically 8-character alphanumeric: "BW######")

4. **Handle modal dismissal** (if `dismiss_modal=True`)
   - Click "Continue Betting" button: `#continueBettingBtn`
   - Wait for modal to close and betslip to return to normal state

### Success Criteria
- Booking code is successfully generated (8-character format)
- Code is extractable from modal or JavaScript variables
- Modal displays without errors
- If dismissed, betslip returns to normal operation

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Share button not found | No bets in betslip | Verify betslip has selections first |
| Modal doesn't appear | Network error or bet validation failed | Check for error messages, retry |
| Code extraction fails | Modal structure changed | Use fallback JavaScript variable method |
| Invalid code format | Generation error | Retry generation process |

### Return Value
```python
{
    "booking_code": "BW518F0B4",
    "share_url": "http://www.betway.co.za/bookabet/BW518F0B4",
    "generated_at": "2024-01-15T10:30:00Z",
    "bet_count": 2,
    "total_odds": 12.73
}
```

### Notes
- Booking codes preserve exact bet selections, odds, and stake configuration
- Codes can be loaded later using `load_booking_code` action
- Useful for saving successful betting strategies
- Codes may have expiration periods (check Betway terms)
- Generated URL format allows direct sharing via social media

---

## 10. `load_booking_code`
High-level goal: Load a previously saved betting configuration using a booking code.

| Field | Type | Description |
|-------|------|-------------|
| `booking_code` | `str` | The 8-character booking code to load (e.g., "BW518F0B4"). |
| `clear_existing` | `bool` | Whether to clear current betslip before loading (default: True). |

### Pre-conditions
- User must be on a betting page with betslip access
- Booking code must be valid and not expired
- User should have sufficient balance if auto-applying stakes

### Execution Outline
1. **Prepare betslip for loading**
   - Open betslip if not already open
   - If `clear_existing=True`: clear current selections via `ClearBetslip()`

2. **Enter booking code**
   - Locate booking code input: `#mtSearch`
   - Clear field and enter the provided `booking_code`
   - Trigger input validation: `enabledLoadBookingCodeBtn()`

3. **Load the configuration**
   - Verify load button is enabled: `#load-booking-code-btn` not disabled
   - Click load button to execute: `GetBookingCodeBetslip()`
   - Wait for loading process to complete

4. **Verify successful loading**
   - Check that bet selections appear in `#betslip-list`
   - Verify bet count matches expected configuration
   - Confirm stakes and odds are loaded correctly

### Success Criteria
- Booking code loads without errors
- All bet selections from saved configuration are restored
- Stakes and odds match the saved state (or current market odds)
- Betslip is ready for further modification or placement

### Common Errors & Handling
| Error | Cause | Action |
|-------|-------|--------|
| Invalid booking code | Code expired or doesn't exist | Return specific error about code validity |
| Load button disabled | Code format invalid | Verify code format and retry entry |
| Partial loading | Some markets unavailable | Report which selections failed to load |
| Odds changed | Markets moved since code generation | Accept new odds or report changes |
| Network timeout | Connection issues | Retry loading process |

### Notes
- Loaded configurations may have updated odds compared to when saved
- Some selections may be unavailable if markets closed or suspended
- Successful load restores the exact betting strategy for reuse
- Useful for implementing consistent betting strategies across sessions 