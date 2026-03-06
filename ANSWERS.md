# ANSWERS.md — NexusAI Intern Challenge Task 5

---

## Q1: Partial STT Transcripts — Query Now or Wait?

**Recommendation: Start lightweight DB lookups on partial transcripts at ~600–800ms of audio, but defer heavy AI processing until the transcript is stable.**

The core tradeoff is latency vs. accuracy. Partial STT output changes word-by-word; acting on "I want to cancel my sub—" could misclassify the intent and pull irrelevant context. However, customer records take 200–400ms to fetch, so fetching too late adds unnecessary delay.

My approach uses a tiered strategy:

1. **After ~600ms of audio** — the customer has likely said their name or account reference. Trigger `fetch_crm()` and `fetch_tickets()` in parallel using the phone number (already known from call setup), not the transcript. These lookups are intent-agnostic and always useful.
2. **At transcript stability** (silence > 300ms or full sentence detected) — classify intent and fetch billing or contextual data.
3. **AI response generation** — only after a sufficiently complete transcript.

This way, backend data arrives *before* the AI needs it, eliminating stacked latency without wasting queries on half-formed sentences. The key mitigation for false-start queries is using the phone number as the primary key, not the volatile partial text.

---

## Q2: Two Failure Modes of the Auto-Knowledge-Base (CSAT ≥ 4)

**Failure Mode 1 — Survivorship Bias Poisoning the KB**

Only satisfied customers leave CSAT scores. Frustrated customers who hung up, were never surveyed, or got a misleading solution that appeared to work (but failed two days later) are systematically excluded. Over six months, the KB accumulates responses that *sound* good and produce short-term satisfaction, but may be factually wrong, outdated (a pricing tier was retired), or only valid for a specific region. Prevention: add a 30-day re-survey signal — if the customer calls back within 30 days on the same intent, retroactively flag that KB entry for review even if it originally scored 4 or 5.

**Failure Mode 2 — Semantic Duplication and Contradiction**

With 24/7 traffic, hundreds of nearly identical resolutions get added independently. Over time the KB contains 12 slightly different answers to "how do I reset my password," some contradicting each other (different reset URLs from different time periods). The AI retrieves whichever one is closest by embedding similarity, leading to inconsistent responses. Prevention: before inserting a new KB entry, run a similarity check (cosine similarity > 0.88 threshold) against existing entries. If a near-duplicate exists, route to a human KB curator to merge or supersede rather than auto-insert.

---

## Q3: Customer Says — "4 Days No Internet, Called 3 Times, Your Company Is Useless, Cancel Right Now"

**Step-by-step AI behavior:**

1. **Signal detection** — Multiple triggers fire simultaneously: sentiment score ≈ −0.85 (Rule 2), "cancel" intent (Rule 4), and ticket history likely shows 3 internet-outage entries (Rule 3). The escalation engine evaluates Rule 4 first and returns `(True, "service_cancellation")` immediately.

2. **Data gathering (parallel)** — While detecting intent the system has already fetched CRM (account tier, VIP status), billing (overdue?), and last 5 tickets to hand to the human agent.

3. **AI acknowledgment response** — Before transferring, the AI says something empathetic and concrete, not a generic hold message:
   > *"I completely understand — 4 days without internet after reaching out 3 times is unacceptable, and I'm sorry we've let you down. I'm connecting you right now with a senior specialist who can fix this and discuss your options. You won't have to repeat your story."*

4. **Handoff payload to human agent:**
   - Customer: [name, account ID, VIP status, plan]
   - Incident: 4-day outage, ticket IDs from prior 3 calls
   - Sentiment: very negative (−0.85)
   - Intent: service_cancellation
   - Escalation trigger: Rule 4 (hard override)
   - Suggested actions: check open outage tickets, proactively offer credit/extension, retention offer if needed

5. **Human agent receives a pre-filled context card** — no cold transfer, no re-explaining from scratch.

---

## Q4: Single Most Important Improvement — Real-Time Intent Confidence Calibration

**What:** Add an online calibration layer that continuously adjusts the model's raw confidence scores using historical outcome data, so `confidence = 0.75` actually means "resolved correctly 75% of the time" — not whatever the model guessed.

**How to build it:** After each call, store `(intent, predicted_confidence, actual_outcome)`. Weekly, fit a lightweight isotonic regression (sklearn, ~10 lines) on the last 30 days of data, mapping raw model confidence → calibrated probability. Deploy as a fast lookup table applied post-inference before the escalation engine sees the score.

**Why it matters:** Currently Rule 1 and Rule 6 rely on raw model confidence, which is notoriously poorly calibrated on GPT-class models (systematically overconfident on rare intents). A model that says 0.70 for "SIM unlock requests" might only resolve them correctly 40% of the time. Without calibration, the escalation engine is making decisions on a broken input signal.

**Measurement:** Track *escalation rate per intent before and after calibration*. Success = escalation rate for historically-difficult intents rises by 10–15% (more correct escalations), while overall escalation rate stays flat or improves, and downstream CSAT improves for escalated calls (agents are only handling cases they genuinely need to handle).
