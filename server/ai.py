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


def configured():
    """Whether an API key is available. Enrichment is optional throughout."""
    return bool(config.ANTHROPIC_API_KEY)


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
