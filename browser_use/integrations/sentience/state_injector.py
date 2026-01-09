"""Inject Sentience semantic geometry into Agent context."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from sentience.models import Snapshot

logger = logging.getLogger(__name__)


@dataclass
class SentienceState:
    """Sentience state with snapshot and formatted prompt block."""

    url: str
    snapshot: "Snapshot"
    prompt_block: str


def format_snapshot_for_llm(snapshot: "Snapshot", limit: int = 100) -> str:
    """
    Format Sentience snapshot for LLM consumption.

    Creates a compact inventory of elements with IDs, roles, names, and bbox centers.
    This gives the LLM a reduced action space to pick from.

    Args:
        snapshot: Sentience Snapshot object
        limit: Maximum number of elements to include (default: 100)

    Returns:
        Formatted string for LLM prompt
    """
    lines = []
    for el in snapshot.elements[:limit]:
        # Calculate bbox center
        cx = int(el.bbox.x + el.bbox.width / 2)
        cy = int(el.bbox.y + el.bbox.height / 2)

        # Get role (prefer role, fallback to tag)
        role = getattr(el, "role", None) or getattr(el, "tag", None) or "el"

        # Get name/text (truncate if too long)
        name = (getattr(el, "name", None) or getattr(el, "text", None) or "").strip()
        if len(name) > 80:
            name = name[:77] + "..."

        # Format: [ID] <role> "name" @ (cx,cy)
        lines.append(f"[{el.id}] <{role}> \"{name}\" @ ({cx},{cy})")

    return "\n".join(lines)


async def build_sentience_state(
    browser_session: "BrowserSession",
) -> Optional[SentienceState]:
    """
    Build Sentience state from browser session.

    Takes a snapshot using the Sentience extension and formats it for LLM consumption.
    If snapshot fails (extension not loaded, timeout, etc.), returns None.

    Args:
        browser_session: Browser-use BrowserSession instance

    Returns:
        SentienceState with snapshot and formatted prompt, or None if snapshot failed
    """
    try:
        # Import here to avoid requiring sentience as a hard dependency
        from sentience.backends import BrowserUseAdapter
        from sentience.backends.snapshot import snapshot
        from sentience.models import SnapshotOptions

        # Create adapter and backend
        adapter = BrowserUseAdapter(browser_session)
        backend = await adapter.create_backend()

        # Give extension a moment to inject (especially after navigation)
        # The snapshot() call has its own timeout, but a small delay helps
        import asyncio
        await asyncio.sleep(0.5)

        # Get API key from environment if available
        api_key = os.getenv("SENTIENCE_API_KEY")
        # Limit to 100 elements to keep prompt size manageable
        if api_key:
            options = SnapshotOptions(sentience_api_key=api_key, limit=100)
        else:
            options = SnapshotOptions(limit=100)  # Use default options if no API key

        # Take snapshot with retry logic (extension may need time to inject after navigation)
        max_retries = 2
        last_error = None
        for attempt in range(max_retries):
            try:
                snap = await snapshot(backend, options=options)
                break  # Success
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    # Wait a bit longer before retry
                    logger.debug(f"Sentience snapshot attempt {attempt + 1} failed, retrying...")
                    await asyncio.sleep(1.0)
                else:
                    raise  # Re-raise on final attempt

        # Get URL from snapshot or browser state
        url = getattr(snap, "url", "") or ""

        # Format for LLM (limit to 100 elements to keep prompt size manageable)
        formatted = format_snapshot_for_llm(snap, limit=100)

        prompt = (
            "## Sentience Element Inventory (semantic geometry)\n"
            "Use these numeric IDs with tools like click(index=ID) / input_text(index=ID,...).\n"
            "Prefer these IDs over guessing coordinates.\n\n"
            f"{formatted}"
        )

        logger.info(f"✅ Sentience snapshot: {len(snap.elements)} elements, URL: {url}")
        return SentienceState(url=url, snapshot=snap, prompt_block=prompt)

    except ImportError:
        logger.warning("⚠️  Sentience SDK not available, skipping snapshot")
        return None
    except Exception as e:
        # Log warning if extension not loaded or snapshot fails
        logger.warning(f"⚠️  Sentience snapshot skipped: {e}")
        return None
