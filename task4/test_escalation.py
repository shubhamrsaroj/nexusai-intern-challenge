"""
Task 4 — Pytest test suite for the Escalation Decision Engine
Run with: pytest task4/ -v

Each test uses a freshly built CustomerContext so all 8 tests are
fully independent (no shared mutable state).
"""

import sys
import os

# Make escalation.py importable regardless of cwd
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "task3"))

import pytest
from fetcher import CustomerContext
from escalation import should_escalate


# ============================================================================
# Helpers — build minimal CustomerContext objects for tests
# ============================================================================

def _make_context(
    *,
    is_vip: bool = False,
    is_overdue: bool = False,
    data_complete: bool = True,
    ticket_intents: list[str] | None = None,
) -> CustomerContext:
    """
    Build a CustomerContext with controllable fields for unit testing.
    Omitted billing/crm data defaults to empty dicts (not None),
    so Rule 5 correctly reads is_vip and is_overdue.
    """
    if ticket_intents is None:
        ticket_intents = []

    complaints = [
        {"id": f"TK-{i}", "intent": intent, "status": "closed"}
        for i, intent in enumerate(ticket_intents)
    ]

    return CustomerContext(
        phone="+10000000000",
        crm_data={"is_vip": is_vip},
        billing_data={"is_overdue": is_overdue},
        ticket_data={"last_5_complaints": complaints},
        data_complete=data_complete,
    )


# ============================================================================
# Rule tests (one per rule)
# ============================================================================

class TestRule1LowConfidence:
    def test_escalates_when_confidence_below_threshold(self):
        """
        Rule 1: confidence below 0.65 must trigger escalation with reason
        'low_confidence'. This matters because an uncertain AI answer is worse
        than no answer — it erodes customer trust if it's wrong.
        """
        ctx = _make_context()
        escalate, reason = should_escalate(ctx, confidence_score=0.60,
                                           sentiment_score=0.0, intent="billing_query")
        assert escalate is True
        assert reason == "low_confidence"

    def test_no_escalation_at_boundary_confidence(self):
        """
        Rule 1 boundary: confidence exactly 0.65 should NOT escalate.
        The rule is confidence < 0.65 (strict), so 0.65 must pass through.
        """
        ctx = _make_context()
        escalate, reason = should_escalate(ctx, confidence_score=0.65,
                                           sentiment_score=0.0, intent="billing_query")
        assert escalate is False
        assert reason == "ai_can_handle"


class TestRule2AngrySentiment:
    def test_escalates_on_very_negative_sentiment(self):
        """
        Rule 2: sentiment < -0.6 should escalate with reason 'angry_customer'.
        Human agents are far more effective at de-escalating emotionally charged
        customers — an AI doubling down on process only makes things worse.
        """
        ctx = _make_context()
        escalate, reason = should_escalate(ctx, confidence_score=0.90,
                                           sentiment_score=-0.8, intent="data_usage")
        assert escalate is True
        assert reason == "angry_customer"


class TestRule3RepeatComplaint:
    def test_escalates_on_three_or_more_same_intent(self):
        """
        Rule 3: same intent appearing 3+ times in ticket history triggers
        escalation with reason 'repeat_complaint'. Repeated complaints mean the
        automated resolutions were not actually fixing the underlying problem —
        a human needs to investigate.
        """
        ctx = _make_context(ticket_intents=[
            "internet_outage", "billing_query", "internet_outage",
            "internet_outage", "sim_swap",
        ])
        escalate, reason = should_escalate(ctx, confidence_score=0.80,
                                           sentiment_score=0.0, intent="internet_outage")
        assert escalate is True
        assert reason == "repeat_complaint"

    def test_no_escalation_with_two_same_intent_tickets(self):
        """
        Rule 3 boundary: exactly 2 occurrences of the same intent should NOT
        trigger escalation — the threshold is 3 or more.
        """
        ctx = _make_context(ticket_intents=[
            "internet_outage", "billing_query", "internet_outage",
            "sim_swap", "roaming",
        ])
        escalate, reason = should_escalate(ctx, confidence_score=0.80,
                                           sentiment_score=0.0, intent="internet_outage")
        assert escalate is False


class TestRule4ServiceCancellation:
    def test_always_escalates_service_cancellation(self):
        """
        Rule 4: intent == 'service_cancellation' always escalates, even when
        confidence is high and sentiment is neutral. Retention conversations
        require human empathy and authorisation to make offers the AI cannot.
        """
        ctx = _make_context()
        escalate, reason = should_escalate(ctx, confidence_score=0.95,
                                           sentiment_score=0.2,
                                           intent="service_cancellation")
        assert escalate is True
        assert reason == "service_cancellation"


class TestRule5VipOverdue:
    def test_escalates_vip_with_overdue_billing(self):
        """
        Rule 5: a VIP customer AND an overdue bill together signal high churn
        risk — escalate with 'vip_overdue_billing'. Account managers can offer
        payment plans or loyalty perks that the AI isn't empowered to give.
        """
        ctx = _make_context(is_vip=True, is_overdue=True)
        escalate, reason = should_escalate(ctx, confidence_score=0.85,
                                           sentiment_score=0.0, intent="billing_query")
        assert escalate is True
        assert reason == "vip_overdue_billing"

    def test_no_escalation_vip_without_overdue(self):
        """
        Rule 5 requires BOTH conditions. A VIP customer with a current
        (not overdue) account should be handled by AI normally — VIP status
        alone is not a reason to escalate.
        """
        ctx = _make_context(is_vip=True, is_overdue=False)
        escalate, reason = should_escalate(ctx, confidence_score=0.85,
                                           sentiment_score=0.0, intent="billing_query")
        assert escalate is False


class TestRule6IncompleteData:
    def test_escalates_when_data_incomplete_and_confidence_marginal(self):
        """
        Rule 6: if data fetching partially failed (data_complete=False) AND
        confidence < 0.80, escalate. The AI is making a decision with missing
        context — better to hand off than to make a wrong call.
        """
        ctx = _make_context(data_complete=False)
        escalate, reason = should_escalate(ctx, confidence_score=0.70,
                                           sentiment_score=0.0, intent="data_usage")
        assert escalate is True
        assert reason == "incomplete_data_low_confidence"


# ============================================================================
# Edge case tests
# ============================================================================

class TestEdgeCases:
    def test_service_cancellation_overrides_high_confidence(self):
        """
        Edge case: Rule 4 must fire even when confidence is 0.99 and sentiment
        is perfectly neutral. This validates that Rule 4 is a hard override
        evaluated before confidence checks — no high confidence score should
        let a cancellation intent slip through to the AI.
        """
        ctx = _make_context()
        escalate, reason = should_escalate(ctx, confidence_score=0.99,
                                           sentiment_score=0.5,
                                           intent="service_cancellation")
        assert escalate is True
        assert reason == "service_cancellation"

    def test_no_escalation_all_clear(self):
        """
        Edge case / happy path: when all metrics are healthy no rule should
        fire and the AI should be allowed to handle the interaction. This test
        ensures the engine doesn't over-escalate and waste agent time.
        """
        ctx = _make_context(
            is_vip=False,
            is_overdue=False,
            data_complete=True,
            ticket_intents=["billing_query", "data_usage", "roaming", "coverage", "slow_speed"],
        )
        escalate, reason = should_escalate(
            ctx,
            confidence_score=0.92,
            sentiment_score=0.1,
            intent="coverage",
        )
        assert escalate is False
        assert reason == "ai_can_handle"
