---
name: x402
description: Onboard a developer to Browser Use Cloud using x402 pay-per-request authentication — wallet-based USDC payments on Base mainnet, no signup or API key. Walks the user through setting up a wallet, funding it with USDC on Base, writing credentials to .env, installing the SDK, and running a verification task. Use when the user asks about x402, pay-per-use, USDC payments, or wants to use Browser Use Cloud without an API key. For the standard free-tier signup (reverse-CAPTCHA → API key), use the `cloud` skill or run `browser-use cloud signup` directly. Distinct from the `browser-use` skill which controls the local CLI.
allowed-tools: Bash, Read, Write, Edit
---

# Browser Use Cloud — x402 onboarding

You are guiding a developer to authenticate with Browser Use Cloud using **x402** (HTTP-native payments via USDC on Base mainnet) instead of an API key. End state: working SDK client that pays per request from a wallet they control.

Reference: https://docs.browser-use.com/cloud/guides/x402 has the full user-facing version of this flow.

## When to use this skill vs alternatives

- **This skill (`x402`):** wallet-based payments. Two sub-modes — see "Two payment modes" below.
- **`browser-use cloud signup`** (CLI command): free tier with reverse-CAPTCHA → standard API key. Faster, no wallet needed. Use this if the user just wants to try Browser Use Cloud quickly.
- **`cloud` skill:** documentation reference for the API. Use when the user asks how to use already-authenticated calls.

## Two payment modes

x402 supports two flows. Pick based on whether the user already has an API key.

### Mode A — Accountless (no signup)

Wallet IS the identity. First payment auto-creates a project named after the wallet. No email, no API key.

Use when:
- User has no existing Browser Use account
- Building autonomous agents that hold their own wallet
- Discovering Browser Use via the x402 directory and wanting hit-and-pay

### Mode B — Top up an existing account

Same payment, but credits land in an existing API-key's project instead of a wallet-derived one. Useful when:
- User self-registered via `browser-use cloud signup`, used the free credits, and needs more
- User has a regular Browser Use account and wants to add credits via crypto instead of credit card
- Multi-agent system where many wallets fund one shared account

Mechanically: same `https://x402.api.browser-use.com` endpoint, but include the `X-Browser-Use-API-Key` header alongside the payment. The backend detects the key and credits that project instead of auto-creating a wallet-keyed one.

If the user is unsure which mode they want, ask:

> Do you already have a Browser Use API key (e.g. from `browser-use cloud signup` or the dashboard)?
>
> - **Yes** → I'll set up x402 to top up that account.
> - **No** → I'll set up x402 in accountless mode (wallet is your identity).

Either path goes through the same wallet setup steps below; the only difference is whether the `X-Browser-Use-API-Key` env var also gets set.

## Step 0: Detect the language

Look at the cwd to figure out what they're building in:

- `package.json` / `tsconfig.json` / `pnpm-lock.yaml` → TypeScript
- `pyproject.toml` / `requirements.txt` / any `.py` → Python
- Both / neither → ask which

Use this for install commands and code samples. Examples below default to Python; substitute TypeScript per the table at the bottom.

## Step 1: Wallet

Ask:

> Do you already have an EVM wallet (e.g. MetaMask, Rabby, Coinbase Wallet, Frame, Phantom) with USDC on Base mainnet, or do you want me to walk you through setting one up? For Claude Code automation, generating a fresh disposable wallet is also an option.

### Path A — User has a wallet already

Direct the user to set the key themselves in their project's `.env`, and just ask for the public address for confirmation:

1. Verify `.env` is in `.gitignore` — add it if not.
2. Tell the user to add the key to their project's `.env`:
   ```
   BROWSER_USE_X402_PRIVATE_KEY=0x...
   ```
3. Ask them to share their wallet's **public address** for confirmation. Verify it's a valid EVM address (`^0x[0-9a-fA-F]{40}$`) and display it back.

If they paste a private key directly into the chat instead, just take it — validate format (`^0x[0-9a-fA-F]{64}$`), save to `.env`, derive the address for confirmation, and continue.

### Path B — Walk them through setting up a wallet

Tell the user:

> Easiest path:
>
> 1. Install **MetaMask** (or any other EVM wallet — Rabby, Coinbase Wallet, Frame, Trust Wallet, Phantom, etc.) from the official site only: https://metamask.io. Create a wallet, save the seed phrase offline, set a password.
> 2. Add **Base** as a network. Most wallets only show Ethereum by default. Open https://chainlist.org/chain/8453, click "Connect Wallet" → "Add to MetaMask", approve in your wallet.
> 3. Click **"Buy"** inside MetaMask. Pick **USDC**, set network to **Base**, pay with credit card / Apple Pay / bank via the built-in onramp. The USDC lands directly in your wallet.
> 4. Export the private key: account menu → Account details → Show private key → enter password → copy.
> 5. Add the key to your project's `.env` (make sure `.env` is in your `.gitignore`):
>    ```
>    BROWSER_USE_X402_PRIVATE_KEY=0x...
>    ```
> 6. Share your wallet's **public address** so I can confirm it's set up correctly.

Then proceed as in Path A.

### Path C — Auto-generate a fresh wallet (for Claude Code automation)

Useful for autonomous agents or test setups. The user still has to fund the resulting address themselves.

For Python:
```bash
pip install eth-account
```
```python
from eth_account import Account
acc = Account.create()
print("Address:", acc.address)
print("Private key:", acc.key.hex())
```

For TypeScript:
```bash
npm install viem
```
```typescript
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
const key = generatePrivateKey();
const acc = privateKeyToAccount(key);
console.log("Address:", acc.address);
console.log("Private key:", key);
```

Save the key to `.env`. **Display the address, never echo the private key in chat.** Then send the user to fund it (see Step 2).

## Step 2: Fund the wallet (only if not already funded)

For Path A / B: the wallet is already funded. Skip this step.

For Path C: tell the user (substitute their wallet address):

> Two ways to get USDC into your wallet on Base:
>
> - **In-wallet Buy button (easiest):** if you used MetaMask or another wallet that supports it, click "Buy" inside the wallet, pick USDC, set network to Base, pay with credit card. USDC lands directly. No exchange account needed.
> - **From an existing exchange:** if you already have crypto on Coinbase, Binance, Kraken, etc., withdraw USDC to `<wallet-address>` and **pick "Base" as the network** (NOT Ethereum — that costs $5–$20 in gas).

Poll the on-chain balance every 5 seconds via Base public RPC (no API key needed):

```bash
PADDED=$(printf "%064s" "${WALLET_ADDR:2}" | tr ' ' '0')
curl -s https://mainnet.base.org \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_call\",\"params\":[{\"to\":\"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913\",\"data\":\"0x70a08231${PADDED}\"},\"latest\"],\"id\":1}"
```

Decode the `result` field as a hex int; divide by `1_000_000` (USDC has 6 decimals). **Recommend funding with at least $20.** That gives room for the $1 verification charge plus headroom for several real tasks. Stop polling once the on-chain balance is ≥ $20.

## Step 3: Install the SDK with the x402 extra

```bash
# Python (Python 3.10+ required for the x402 extra)
pip install "browser-use-sdk[x402]"

# TypeScript
npm install browser-use-sdk @x402/fetch @x402/evm viem
```

If the project uses `uv` / `pnpm` / `yarn`, prefer those over `pip` / `npm`.

## Step 4: Verification run

**Do not run anything yet.** First, ask the user for permission and explain what's about to happen:

> Ready to verify your x402 setup. Here's what I'll do:
>
> - Spend exactly **$1 USDC** from your wallet — the minimum x402 top-up. Settled on-chain to Browser Use's prod payee.
> - Run a tiny test task to confirm payment + credit grant + execution all work end-to-end.
> - Show you the Basescan transaction so you can see settlement.
>
> Default test task: *"Go to example.com and tell me the heading text."* (cheap, ~5 seconds).
>
> Want to use the default task, suggest your own (keep it short), or skip the verification?

Wait for confirmation. If they suggest a custom task, use that.

To force the **$1** option (instead of the $5 default that the SDK would normally pick when the wallet has ≥ $5), use the raw x402 client with a `max_value` constraint of $1.50. This skips the $5 option in the 402 challenge and pays $1:

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
    # max_value caps what the client is willing to pay per challenge —
    # forces the $1 fallback instead of the $5 default in our [$5, $1] accepts list.
    async with x402HttpxClient(client, max_value=Decimal("1.5"), timeout=180.0) as http:
        resp = await http.post(
            "https://x402.api.browser-use.com/api/v3/sessions",
            json={"task": "<the task the user agreed to>"},
        )
        print(resp.status_code, resp.json())

asyncio.run(main())
```

If the installed `x402` version doesn't accept `max_value` on `x402HttpxClient`, fall back to using our SDK (`AsyncBrowserUse()`) — but **tell the user first** that this will cost $5 instead of $1, and re-confirm before running.

**For Mode B (top-up)**, the API key only matters when going through our SDK. For the $1 raw-client verification above, omit it; once verified, switch to the SDK with both `api_key` and `x402_private_key` for real use:

```python
client = AsyncBrowserUse(
    api_key="bu_...",                    # the existing API key getting topped up
    x402_private_key="0x...",            # wallet that pays
    base_url="https://x402.api.browser-use.com/api/v3",
)
```

After verification returns, show the user proof of settlement:

> Onchain proof: https://basescan.org/address/<wallet-address>#tokentxns

Look for an outbound USDC transfer of exactly `$1.000000`.

Once verification passes, transition the user to the SDK (`AsyncBrowserUse()` / `new BrowserUse()`) for real tasks — that path uses the $5 default top-up.

## TypeScript equivalents

| Python | TypeScript |
|---|---|
| `from browser_use_sdk.v3 import AsyncBrowserUse` | `import { BrowserUse } from "browser-use-sdk/v3"` |
| `AsyncBrowserUse()` | `new BrowserUse()` |
| `pip install "browser-use-sdk[x402]"` | `npm install browser-use-sdk @x402/fetch @x402/evm viem` |

Both SDKs auto-detect `BROWSER_USE_X402_PRIVATE_KEY` from env.

## Behavior rules

- **Add `.env` to `.gitignore`** before writing keys. Verify first.
- **Confirm `.env` location** if ambiguous (project root vs cwd).
- **Never spend the user's USDC without explicit consent.** Step 4 must always pause for permission before running, explain that it costs $1, and accept a custom task or a "skip verification" response.
- **If you can't force a $1 charge** (e.g. installed `x402` lib doesn't support `max_value`), tell the user the verification will instead cost $5 and re-confirm before running.
- **Python <3.10:** the `[x402]` extra won't install. Tell the user to upgrade Python or use the free-tier path (`browser-use cloud signup`).
- **Wallets hold real money.** Anyone with the private key can drain them. Tell the user to keep keys out of source control, logs, and screenshots, and to only fund with what they're okay losing if something leaked.

## Reference

- x402 user docs: https://docs.browser-use.com/cloud/guides/x402
- x402 protocol: https://www.x402.org
- Coinbase x402 launch: https://www.coinbase.com/developer-platform/discover/launches/x402
- USDC on Base contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Base RPC: https://mainnet.base.org
- Basescan: https://basescan.org
