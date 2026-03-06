# NexusAI Intern Challenge

A five-task AI/backend engineering challenge demonstrating async Python, PostgreSQL schema design, concurrent I/O, rule-based decision engines, and system design thinking.

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-username/nexusai-intern-challenge.git
cd nexusai-intern-challenge

# 2. Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Task 1 — AI Message Handler

**File:** `task1/message_handler.py`

Set your OpenAI API key first:

```bash
# Windows PowerShell
$env:OPENAI_API_KEY = "sk-..."
```

Or edit the `OPENAI_API_KEY` constant directly in the file.

```bash
python task1/message_handler.py
```

Sample output:
```
--- [VOICE] Customer C001 ---
Input: 'My internet has been down for 2 days!'
Response: I'll escalate this to our tech team right away. You'll receive an update SMS within 2 hours.
Confidence: 0.88
Action: escalate_technical
Formatted: I'll escalate this to our tech team right away. You'll receive an update SMS within 2 hours.
```

**Design decisions:**
- System prompt positions ARIA as a telecom expert with clear persona, not just "helpful assistant"
- Prompts the model to output JSON with confidence and suggested_action fields
- Voice channel strips markdown for clean TTS output
- All errors (timeout, rate limit, empty input) return a valid `MessageResponse` with `error` populated — never raise exceptions to the caller

---

## Task 2 — Database Schema

**Files:** `task2/schema.sql`, `task2/repository.py`

### Apply the schema (requires a running PostgreSQL instance):

```bash
psql -U your_user -d nexusai -f task2/schema.sql
```

### Run the repository demo:

Configure `DATABASE_URL` in `task2/repository.py`, then:

```bash
python task2/repository.py
```

**Schema highlights:**
- `confidence_score NUMERIC(4,3)` — exact decimal, not FLOAT, for financial-grade precision
- `csat_score SMALLINT CHECK (1–5)` — enforced at DB level, no app-level bypass possible
- 3 indexes with documented rationale (customer lookup, time-range scans, intent analytics)
- `get_low_resolution_intents()` returns the 5 worst intents by resolution rate over the last 7 days

---

## Task 3 — Parallel Data Fetcher

**File:** `task3/fetcher.py`

```bash
python task3/fetcher.py
```

### Timing output (example run):

```
============================================================
SEQUENTIAL FETCH
============================================================
  CRM fetch done in 312 ms
  Billing fetch done in 278 ms
  Ticket history fetch done in 189 ms
  data_complete : True
  ⏱  Total time : 779 ms

============================================================
PARALLEL FETCH
============================================================
  CRM fetch done in 312 ms
  Billing fetch done in 278 ms
  Ticket history fetch done in 189 ms
  data_complete : True
  ⏱  Total time : 318 ms

  🚀 Speed-up   : 2.45× faster with parallel fetch
```

**Why it matters:** Real customer calls have a 6–8 second patience window. Sequential fetching (~700ms each source) would alone consume 2+ seconds before the AI can respond. Parallel fetching collapses this to the time of the slowest single source.

**Billing timeout handling:** `asyncio.gather(return_exceptions=True)` is used instead of the default behaviour. This means even if billing raises `TimeoutError`, CRM and ticket data are still returned. The `CustomerContext.data_complete` flag is set to `False` and a warning is logged — the interaction continues with whatever data is available.

---

## Task 4 — Escalation Decision Engine

**Files:** `task4/escalation.py`, `task4/test_escalation.py`

### Run the tests:

```bash
pytest task4/ -v
```

Expected output:
```
task4/test_escalation.py::TestRule1LowConfidence::test_escalates_when_confidence_below_threshold PASSED
task4/test_escalation.py::TestRule1LowConfidence::test_no_escalation_at_boundary_confidence PASSED
task4/test_escalation.py::TestRule2AngrySentiment::test_escalates_on_very_negative_sentiment PASSED
task4/test_escalation.py::TestRule3RepeatComplaint::test_escalates_on_three_or_more_same_intent PASSED
task4/test_escalation.py::TestRule3RepeatComplaint::test_no_escalation_with_two_same_intent_tickets PASSED
task4/test_escalation.py::TestRule4ServiceCancellation::test_always_escalates_service_cancellation PASSED
task4/test_escalation.py::TestRule5VipOverdue::test_escalates_vip_with_overdue_billing PASSED
task4/test_escalation.py::TestRule5VipOverdue::test_no_escalation_vip_without_overdue PASSED
task4/test_escalation.py::TestRule6IncompleteData::test_escalates_when_data_incomplete_and_confidence_marginal PASSED
task4/test_escalation.py::TestEdgeCases::test_service_cancellation_overrides_high_confidence PASSED
task4/test_escalation.py::TestEdgeCases::test_no_escalation_all_clear PASSED

11 passed in 0.12s
```

### Rule conflict resolution

When two rules appear to conflict, **Rule 4 (service_cancellation) always wins** because it is evaluated first and returns immediately — it is a hard business rule, not a signal. Example: confidence is 0.90 but intent is `service_cancellation`. Rule 4 fires before Rule 1 is even evaluated, and the result is escalation with reason `"service_cancellation"`. This is intentional: the confidence score reflects *how well the AI understood the question*, but it says nothing about whether the AI is *authorised* to handle a cancellation. That authority check is categorical, not probabilistic. In general, categorical hard rules (Rule 4) precede signal-based rules (Rules 1, 2), which precede compound-condition rules (Rules 3, 5, 6). When two signal rules both fire (e.g., confidence < 0.65 AND sentiment < -0.6), the first match in evaluation order wins — in this case "low_confidence" — but both conditions are logged in the handoff payload so the agent understands the full picture.

---

## Task 5 — Written Design Questions

See [`ANSWERS.md`](./ANSWERS.md) at the project root.

---

## Project Structure

```
nexusai-intern-challenge/
├── ANSWERS.md              # Task 5 design questions
├── README.md               # This file
├── requirements.txt
├── task1/
│   └── message_handler.py  # Async AI handler + MessageResponse dataclass
├── task2/
│   ├── schema.sql          # PostgreSQL CREATE TABLE + indexes + constraints
│   └── repository.py       # CallRecordRepository (asyncpg)
├── task3/
│   └── fetcher.py          # Parallel vs sequential fetch + CustomerContext
└── task4/
    ├── escalation.py       # should_escalate() — 6 rules
    └── test_escalation.py  # 8 pytest test cases
```
