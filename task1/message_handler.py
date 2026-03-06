"""
Task 1 — AI Message Handler
Async function that processes customer messages and returns structured AI responses
for a telecom support system.

Uses Google Gemini (google-genai SDK) — same API pattern as the JS implementation.
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv          # pip install python-dotenv
load_dotenv()                           # reads .env from project root (ignored by git)

from google import genai                        # pip install google-genai
from google.genai import types
from google.genai.errors import ClientError     # covers rate-limit (429) errors

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise EnvironmentError(
        "GEMINI_API_KEY is not set.\n"
        "  PowerShell : $env:GEMINI_API_KEY = 'your-key'\n"
        "  bash/zsh   : export GEMINI_API_KEY='your-key'"
    )
GEMINI_MODEL    = "gemini-2.5-flash"
API_TIMEOUT_SECONDS     = 10
RATE_LIMIT_RETRY_DELAY  = 2   # seconds to wait before retrying after a 429


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class MessageResponse:
    response_text: str
    confidence: float                  # 0.0 – 1.0
    suggested_action: str
    channel_formatted_response: str
    error: Optional[str]               # None on success


# ---------------------------------------------------------------------------
# System prompt  (real prompting thought — not just "you are helpful")
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are ARIA, a senior telecom support specialist at NexusComm.
You have deep expertise in: mobile plan changes, internet outages, billing disputes,
roaming charges, SIM replacements, contract terms, and retention.

Your persona:
- Empathetic first — acknowledge frustration before diving into solutions
- Concise and clear — avoid jargon; use plain language
- Solution-focused — never say "I can't help" without offering an alternative path
- Never reveal you are an AI unless the customer directly asks

Channel rules:
- VOICE: response_text must be ≤ 2 sentences. No bullet points. TTS-friendly.
- CHAT / WHATSAPP: full explanation allowed; use bullet points for step-by-step guidance.

Confidence scoring guide:
  0.90–1.00 → standard FAQ / known resolution
  0.70–0.89 → likely correct, may need verification
  0.50–0.69 → partial info, consider escalation
  below 0.50 → escalate immediately

Suggested action must be exactly one of:
  resolve | escalate_billing | escalate_technical | escalate_manager |
  send_sms_link | schedule_callback

Always reply with ONLY a valid JSON object — no markdown, no prose — with exactly:
{
  "response_text": "<your reply to the customer>",
  "confidence": <float 0.0–1.0>,
  "suggested_action": "<one of the six actions above>"
}"""


# ---------------------------------------------------------------------------
# Channel formatter
# ---------------------------------------------------------------------------

def _format_for_channel(text: str, channel: str) -> str:
    """Apply channel-specific formatting to the response text."""
    if channel == "voice":
        # Strip markdown — clean output for TTS engines
        text = re.sub(r"\*+", "", text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        return text.strip()
    # whatsapp & chat: pass through (both support basic markdown)
    return text.strip()


def _strip_json_fence(raw: str) -> str:
    """Remove ```json … ``` fences if the model adds them despite instructions."""
    raw = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*",     "", raw)
    return raw.strip()


# ---------------------------------------------------------------------------
# Core async handler
# ---------------------------------------------------------------------------

async def handle_message(
    customer_message: str,
    customer_id: str,
    channel: str,           # "voice" | "whatsapp" | "chat"
) -> MessageResponse:
    """
    Process a customer message via Gemini and return a structured response.

    Error cases handled:
        (a) API timeout after 10 seconds
        (b) API rate limit (HTTP 429) — retry once after 2 seconds
        (c) Empty or whitespace-only input — returns error WITHOUT calling API
    """

    # ── Guard (c): empty / whitespace input ─────────────────────────────────
    if not customer_message or not customer_message.strip():
        return MessageResponse(
            response_text="",
            confidence=0.0,
            suggested_action="resolve",
            channel_formatted_response="",
            error="empty_input: customer message was empty or whitespace-only",
        )

    # ── Channel validation ───────────────────────────────────────────────────
    valid_channels = {"voice", "whatsapp", "chat"}
    if channel not in valid_channels:
        return MessageResponse(
            response_text="",
            confidence=0.0,
            suggested_action="resolve",
            channel_formatted_response="",
            error=f"invalid_channel: '{channel}' must be one of {valid_channels}",
        )

    # ── Build user-turn prompt ───────────────────────────────────────────────
    channel_hint = (
        "[VOICE — reply in 2 sentences max, no bullet points]"
        if channel == "voice"
        else "[CHAT/WHATSAPP — detailed reply with bullet points allowed]"
    )
    user_turn = (
        f"{channel_hint}\n"
        f"Customer ID: {customer_id}\n"
        f"Customer message: {customer_message}"
    )

    # ── Gemini client (stateless — matches JS pattern) ───────────────────────
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

    async def _call_gemini() -> dict:
        """Single async Gemini call with timeout guard."""
        response = await asyncio.wait_for(
            asyncio.to_thread(                  # run sync SDK call in thread pool
                ai_client.models.generate_content,
                model=GEMINI_MODEL,
                contents=user_turn,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            ),
            timeout=API_TIMEOUT_SECONDS,
        )

        # Extract raw text (mirrors JS: response.text() fallback chain)
        if hasattr(response, "text") and callable(response.text):
            raw = response.text()
        elif hasattr(response, "text") and isinstance(response.text, str):
            raw = response.text
        elif response.candidates:
            raw = response.candidates[0].content.parts[0].text
        else:
            raise ValueError(
                "Unexpected Gemini response shape: " + str(type(response))
            )

        return json.loads(_strip_json_fence(raw))

    # ── Attempt with rate-limit retry ────────────────────────────────────────
    try:
        data = await _call_gemini()

    except asyncio.TimeoutError:
        # (a) Timeout
        return MessageResponse(
            response_text="",
            confidence=0.0,
            suggested_action="schedule_callback",
            channel_formatted_response="",
            error="api_timeout: Gemini did not respond within 10 seconds",
        )

    except ClientError as exc:
        # (b) Rate limit → retry once after 2 s
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
            try:
                data = await _call_gemini()
            except asyncio.TimeoutError:
                return MessageResponse(
                    response_text="",
                    confidence=0.0,
                    suggested_action="schedule_callback",
                    channel_formatted_response="",
                    error="api_timeout_after_retry: timed out on rate-limit retry",
                )
            except Exception as retry_exc:
                return MessageResponse(
                    response_text="",
                    confidence=0.0,
                    suggested_action="escalate_manager",
                    channel_formatted_response="",
                    error=f"api_error_after_retry: {type(retry_exc).__name__}: {retry_exc}",
                )
        else:
            return MessageResponse(
                response_text="",
                confidence=0.0,
                suggested_action="escalate_manager",
                channel_formatted_response="",
                error=f"gemini_client_error: {exc}",
            )

    except Exception as exc:
        return MessageResponse(
            response_text="",
            confidence=0.0,
            suggested_action="escalate_manager",
            channel_formatted_response="",
            error=f"api_error: {type(exc).__name__}: {exc}",
        )

    # ── Assemble final response ───────────────────────────────────────────────
    response_text    = data.get("response_text", "")
    confidence       = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    suggested_action = data.get("suggested_action", "resolve")
    channel_fmt      = _format_for_channel(response_text, channel)

    return MessageResponse(
        response_text=response_text,
        confidence=confidence,
        suggested_action=suggested_action,
        channel_formatted_response=channel_fmt,
        error=None,
    )


# ---------------------------------------------------------------------------
# Quick demo (python task1/message_handler.py)
# ---------------------------------------------------------------------------

async def _demo():
    test_cases = [
        ("My internet has been down for 2 days!",           "C001", "voice"),
        ("I was charged twice this month, check billing.",   "C002", "chat"),
        ("   ",                                              "C003", "whatsapp"),   # empty
        ("I want to cancel my plan right now.",              "C004", "whatsapp"),
    ]
    for msg, cid, ch in test_cases:
        print(f"\n{'='*55}")
        print(f"[{ch.upper()}] Customer {cid}")
        print(f"Input : {repr(msg)}")
        result = await handle_message(msg, cid, ch)
        if result.error:
            print(f"ERROR : {result.error}")
        else:
            print(f"Reply : {result.response_text}")
            print(f"Conf  : {result.confidence:.2f}")
            print(f"Action: {result.suggested_action}")
            print(f"Fmtd  : {result.channel_formatted_response}")


if __name__ == "__main__":
    asyncio.run(_demo())
