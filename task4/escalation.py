"""
Task 4 — Escalation Decision Engine
Determines whether a customer interaction should be handled by the AI
or handed off to a human agent.
"""

import sys
import os

# Allow imports from task3 when running standalone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "task3"))
from fetcher import CustomerContext  # noqa: E402


def should_escalate(
    context: CustomerContext,
    confidence_score: float,
    sentiment_score: float,   # -1.0 (very negative) to +1.0 (very positive)
    intent: str,
) -> tuple[bool, str]:
    """
    Decide whether this interaction requires a human agent.

    Rules are evaluated IN ORDER. The first matching rule wins.
    Returns (escalate: bool, reason: str).
    When no rule fires, returns (False, "ai_can_handle").

    Rule priority (highest → lowest):
        4 → service_cancellation  (hard rule — no exceptions)
        1 → low confidence
        2 → angry customer
        3 → repeat complaint
        5 → VIP + overdue billing
        6 → incomplete data + marginal confidence
    """

    # ------------------------------------------------------------------
    # Rule 4: service cancellation — ALWAYS escalate, no exceptions.
    # Evaluated first because it overrides every other rule (even Rule 1).
    # ------------------------------------------------------------------
    if intent.lower() == "service_cancellation":
        return True, "service_cancellation"

    # ------------------------------------------------------------------
    # Rule 1: AI is not confident enough to handle the query reliably.
    # ------------------------------------------------------------------
    if confidence_score < 0.65:
        return True, "low_confidence"

    # ------------------------------------------------------------------
    # Rule 2: Customer is very upset — a human can de-escalate better.
    # ------------------------------------------------------------------
    if sentiment_score < -0.6:
        return True, "angry_customer"

    # ------------------------------------------------------------------
    # Rule 3: Customer has complained about the same issue 3+ times.
    # Chronic repeats indicate the AI hasn't solved the root cause.
    # ------------------------------------------------------------------
    if context.ticket_data:
        complaints = context.ticket_data.get("last_5_complaints", [])
        intent_count = sum(
            1 for c in complaints if c.get("intent", "").lower() == intent.lower()
        )
        if intent_count >= 3:
            return True, "repeat_complaint"

    # ------------------------------------------------------------------
    # Rule 5: VIP customer with an overdue bill — high churn risk,
    # handle personally to preserve relationship.
    # ------------------------------------------------------------------
    is_vip = context.crm_data and context.crm_data.get("is_vip", False)
    is_overdue = context.billing_data and context.billing_data.get("is_overdue", False)
    if is_vip and is_overdue:
        return True, "vip_overdue_billing"

    # ------------------------------------------------------------------
    # Rule 6: We're missing data AND the AI is only marginally confident.
    # Better to escalate than to risk a wrong automated decision.
    # ------------------------------------------------------------------
    if not context.data_complete and confidence_score < 0.80:
        return True, "incomplete_data_low_confidence"

    # No rule fired — AI can handle this.
    return False, "ai_can_handle"
