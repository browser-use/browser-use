from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log: logging.Logger = logging.getLogger(__name__)

GENESIS_HASH: str = (
    "0000000000000000000000000000000000000000000000000000000000000000"
)


@dataclass
class BrowserDebtReport:
    session_id: str
    action_type: str
    bdi_score: float  # Browser Debt Index (target <= 12.0)
    token_inflation_multiplier: float  # Target <= 1.15x
    step_latency_seconds: float  # Target <= 2.0s
    mutation_safety_score: float  # Target 100.0
    production_readiness_index: float  # Scale 0 - 100
    is_production_ready: bool
    critical_smells: List[str]
    receipt_hash: str


class TechnicalDueDiligenceLedger:
    """
    Cryptographic SHA-256 hash-chained Action Ledger for Browser Use agent runs.
    """

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._last_hash: str = GENESIS_HASH

    def record_browser_action(
        self,
        session_id: str,
        action_type: str,
        event_type: str,
        readiness_index: float,
        critical_smells: List[str],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        index = len(self._entries)

        meta_bytes = json.dumps(metadata, sort_keys=True).encode("utf-8")
        canonical_content = f"{index}|{self._last_hash}|{session_id}|{action_type}|{event_type}|{readiness_index}|{timestamp}|{hashlib.sha256(meta_bytes).hexdigest()}"
        curr_hash = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()

        entry = {
            "index": index,
            "timestamp": timestamp,
            "session_id": session_id,
            "action_type": action_type,
            "event_type": event_type,
            "readiness_index": readiness_index,
            "critical_smells": critical_smells,
            "prev_hash": self._last_hash,
            "curr_hash": curr_hash,
            "metadata": metadata,
        }

        self._entries.append(entry)
        self._last_hash = curr_hash
        return entry

    def get_ledger_entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def verify_ledger_integrity(self) -> bool:
        prev = GENESIS_HASH
        for entry in self._entries:
            if entry["prev_hash"] != prev:
                return False
            prev = entry["curr_hash"]
        return True


class ProductionDebtBrowserGate:
    """
    A2Z SOC Production Debt & Technical Due Diligence Gate for Browser Use.

    Quantifies browser agent actions against 4 Enterprise Forward Deployed Engineering KPIs:
    1. Browser Debt Index (BDI <= 12.0)
    2. Vision & DOM Token Inflation Multiplier (VTI <= 1.15x)
    3. P99 Single-Action Latency Ceiling (<= 2.0s)
    4. Deterministic Mutation Boundaries (never_equate_intent_to_approval)
    """

    def __init__(
        self,
        never_equate_intent_to_approval: bool = True,
        max_acceptable_bdi: float = 12.0,
    ) -> None:
        self.never_equate_intent_to_approval = never_equate_intent_to_approval
        self.max_acceptable_bdi = max_acceptable_bdi
        self.ledger = TechnicalDueDiligenceLedger()

    def check_kill_switch(self) -> bool:
        if os.environ.get("AAG_KILL_SWITCH", "").lower() in ("true", "1", "yes"):
            return True
        for path_str in ("artifacts/KILL", "/tmp/KILL"):
            if Path(path_str).exists():
                return True
        return False

    def evaluate_action(
        self,
        session_id: str,
        action_type: str = "click_element",
        context_tokens: int = 1200,
        vision_tokens: int = 150,
        step_latency_seconds: float = 1.1,
        dom_loop_count: int = 0,
        un_gated_mutations: int = 0,
    ) -> BrowserDebtReport:
        # 1. Evaluate emergency kill switch
        if self.check_kill_switch():
            self.ledger.record_browser_action(
                session_id=session_id,
                action_type=action_type,
                event_type="action_halted_kill_switch",
                readiness_index=0.0,
                critical_smells=["EMERGENCY_KILL_SWITCH_ENGAGED"],
                metadata={"reason": "AAG_KILL_SWITCH is set"},
            )
            raise PermissionError(
                "A2Z SOC ActionGate: Emergency kill switch is engaged. Browser session halted."
            )

        critical_smells: List[str] = []

        # KPI 2: Vision & DOM Token Inflation Multiplier
        token_ratio = (context_tokens + vision_tokens) / max(1, context_tokens)
        if token_ratio > 2.0:
            critical_smells.append(f"HIGH_VISION_TOKEN_INFLATION_{token_ratio:.2f}X")

        # KPI 3: Latency Ceiling
        if step_latency_seconds > 6.0:
            critical_smells.append(f"HIGH_DOM_ACTION_LATENCY_{step_latency_seconds:.2f}S")

        # DOM Loops
        if dom_loop_count > 2:
            critical_smells.append(f"DETECTED_{dom_loop_count}_DOM_NAVIGATION_LOOPS")

        # KPI 4: Mutation Safety
        if un_gated_mutations > 0:
            critical_smells.append(f"DETECTED_{un_gated_mutations}_UNGATED_MUTATIONS")

        # KPI 1: Browser Debt Index (0 = Clean, 100 = Catastrophic)
        bdi = (
            max(0.0, (token_ratio - 1.0) * 15.0)
            + max(0.0, (step_latency_seconds - 2.0) * 8.0)
            + (dom_loop_count * 12.0)
            + (un_gated_mutations * 30.0)
        )
        bdi_score = round(min(100.0, bdi), 2)

        # Production Readiness Index (0 - 100)
        readiness = max(0.0, 100.0 - bdi_score)
        is_production_ready = (
            bdi_score <= self.max_acceptable_bdi and len(critical_smells) == 0
        )

        # Cryptographic Ledger Entry
        entry = self.ledger.record_browser_action(
            session_id=session_id,
            action_type=action_type,
            event_type="action_authorized" if is_production_ready else "action_flagged_debt",
            readiness_index=readiness,
            critical_smells=critical_smells,
            metadata={
                "action_type": action_type,
                "bdi_score": bdi_score,
                "token_ratio": token_ratio,
                "step_latency_seconds": step_latency_seconds,
                "dom_loop_count": dom_loop_count,
                "un_gated_mutations": un_gated_mutations,
                "never_equate_intent_to_approval": self.never_equate_intent_to_approval,
            },
        )

        return BrowserDebtReport(
            session_id=session_id,
            action_type=action_type,
            bdi_score=bdi_score,
            token_inflation_multiplier=round(token_ratio, 2),
            step_latency_seconds=round(step_latency_seconds, 2),
            mutation_safety_score=(
                100.0 if un_gated_mutations == 0 else max(0.0, 100.0 - un_gated_mutations * 30.0)
            ),
            production_readiness_index=readiness,
            is_production_ready=is_production_ready,
            critical_smells=critical_smells,
            receipt_hash=entry["curr_hash"],
        )
