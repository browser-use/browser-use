---
name: x402
description: Set up Browser Use Cloud payments with x402 — pay per request from a crypto wallet (USDC on Base mainnet), no signup or API key. Two setups it works out up front — "just use it" (set up a wallet so you or Claude Code can run cloud browser tasks paid from the wallet — Claude writes and runs throwaway scripts, nothing touches your codebase) or "build it in" (install the SDK and write the key + code into your project). Walks through wallet setup, funding, .env, and a ~$1 test run. Use when the user asks about x402, pay-per-use, USDC payments, or wants Browser Use Cloud without an API key. For the free-tier signup (reverse-CAPTCHA → API key), use `browser-use cloud signup` or the `cloud` skill instead.
allowed-tools: Bash, Read, Write, Edit
---

# Browser Use Cloud — pay with x402 (crypto wallet)

This is a scripted flow. Follow the steps in order. x402 only works through the **SDK** (`browser-use-sdk` for Python, the `browser-use` npm package for TS) — there is no `browser-use` CLI command for it, so every step runs a short SDK script.

## How to use this script

- Lines under **Say:** are spoken to the user **word for word.** Don't paraphrase, add, or drop anything.
- `<like this>` inside a Say block is a fill-in — replace it with the real value, keep the rest exact.
- Lines under **Ask:** use the AskUserQuestion tool. Use the question and option text exactly as written.
- **To show an explanation before a question, put it inside the AskUserQuestion `question` field** (it renders above the options). Don't send it as separate chat text before calling the tool — that text gets dropped when the question UI opens. So: explanation + the actual question both go in the `question` field, in one tool call.
- Lines under **Do:** are your actions. Don't read them out.
- Track two facts as you go: `SETUP` (A or B, from Step 1) and `MODE` (A or B, from Step 2).
- **`SETUP`, `MODE`, and the Path A/B/C names are internal labels for you only. Never say them to the user.** Describe choices in plain words instead (e.g. "top up your account" / "accountless wallet"), never "Mode B" or "Path A".

---

## Step 1 — Open and pick the setup

**Ask:** (header: `Use x402`) — put the explanation and the question both in the `question` field, exactly:

> x402 is a protocol from Coinbase that, instead of presenting an API key, allows you to use crypto to pay for API requests. x402 lets you pay Browser Use per request from a crypto wallet with USDC on Base — no signup, API key, or credit card needed, just a wallet. Setup takes a few minutes: get or make a wallet, add funds, save the key in `.env`, and test it.
>
> How do you want to use x402?
- **Just use it** — Run Browser Use tasks, paid from your wallet, here in terminal by asking me. I set up the wallet and key.
- **Build it in** — You're coding an app and want x402 in it. I will help you install the SDK, save the key to your project's `.env`, and add code.

**Do:** "Just use it" → `SETUP = A`. "Build it in" → `SETUP = B`.

---

## Step 2 — Find the account (check before asking)

**Do:** Look for an existing Browser Use API key, in this order. Don't say anything yet.
1. `BROWSER_USE_API_KEY` in the environment
2. a `BROWSER_USE_API_KEY=` line in `./.env`
3. `~/.browser-use/config.json` (saved by `browser-use cloud login` / `signup`)
4. `browser-use doctor` output, if the CLI is installed

**If no key is found anywhere:**

**Say:**
> No Browser Use key found, so I'll set this up accountless: the wallet is your identity, and the first payment makes a project named after it.

**Do:** `MODE = A`. Go to Step 3.

**If a key is found:**

**Ask:** (header: `Account`) — question: `I found a Browser Use API key in <location>. Where should the USDC credits go?`
- **Top up that account** — Credits go to your existing API key's project. Good if your free credits ran out, or you'd rather pay with crypto than a card.
- **Accountless wallet** — The wallet is a separate identity. The first payment makes a fresh project named after the wallet, apart from your existing account.

**Do:** "Top up that account" → `MODE = B`. "Accountless wallet" → `MODE = A`.

---

## Step 3 — Wallet

**Ask:** (header: `Wallet`) — question: `Do you have a wallet ready, or should I set one up?`
- **I have a funded wallet** — An EVM wallet (MetaMask, Rabby, Coinbase Wallet, Frame, Phantom, …) with USDC on Base mainnet.
- **Walk me through it** — I'll guide you through making a wallet, adding Base, and buying USDC.
- **Make a fresh one** — I'll generate a throwaway wallet for automation. You'll still need to fund it.

Branch on the answer.

### Path A — "I have a funded wallet"

**Do:** Check `.env` is in `.gitignore`; add it if missing.

**Ask:** (header: `Add key`) — put the note and the question both in the `question` field:
> Your wallet's private key needs to go into `.env`. You can paste it here and I'll add it for you, or add it yourself. Heads up: anything pasted in chat is saved in the transcript, so for a high-value wallet, adding it yourself is a bit safer. How do you want to do it?

- **Paste it here** — Paste your private key in the chat and I'll write it to `.env` for you.
- **I'll add it myself** — You add it to `.env`, then send me just your public address.

**If "Paste it here":**

**Do:** Write `BROWSER_USE_X402_PRIVATE_KEY=<pasted key>` to `.env` (create the file if needed; make sure `.env` is gitignored). Never echo the key back or print it anywhere.

**Say:**
> Saved your key to `.env` — I won't print it back.

**Do:** Go to Step 4.

**If "I'll add it myself":**

**Say:**
> Add this line to your `.env`, then send me your wallet's public address (the `0x…` one — safe to share):
> ```
> BROWSER_USE_X402_PRIVATE_KEY=<your private key>
> ```

**Do:** When they send the address, check it matches `^0x[0-9a-fA-F]{40}$`.

**Say:**
> Got it: `<address>`. That's a valid address.

**Do:** Go to Step 4.

### Path B — "Walk me through it"

**Say:**
> 1. Install MetaMask (or Rabby, Coinbase Wallet, Frame, Trust Wallet, Phantom, …) from the official site only: https://metamask.io. Make a wallet, save the seed phrase offline, set a password.
> 2. Add Base as a network. Open https://chainlist.org/chain/8453 → "Connect Wallet" → "Add to MetaMask", then approve it in your wallet.
> 3. Click "Buy" in your wallet. Pick USDC, network Base, pay with card / Apple Pay / bank. The USDC lands straight in your wallet.
> 4. Get the private key: account menu → Account details → Show private key → enter password → copy.
> 5. Add it to your `.env` (make sure `.env` is gitignored):
> ```
> BROWSER_USE_X402_PRIVATE_KEY=<your private key>
> ```
> 6. Send me your wallet's public address (the `0x…` one) so I can check it.

**Do:** Then follow Path A from the address check onward.

### Path C — "Make a fresh one"

**Do:** Generate a wallet. Save the key to `.env`. Show the address only.

Python:
```bash
pip install eth-account
```
```python
from eth_account import Account
acc = Account.create()
print("Address:", acc.address)
print("Private key:", acc.key.hex())
```

TypeScript:
```bash
npm install viem
```
```typescript
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
const key = generatePrivateKey();
console.log("Address:", privateKeyToAccount(key).address);
console.log("Private key:", key);
```

**Say:**
> Made a fresh wallet. Your public address is `<address>`, and I've saved the private key to `.env`. Now it needs funds.

**Do:** Go to Step 4 (funding).

---

## Step 4 — Add funds

**If Path A or B (already funded):**

**Say:**
> Your wallet's already funded, so we'll skip ahead to the test.

**Do:** Go to Step 5.

**If Path C:**

**Say:**
> Two ways to get USDC into your wallet on Base:
> - In-wallet Buy button (easiest): click "Buy", pick USDC, set the network to Base, pay with a card. No exchange needed.
> - From an exchange: send USDC to `<address>` and pick "Base" as the network — not Ethereum, which costs $5–$20 in fees.
>
> Add at least $20: that covers the $1 test plus a few real tasks. I'll watch the balance and tell you when it lands.

**Do:** Check the on-chain balance every 5s with Base's public RPC:
```bash
PADDED=$(printf "%064s" "${WALLET_ADDR:2}" | tr ' ' '0')
curl -s https://mainnet.base.org \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_call\",\"params\":[{\"to\":\"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913\",\"data\":\"0x70a08231${PADDED}\"},\"latest\"],\"id\":1}"
```
Read `result` as a hex number; divide by `1_000_000` (USDC has 6 decimals). Stop once it's $20 or more.

**Say:**
> Funded — I see $<amount> on Base. Next, a quick test.

---

## Step 5 — Test run (~$1)

**Do:** If `SETUP = A`, make sure the SDK is installed where you'll run scripts (default Python). If `SETUP = B`, install it into the project in the project's language — work out the language from the cwd (`package.json`/`tsconfig.json` → TypeScript; `pyproject.toml`/`requirements.txt`/`*.py` → Python; ask only if you can't tell):
```bash
# Python (needs 3.10+ for the x402 extra)
pip install "browser-use-sdk[x402]"
# TypeScript
npm install browser-use-sdk @x402/fetch @x402/evm viem
```

**Ask:** (header: `Test run`) — question: `Ready to test? This spends exactly $1 USDC from your wallet to check payment + run work end to end.`
- **Use the default task** — "Go to example.com and tell me the heading text." (~5 seconds, cheap)
- **I'll give you a task** — Tell me a short task to run instead.
- **Skip the test** — Skip the test and go straight to using x402.

**Do:**
- "I'll give you a task" → **Say:** `What's the task? Keep it short.` Wait for it.
- "Skip the test" → go to Step 6.
- Otherwise use the default task.

**Do:** Run the test. Use the raw x402 client with `max_value` of $1.50 so it pays $1, not the $5 the SDK uses by default:
```python
import asyncio, os
from decimal import Decimal
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from eth_account import Account

async def main():
    client = x402Client()
    register_exact_evm_client(
        client,
        EthAccountSigner(Account.from_key(os.environ["BROWSER_USE_X402_PRIVATE_KEY"])),
    )
    # max_value caps the spend per request — picks the $1 option over the $5 default.
    async with x402HttpxClient(client, max_value=Decimal("1.5"), timeout=180.0) as http:
        resp = await http.post(
            "https://x402.api.browser-use.com/api/v3/sessions",
            json={"task": "<the task>"},
        )
        print(resp.status_code, resp.json())

asyncio.run(main())
```
If `MODE = B`, add the API key header, or the $1 goes to a new wallet project instead of the one being topped up:
```python
async with x402HttpxClient(
    client, max_value=Decimal("1.5"), timeout=180.0,
    headers={"X-Browser-Use-API-Key": os.environ["BROWSER_USE_API_KEY"]},
) as http:
    ...
```
If the installed `x402` lib has no `max_value`, **Say:** `That x402 version can't force a $1 charge, so the test will cost $5 instead. Want me to go ahead?` — wait for a yes before running.

**Say:**
> Paid. On-chain proof: https://basescan.org/address/<address>#tokentxns — look for a USDC transfer out of exactly $1.000000.

**Do:** Read the balance. If `MODE = A` (needs `browser-use-sdk` ≥ 3.8.0; if older, say to run `pip install -U "browser-use-sdk[x402]"` or skip this):
```python
import asyncio, os
from browser_use_sdk.v3 import get_wallet_balance

async def main():
    bal = await get_wallet_balance(os.environ["BROWSER_USE_X402_PRIVATE_KEY"])
    print(bal['total_credits_usd'])

asyncio.run(main())
```
If `MODE = B`, skip `get_wallet_balance` (it returns 404 — the credits sit in the API key's project, that's normal, don't show it as an error) and read it the normal way:
```python
from browser_use_sdk.v3 import AsyncBrowserUse
client = AsyncBrowserUse(api_key=os.environ["BROWSER_USE_API_KEY"])
acct = await client.billing.account()
print(acct.total_credits_balance_usd)
```

**Say:**
> Done. Your Browser Use balance is now $<balance> (the test cost about $<cost>). Tasks draw from this, and the SDK adds another $5 when it runs out.

---

## Step 6 — Wrap up

**If `SETUP = A`:**

**Say:**
> All set. Ask me to run any browser task and I'll run it through the SDK, paid from your wallet.

**Do:** When they ask for a task, write a throwaway script (in `/tmp`, or a background job for long ones), run it, report the result, and delete it — don't leave files in their cwd. The SDK reads `BROWSER_USE_X402_PRIVATE_KEY` and finds the x402 endpoint on its own:
```python
import asyncio, os
from browser_use_sdk.v3 import AsyncBrowserUse

async def main():
    client = AsyncBrowserUse()  # Mode B: AsyncBrowserUse(api_key=os.environ["BROWSER_USE_API_KEY"])
    result = await client.run(task="<the task>")
    print(result.output)

asyncio.run(main())
```

**If `SETUP = B`:**

**Say:**
> All set. Here's the client to use in your code — it reads the key and endpoint from your `.env`:

**Do:** Add the client in the project's language and point them at the `cloud` skill / SDK docs for the rest:
```python
from browser_use_sdk.v3 import AsyncBrowserUse

client = AsyncBrowserUse()                                  # Mode A (accountless)
# client = AsyncBrowserUse(api_key="bu_...")                # Mode B (top up existing account)
```

(x402 needs the **async** client — the sync `BrowserUse` won't run when the x402 env var is set.)

---

## TypeScript equivalents

| Python | TypeScript |
|---|---|
| `from browser_use_sdk.v3 import AsyncBrowserUse` | `import { BrowserUse } from "browser-use-sdk/v3"` |
| `AsyncBrowserUse()` | `new BrowserUse()` |
| `await client.run(task=...)` → `.output` | `await client.run({ task })` → `.output` |
| `get_wallet_balance(key)` | `getWalletBalance(key)` (`from "browser-use-sdk/v3"`) |
| `pip install "browser-use-sdk[x402]"` | `npm install browser-use-sdk @x402/fetch @x402/evm viem` |

Both SDKs read `BROWSER_USE_X402_PRIVATE_KEY` from the env.

## Rules

- **Follow the script in order. Say the Say blocks word for word.**
- **Never spend the user's USDC without a clear yes** (the Step 5 question is that yes).
- **Always offer both ways to add the key**: paste it in chat (you write it to `.env`) or the user adds it themselves. If they paste it, write it straight to `.env` and never echo it back or store it anywhere else.
- **Add `.env` to `.gitignore` before saving keys.**
- **Wallets hold real money.** Keep keys out of source control, logs, and screenshots; only add what you can afford to lose if it leaks.

## Reference

- x402 user docs: https://docs.browser-use.com/cloud/guides/x402
- Claude Code + Browser Use Cloud: https://docs.browser-use.com/cloud/tutorials/integrations/claude-code
- x402 protocol: https://www.x402.org
- USDC on Base contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Base RPC: https://mainnet.base.org · Basescan: https://basescan.org
