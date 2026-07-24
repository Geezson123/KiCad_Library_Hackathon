"""Turn Mouser's raw part data into a draft library entry, using Claude.

The division of labour matters. Mouser is the source of truth for anything factual --
MPN, manufacturer, datasheet URL, description -- and those are copied across verbatim,
never sent to a model to be paraphrased. Claude is asked only to do the judgement work
that has no authoritative answer: which of *our* categories this belongs in, what
keywords a colleague would search for, and which footprint already in the library fits.

Everything it produces is a **draft**. The caller renders it into the upload form for a
human to review; nothing reaches the shared library until someone submits that form. A
wrong footprint is a scrapped board, so this stays a suggestion.
"""
import json

import config

MODEL = "claude-opus-4-8"

# Small, well-scoped classification -- `medium` gets the same answer as `high` here at
# a fraction of the tokens. Raise it if footprint matching starts looking sloppy.
EFFORT = "medium"

SYSTEM = """You help a university electronics lab file parts into their shared KiCad \
library. You are given factual data about a component from Mouser's catalogue, the \
categories this lab uses, and the footprints already in their library.

Your job is judgement, not facts:
- Pick the single best category from the lab's list.
- Write search keywords a lab member would actually type to find this part.
- Extract the component's value if it has a conventional one (10K, 100nF, 16MHz). \
Leave it empty for parts where a "value" is meaningless, like a microcontroller.
- Suggest a footprint ONLY from the provided list, and only when you are confident the \
package genuinely matches. Return null otherwise. A wrong footprint means a scrapped \
board, so a null is much better than a guess.

Be concise in your notes. State any real uncertainty plainly."""

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "description": "One of the lab's categories."},
        "keywords": {
            "type": "string",
            "description": "Space-separated lowercase search terms.",
        },
        "value": {
            "type": "string",
            "description": "Component value, or empty string if not applicable.",
        },
        "suggested_footprint": {
            "type": ["string", "null"],
            "description": "A footprint name from the provided list, or null.",
        },
        "notes": {
            "type": "string",
            "description": "One or two sentences: what you inferred and any doubts.",
        },
    },
    "required": ["category", "keywords", "value", "suggested_footprint", "notes"],
    "additionalProperties": False,
}


RECEIPT_SYSTEM = """You read Mouser order confirmations and invoices and extract the \
line items.

For each ordered line, return the manufacturer part number, the Mouser part number, \
and the quantity actually ordered. Use the manufacturer part number exactly as printed \
- it is what the lab matches against, so do not normalise, expand, or tidy it.

Ignore shipping, tax, handling, and discount lines: they are not stock. If the \
document is not a Mouser order at all, return an empty items list and say so in notes.

Quantities are integers. If a line's quantity is genuinely unreadable, omit that line \
and mention it in notes rather than guessing a number."""

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "order_number": {
            "type": "string",
            "description": "Mouser web order number, or empty if not shown.",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mpn": {"type": "string", "description": "Manufacturer part number."},
                    "mouser_pn": {"type": "string", "description": "Mouser part number."},
                    "description": {"type": "string"},
                    "quantity": {"type": "integer", "description": "Units ordered."},
                },
                "required": ["mpn", "mouser_pn", "description", "quantity"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "Anything unreadable, ambiguous, or skipped.",
        },
    },
    "required": ["order_number", "items", "notes"],
    "additionalProperties": False,
}


def configured():
    """Whether an API key is available. Enrichment is optional throughout."""
    return bool(config.ANTHROPIC_API_KEY)


def _client():
    """Construct the SDK client, or None if it is unavailable."""
    if not configured():
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


class ReceiptError(Exception):
    """Receipt parsing failed; the message is user-facing."""


def read_receipt(pdf_bytes=None, text=None):
    """Extract order line items from a Mouser receipt.

    Takes either a PDF (sent to Claude as a native document block -- no PDF library
    needed here) or pasted text. Returns ``{order_number, items, notes}``.

    Raises ReceiptError rather than degrading: unlike part enrichment, there is no
    useful fallback for "read this document", and silently returning zero line items
    would look like a receipt with nothing on it.
    """
    client = _client()
    if client is None:
        raise ReceiptError(
            "Receipt reading needs Claude. Set ANTHROPIC_API_KEY on the server "
            "(and pip install -r server/requirements.txt)."
        )

    if pdf_bytes:
        import base64
        content = [
            # The document block goes before the text block -- that ordering is what
            # the API expects for document questions.
            {"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
            }},
            {"type": "text", "text": "Extract the ordered line items from this Mouser order."},
        ]
    elif (text or "").strip():
        content = [{"type": "text",
                    "text": "Extract the ordered line items from this Mouser order:\n\n"
                            + text}]
    else:
        raise ReceiptError("Attach a PDF or paste the order text.")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=RECEIPT_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": RECEIPT_SCHEMA},
            },
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # noqa: BLE001
        raise ReceiptError(f"Could not read the receipt: {exc}")

    if response.stop_reason == "refusal":
        raise ReceiptError("The model declined to read that document.")

    raw = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise ReceiptError("The model returned something unparseable.")

    # Drop anything without a usable MPN or a positive quantity. The schema cannot
    # express "quantity must be at least 1", and a zero-quantity line is not stock.
    items = [
        {
            "mpn": (item.get("mpn") or "").strip(),
            "mouser_pn": (item.get("mouser_pn") or "").strip(),
            "description": (item.get("description") or "").strip(),
            "quantity": int(item.get("quantity") or 0),
        }
        for item in parsed.get("items", [])
        if (item.get("mpn") or "").strip() and int(item.get("quantity") or 0) > 0
    ]
    return {
        "order_number": (parsed.get("order_number") or "").strip(),
        "items": items,
        "notes": (parsed.get("notes") or "").strip(),
    }


def _fallback(part, categories, reason):
    """A usable draft with no model involved -- Mouser facts plus obvious defaults."""
    category = ""
    haystack = f"{part.get('mouser_category', '')} {part.get('description', '')}".lower()
    for candidate in categories:
        if candidate.lower() in haystack:
            category = candidate
            break
    return {
        "category": category,
        "keywords": "",
        "value": "",
        "suggested_footprint": None,
        "notes": reason,
        "ai_used": False,
    }


def enrich(part, categories, footprints):
    """Draft the judgement-call fields for a Mouser part.

    ``part`` is a normalized dict from mouser.normalize(). ``categories`` and
    ``footprints`` scope the model to values that actually exist in this library.

    Never raises: if the key is missing, the SDK is not installed, or the call fails,
    it returns a fallback draft with ``ai_used: False`` and an explanation in
    ``notes``. Ingest is more useful degraded than broken.
    """
    if not configured():
        return _fallback(part, categories,
                         "AI enrichment is off (no ANTHROPIC_API_KEY set) — "
                         "category and keywords are yours to fill in.")
    try:
        import anthropic
    except ImportError:
        return _fallback(part, categories,
                         "The anthropic package is not installed on the server — "
                         "run pip install -r server/requirements.txt.")

    facts = {
        "mpn": part.get("mpn", ""),
        "manufacturer": part.get("manufacturer", ""),
        "description": part.get("description", ""),
        "mouser_category": part.get("mouser_category", ""),
        "attributes": part.get("attributes", {}),
    }
    prompt = (
        f"Component data from Mouser:\n{json.dumps(facts, indent=2)}\n\n"
        f"The lab's categories:\n{json.dumps(categories)}\n\n"
        f"Footprints already in the library:\n{json.dumps(footprints)}\n\n"
        "Draft the category, keywords, value, and footprint suggestion."
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001 - degrade rather than break the upload
        return _fallback(part, categories, f"AI enrichment failed ({exc}).")

    if response.stop_reason == "refusal":
        return _fallback(part, categories, "The model declined to answer for this part.")

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        draft = json.loads(text)
    except ValueError:
        return _fallback(part, categories, "The model returned something unparseable.")

    # Constrain the result to values that exist here. The schema asks for these, but
    # the library is the authority on what is real -- a hallucinated footprint name
    # would sail through JSON validation and land a broken reference in the database.
    if draft.get("category") not in categories:
        draft["category"] = ""
    if draft.get("suggested_footprint") not in footprints:
        draft["suggested_footprint"] = None

    draft["ai_used"] = True
    return draft
