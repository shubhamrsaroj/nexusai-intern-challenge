-- =============================================================================
-- Task 2 — Database Schema: call_records
-- PostgreSQL table for storing every customer interaction
-- =============================================================================

CREATE TABLE IF NOT EXISTS call_records (
    id               BIGSERIAL        PRIMARY KEY,

    -- Customer identification
    customer_phone   VARCHAR(20)      NOT NULL,
    channel          VARCHAR(10)      NOT NULL
                         CHECK (channel IN ('voice', 'whatsapp', 'chat')),

    -- What was said and how AI responded
    transcript       TEXT             NOT NULL,
    ai_response      TEXT             NOT NULL,
    intent           VARCHAR(100),                        -- e.g. "billing_dispute"

    -- Outcome of the interaction
    outcome          VARCHAR(12)      NOT NULL
                         CHECK (outcome IN ('resolved', 'escalated', 'failed')),

    -- AI quality metrics
    confidence_score NUMERIC(4, 3)   NOT NULL
                         CHECK (confidence_score >= 0 AND confidence_score <= 1),

    -- Customer satisfaction (nullable — filled in post-call survey)
    csat_score       SMALLINT
                         CHECK (csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5)),

    -- Timing
    started_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    duration_seconds INTEGER         NOT NULL CHECK (duration_seconds >= 0),

    -- Agent who handled escalation (NULL if fully automated)
    agent_id         VARCHAR(50)
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- WHY: Most common query pattern is "show me all recent calls for this customer."
-- Without this index every  customer-lookup scans the full table, which becomes
-- extremely slow once millions of rows accumulate from 24/7 call-center traffic.
CREATE INDEX idx_call_records_customer_phone
    ON call_records (customer_phone, started_at DESC);

-- WHY: Operations teams run daily/weekly KPI dashboards filtered by time window
-- (e.g. "last 7 days"). A BRIN index is ideal for append-only timestamp columns
-- because rows are inserted in roughly chronological order, making the block
-- ranges very effective while adding almost no storage overhead.
CREATE INDEX idx_call_records_started_at_brin
    ON call_records USING BRIN (started_at);

-- WHY: Analysts and the escalation engine need to query by intent to track which
-- intent types have the worst resolution rates or CSAT. Without this index those
-- aggregation queries do a full sequential scan — unacceptable at production volume.
CREATE INDEX idx_call_records_intent_outcome
    ON call_records (intent, outcome)
    WHERE intent IS NOT NULL;

-- =============================================================================
-- Analytics view: intent resolution + CSAT (last 7 days)
-- Used by get_low_resolution_intents() in repository.py
-- =============================================================================
CREATE OR REPLACE VIEW vw_intent_resolution_7d AS
SELECT
    intent,
    COUNT(*)                                              AS total_calls,
    SUM(CASE WHEN outcome = 'resolved' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0)                            AS resolution_rate,
    AVG(csat_score)                                       AS avg_csat
FROM call_records
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND intent IS NOT NULL
GROUP BY intent;
