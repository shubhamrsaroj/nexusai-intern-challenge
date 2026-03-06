"""
Task 3 — Parallel Data Fetcher
Demonstrates async parallelism for fetching customer data from multiple
backend systems simultaneously during an incoming call.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# CustomerContext dataclass
# ============================================================================

@dataclass
class CustomerContext:
    phone: str
    crm_data: Optional[dict]        = None   # None if fetch failed
    billing_data: Optional[dict]    = None
    ticket_data: Optional[dict]     = None
    data_complete: bool             = True   # False if ANY source failed
    fetch_time_ms: float            = 0.0
    warnings: list[str]             = field(default_factory=list)


# ============================================================================
# Mock data generators
# ============================================================================

def _make_crm_data(phone: str) -> dict:
    return {
        "phone": phone,
        "customer_id": f"CRM-{phone[-6:]}",
        "name": "Priya Sharma",
        "plan": "Nexus Unlimited Pro",
        "is_vip": random.choice([True, False]),
        "account_status": "active",
        "region": "South-Asia",
        "since": "2021-03-14",
    }


def _make_billing_data(phone: str) -> dict:
    return {
        "phone": phone,
        "current_balance": round(random.uniform(-500, 200), 2),
        "due_date": "2026-03-15",
        "is_overdue": random.choice([True, False]),
        "last_payment": "2026-02-20",
        "payment_method": "credit_card",
    }


def _make_ticket_data(phone: str) -> dict:
    intents = [
        "internet_outage",
        "billing_dispute",
        "slow_speed",
        "billing_dispute",   # duplicate to trigger Rule 3
        "internet_outage",
        "service_cancellation",
    ]
    sample = random.sample(intents, k=5)
    return {
        "phone": phone,
        "open_tickets": random.randint(0, 3),
        "last_5_complaints": [
            {"id": f"TK-{1000+i}", "intent": sample[i], "status": "closed"}
            for i in range(5)
        ],
    }


# ============================================================================
# Mock async fetch functions (simulate real network latency)
# ============================================================================

async def fetch_crm(phone: str) -> dict:
    """Simulate CRM API call — 200–400 ms latency."""
    delay = random.uniform(0.200, 0.400)
    await asyncio.sleep(delay)
    logger.info("CRM fetch done in %.0f ms", delay * 1000)
    return _make_crm_data(phone)


async def fetch_billing(phone: str) -> dict:
    """
    Simulate billing system call — 150–350 ms latency.
    Has a 10 % random chance of raising TimeoutError.
    """
    delay = random.uniform(0.150, 0.350)
    await asyncio.sleep(delay)

    if random.random() < 0.10:   # 10 % failure chance
        raise TimeoutError("Billing service timed out (simulated)")

    logger.info("Billing fetch done in %.0f ms", delay * 1000)
    return _make_billing_data(phone)


async def fetch_tickets(phone: str) -> dict:
    """Simulate ticket-history system call — 100–300 ms latency."""
    delay = random.uniform(0.100, 0.300)
    await asyncio.sleep(delay)
    logger.info("Ticket history fetch done in %.0f ms", delay * 1000)
    return _make_ticket_data(phone)


# ============================================================================
# Sequential fetcher
# ============================================================================

async def fetch_sequential(phone: str) -> CustomerContext:
    """
    Fetch all three data sources one after another.
    Total time ≈ sum of all three latencies.
    """
    ctx = CustomerContext(phone=phone)
    start = time.monotonic()

    ctx.crm_data = await fetch_crm(phone)

    try:
        ctx.billing_data = await fetch_billing(phone)
    except TimeoutError as exc:
        logger.warning("Sequential billing fetch failed: %s", exc)
        ctx.billing_data = None
        ctx.data_complete = False
        ctx.warnings.append(f"billing_timeout: {exc}")

    ctx.ticket_data = await fetch_tickets(phone)

    ctx.fetch_time_ms = (time.monotonic() - start) * 1000
    return ctx


# ============================================================================
# Parallel fetcher (uses asyncio.gather)
# ============================================================================

async def fetch_parallel(phone: str) -> CustomerContext:
    """
    Fetch all three data sources concurrently using asyncio.gather().
    Total time ≈ slowest single request (not the sum).

    Uses return_exceptions=True so a failure in one source does not
    crash the entire gather — the other sources still return normally.
    """
    ctx = CustomerContext(phone=phone)
    start = time.monotonic()

    results = await asyncio.gather(
        fetch_crm(phone),
        fetch_billing(phone),
        fetch_tickets(phone),
        return_exceptions=True,   # ← critical: prevents one failure from cancelling others
    )

    crm_result, billing_result, ticket_result = results

    # --- CRM ---
    if isinstance(crm_result, Exception):
        logger.warning("CRM fetch failed: %s", crm_result)
        ctx.crm_data = None
        ctx.data_complete = False
        ctx.warnings.append(f"crm_error: {crm_result}")
    else:
        ctx.crm_data = crm_result

    # --- Billing (10 % chance of TimeoutError) ---
    if isinstance(billing_result, Exception):
        logger.warning("Billing fetch failed: %s", billing_result)
        ctx.billing_data = None
        ctx.data_complete = False
        ctx.warnings.append(f"billing_timeout: {billing_result}")
    else:
        ctx.billing_data = billing_result

    # --- Tickets ---
    if isinstance(ticket_result, Exception):
        logger.warning("Ticket fetch failed: %s", ticket_result)
        ctx.ticket_data = None
        ctx.data_complete = False
        ctx.warnings.append(f"ticket_error: {ticket_result}")
    else:
        ctx.ticket_data = ticket_result

    ctx.fetch_time_ms = (time.monotonic() - start) * 1000
    return ctx


# ============================================================================
# Timing demo
# ============================================================================

async def _run_demo():
    phone = "+19005551234"

    print("\n" + "=" * 60)
    print("SEQUENTIAL FETCH")
    print("=" * 60)
    seq_ctx = await fetch_sequential(phone)
    print(f"  data_complete : {seq_ctx.data_complete}")
    print(f"  warnings      : {seq_ctx.warnings}")
    print(f"  Total time    : {seq_ctx.fetch_time_ms:.0f} ms")

    print("\n" + "=" * 60)
    print("PARALLEL FETCH")
    print("=" * 60)
    par_ctx = await fetch_parallel(phone)
    print(f"  data_complete : {par_ctx.data_complete}")
    print(f"  warnings      : {par_ctx.warnings}")
    print(f"  Total time    : {par_ctx.fetch_time_ms:.0f} ms")

    if par_ctx.fetch_time_ms > 0:
        speedup = seq_ctx.fetch_time_ms / par_ctx.fetch_time_ms
        print(f"\n  >> Speed-up   : {speedup:.2f}x faster with parallel fetch")

    print()


if __name__ == "__main__":
    asyncio.run(_run_demo())
