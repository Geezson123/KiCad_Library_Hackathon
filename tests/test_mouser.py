#!/usr/bin/env python3
"""Stage 6: Mouser ingest — URL parsing, response normalization, AI enrichment
guardrails, and the review-before-commit flow.

Both network calls are stubbed. No test here talks to Mouser or to Claude: the point
is the glue and the guardrails, not their APIs.
"""
import sys
import types

from harness import check, finish, make_client, section, setup

webapp, config, db = setup()

import ai        # noqa: E402
import library   # noqa: E402
import mouser    # noqa: E402


def client():
    return make_client(webapp)


def sign_in(c, name="Ingest Tester"):
    c.post("/dev-login", data={"name": name}, follow_redirects=True)


# A recorded-shape Mouser response (field names per their Search API).
MOUSER_RESPONSE = {
    "Errors": [],
    "SearchResults": {
        "NumberOfResult": 1,
        "Parts": [{
            "ManufacturerPartNumber": "RC0603FR-0710KL",
            "Manufacturer": "YAGEO",
            "Description": "Thick Film Resistors - SMD 10 kOhms 1% 0603",
            "DataSheetUrl": "https://example.com/rc0603.pdf",
            "Category": "Thick Film Resistors - SMD",
            "MouserPartNumber": "603-RC0603FR-0710KL",
            "ProductDetailUrl": "https://www.mouser.com/ProductDetail/603-RC0603FR-0710KL",
            "Availability": "12500 In Stock",
            "PriceBreaks": [{"Quantity": 1, "Price": "$0.10", "Currency": "USD"}],
            "ProductAttributes": [
                {"AttributeName": "Package / Case", "AttributeValue": "0603"},
                {"AttributeName": "Resistance", "AttributeValue": "10 kOhms"},
            ],
        }],
    },
}

section("URL parsing")
check("manufacturer/part URL",
      mouser.parse_part_number(
          "https://www.mouser.com/ProductDetail/Yageo/RC0603FR-0710KL"
      ) == "RC0603FR-0710KL")
check("query string ignored",
      mouser.parse_part_number(
          "https://www.mouser.com/ProductDetail/Yageo/RC0603FR-0710KL?qs=abc%2Fdef"
      ) == "RC0603FR-0710KL")
check("single-segment (Mouser P/N) URL",
      mouser.parse_part_number(
          "https://www.mouser.com/ProductDetail/603-RC0603FR-0710KL"
      ) == "603-RC0603FR-0710KL")
check("regional host accepted",
      mouser.parse_part_number(
          "https://eu.mouser.com/ProductDetail/Yageo/RC0603FR-0710KL"
      ) == "RC0603FR-0710KL")
check("bare part number passes through",
      mouser.parse_part_number("RC0603FR-0710KL") == "RC0603FR-0710KL")
check("percent-encoding decoded",
      mouser.parse_part_number(
          "https://www.mouser.com/ProductDetail/TE/1-2380668-0%2FX"
      ) == "1-2380668-0/X")

for bad, label in [
    ("https://evil.example.com/ProductDetail/Yageo/RC0603", "non-Mouser host refused"),
    ("https://mouser.com.evil.example/ProductDetail/x", "lookalike host refused"),
    ("https://www.mouser.com/c/passive-components/", "non-product Mouser URL refused"),
    ("", "empty input refused"),
]:
    try:
        mouser.parse_part_number(bad)
        blocked = False
    except mouser.MouserError:
        blocked = True
    check(label, blocked, bad)

section("response normalization")
part = mouser.normalize(MOUSER_RESPONSE)
check("MPN", part["mpn"] == "RC0603FR-0710KL", part["mpn"])
check("manufacturer", part["manufacturer"] == "YAGEO")
check("datasheet", part["datasheet"] == "https://example.com/rc0603.pdf")
check("Mouser P/N", part["mouser_pn"] == "603-RC0603FR-0710KL")
check("availability", part["availability"] == "12500 In Stock")
check("price break formatted", "$0.10" in part["price"], part["price"])
check("attributes flattened",
      part["attributes"]["Package / Case"] == "0603", part["attributes"])

for payload, label in [
    ({"Errors": [{"Message": "Invalid API key"}]}, "API error surfaced"),
    ({"Errors": [], "SearchResults": {"Parts": []}}, "no results surfaced"),
]:
    try:
        mouser.normalize(payload)
        raised = False
    except mouser.MouserError:
        raised = True
    check(label, raised)

section("missing configuration degrades, never crashes")
config.MOUSER_API_KEY = ""
try:
    mouser.lookup("RC0603FR-0710KL")
    raised = False
except mouser.MouserError as exc:
    raised = "api-hub" in str(exc)
check("unconfigured lookup explains how to fix it", raised)

config.ANTHROPIC_API_KEY = ""
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("enrichment falls back with no key", draft["ai_used"] is False, draft)
check("fallback still guesses a category from Mouser's",
      draft["category"] == "Resistor", draft["category"])
check("fallback suggests no footprint", draft["suggested_footprint"] is None)
check("fallback explains itself", "ANTHROPIC_API_KEY" in draft["notes"], draft["notes"])

section("AI output is constrained to what exists here")


def fake_anthropic(payload_text, stop_reason="end_turn", model="stub-model"):
    """Inject a stand-in `anthropic` module so enrich() takes the model path.

    Returns a dict that captures the kwargs of the last request, so tests can assert
    on the parameters actually sent rather than only on the parsed result.
    """
    block = types.SimpleNamespace(type="text", text=payload_text)
    response = types.SimpleNamespace(content=[block], stop_reason=stop_reason,
                                     model=model)
    captured = {}

    def create(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return response

    module = types.ModuleType("anthropic")
    module.Anthropic = lambda **kw: types.SimpleNamespace(
        messages=types.SimpleNamespace(create=create))
    sys.modules["anthropic"] = module
    return captured


config.ANTHROPIC_API_KEY = "test-key"
fake_anthropic('{"category": "Resistor", "keywords": "resistor 10k 0603",'
               ' "value": "10K", "suggested_footprint": "R_0603", "notes": "ok"}')
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("valid draft passes through", draft["ai_used"] is True, draft)
check("category kept", draft["category"] == "Resistor")
check("footprint kept", draft["suggested_footprint"] == "R_0603")

# The schema can't stop the model inventing a plausible-looking footprint name, so
# enrich() checks the answer against the real library before returning it.
fake_anthropic('{"category": "Frobnicator", "keywords": "x", "value": "",'
               ' "suggested_footprint": "R_0402_INVENTED", "notes": "n"}')
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("invented category dropped", draft["category"] == "", draft["category"])
check("invented footprint dropped", draft["suggested_footprint"] is None, draft)

fake_anthropic("this is not json")
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("unparseable output degrades", draft["ai_used"] is False, draft)

fake_anthropic("{}", stop_reason="refusal")
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("a refusal degrades", draft["ai_used"] is False, draft)
check("refusal is explained", "declined" in draft["notes"], draft["notes"])

section("model is configurable, and parameters adapt to it")
VALID = ('{"category": "Resistor", "keywords": "k", "value": "",'
         ' "suggested_footprint": null, "notes": "n"}')
_saved_model, _saved_effort = config.AI_MODEL, config.AI_EFFORT

# Adaptive-thinking models: thinking + effort together.
for model in ("claude-opus-4-8", "claude-sonnet-5", "claude-opus-4-6"):
    config.AI_MODEL = model
    captured = fake_anthropic(VALID)
    ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
    check(f"{model}: configured model is the one requested",
          captured.get("model") == model, captured.get("model"))
    check(f"{model}: adaptive thinking",
          captured.get("thinking") == {"type": "adaptive"}, captured.get("thinking"))
    check(f"{model}: effort sent",
          captured["output_config"].get("effort") == config.AI_EFFORT,
          captured["output_config"])

# Haiku rejects `effort` and needs the older budget_tokens form — a bare model-string
# swap would 400 here, which is the whole reason profiles exist.
config.AI_MODEL = "claude-haiku-4-5"
captured = fake_anthropic(VALID)
ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("haiku: budget_tokens form, not adaptive",
      captured["thinking"] == {"type": "enabled", "budget_tokens": ai.THINKING_BUDGET},
      captured["thinking"])
check("haiku: effort omitted (it is rejected)",
      "effort" not in captured["output_config"], captured["output_config"])
check("haiku: budget is below max_tokens",
      ai.THINKING_BUDGET < captured["max_tokens"])
check("haiku: budget is above the 1024 minimum", ai.THINKING_BUDGET >= 1024)

# Fable/Mythos: thinking is always on and sending the parameter at all is a 400.
config.AI_MODEL = "claude-fable-5"
captured = fake_anthropic(VALID)
ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("fable: thinking parameter omitted entirely",
      "thinking" not in captured, captured.get("thinking"))
check("fable: effort still sent", "effort" in captured["output_config"])

# An unknown name gets the modern shape rather than a silent wrong guess.
config.AI_MODEL = "claude-something-unreleased"
captured = fake_anthropic(VALID)
ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("unknown model falls back to the adaptive profile",
      captured.get("thinking") == {"type": "adaptive"}, captured.get("thinking"))

# Effort is configurable too.
config.AI_MODEL, config.AI_EFFORT = "claude-opus-4-8", "xhigh"
captured = fake_anthropic(VALID)
ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("effort comes from config",
      captured["output_config"]["effort"] == "xhigh", captured["output_config"])

# Structured output survives every profile — it is what the guardrails parse.
for model in ("claude-opus-4-8", "claude-haiku-4-5", "claude-fable-5"):
    config.AI_MODEL = model
    captured = fake_anthropic(VALID)
    ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
    fmt = captured["output_config"].get("format", {})
    check(f"{model}: json_schema output still requested",
          fmt.get("type") == "json_schema" and "schema" in fmt, fmt)

section("the model used is reported back")
config.AI_MODEL, config.AI_EFFORT = _saved_model, _saved_effort
fake_anthropic(VALID, model="claude-sonnet-5")
draft = ai.enrich(part, webapp.CATEGORIES, ["R_0603"])
check("draft names the model that produced it",
      draft["model"] == "claude-sonnet-5", draft.get("model"))
check("fallback drafts report no model", ai._fallback(part, [], "x")["model"] == "")

section("footprint list comes from the real library")
names = library.list_footprints()
check("returns the library's footprints", isinstance(names, list), names)
check("names carry no .kicad_mod suffix",
      all(not n.endswith(".kicad_mod") for n in names), names)

section("review before commit")
config.MOUSER_API_KEY = "test-key"
_real_lookup = mouser.lookup


def stub_lookup(url_or_part, timeout=20):
    """Stub only the HTTP call — real URL validation still runs, so the route's
    rejection path is exercised rather than stubbed away."""
    mouser.parse_part_number(url_or_part)
    return mouser.normalize(MOUSER_RESPONSE)


mouser.lookup = stub_lookup
fake_anthropic('{"category": "Resistor", "keywords": "resistor 10k",'
               ' "value": "10K", "suggested_footprint": null, "notes": "clear"}')

before = len(db.list_parts())
with client() as c:
    sign_in(c)
    r = c.get("/upload/from-mouser")
    check("the lookup page renders", r.status_code == 200 and b"Mouser" in r.data)

    r = c.post("/upload/from-mouser",
               data={"url": "https://www.mouser.com/ProductDetail/Yageo/RC0603FR-0710KL"},
               follow_redirects=True)
    check("lookup lands on the upload form", r.status_code == 200, r.status_code)
    body = r.data.decode()
    check("MPN prefilled", 'value="RC0603FR-0710KL"' in body)
    check("manufacturer prefilled", 'value="YAGEO"' in body)
    check("datasheet prefilled", "example.com/rc0603.pdf" in body)
    check("AI-derived fields are labelled", 'class="chip ai"' in body)
    check("stock shown for context", "12500 In Stock" in body)
    check("symbol still required", 'name="symbol"' in body and "required" in body)

check("NOTHING was written to the library", len(db.list_parts()) == before,
      f"{before} -> {len(db.list_parts())}")

with client() as c:
    sign_in(c)
    r = c.post("/upload/from-mouser", data={"url": "https://evil.example.com/x"},
               follow_redirects=True)
    check("a non-Mouser URL is refused in the UI too", b"not a Mouser link" in r.data)

mouser.lookup = _real_lookup

section("ingest requires sign-in")
with client() as c:
    r = c.get("/upload/from-mouser")
    check("anonymous users are redirected to login",
          r.status_code == 302 and "/login" in r.headers.get("Location", ""),
          r.status_code)

finish()
