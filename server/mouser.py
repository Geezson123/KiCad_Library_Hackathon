"""Look up a part on Mouser from a product URL.

The user pastes a Mouser link; we pull the part number out of it and ask the Mouser
Search API for structured data. We deliberately do **not** fetch the URL the user gave
us -- only the part number is extracted from it, and the request goes to the Mouser API
host we control. Fetching an arbitrary user-supplied URL server-side is an SSRF, and
scraping the product page would be both fragile and against Mouser's terms; the API
returns better data anyway.

Get a free API key at https://www.mouser.com/api-hub/ and set LUGROUPLIB_MOUSER_KEY.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import config

API_URL = "https://api.mouser.com/api/v1/search/partnumber"

# Hosts we accept a product link from.
_MOUSER_HOSTS = {"mouser.com", "www.mouser.com", "eu.mouser.com", "www2.mouser.com"}

# /ProductDetail/<Manufacturer>/<PartNumber> or /ProductDetail/<MouserPartNumber>
_PRODUCT_PATH_RE = re.compile(r"/ProductDetail/(?P<rest>[^?#]+)", re.I)


class MouserError(Exception):
    """Something went wrong looking the part up; the message is user-facing."""


def parse_part_number(url):
    """Pull the part number out of a Mouser product URL.

    Accepts a bare part number too, so someone can paste either. Raises MouserError
    for anything that isn't a Mouser link, rather than silently fetching it.
    """
    text = (url or "").strip()
    if not text:
        raise MouserError("Paste a Mouser product link or a part number.")

    # A bare part number (no scheme, no slashes) is taken at face value.
    if "/" not in text and " " not in text:
        return text

    parsed = urllib.parse.urlparse(text if "//" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if host not in _MOUSER_HOSTS:
        raise MouserError(
            f"That is not a Mouser link (host: {host or 'unknown'}). Paste a "
            "mouser.com product URL, or just the part number."
        )

    match = _PRODUCT_PATH_RE.search(parsed.path)
    if not match:
        raise MouserError(
            "Could not find a part number in that link. It should look like "
            "https://www.mouser.com/ProductDetail/Yageo/RC0603FR-0710KL"
        )
    # Last path segment is the part number; anything before it is the manufacturer.
    segments = [s for s in match.group("rest").split("/") if s]
    return urllib.parse.unquote(segments[-1])


def configured():
    return bool(config.MOUSER_API_KEY)


def _post(part_number, timeout):
    body = json.dumps({
        "SearchByPartRequest": {
            "mouserPartNumber": part_number,
            "partSearchOptions": "Exact",
        }
    }).encode("utf-8")
    url = API_URL + "?" + urllib.parse.urlencode({"apiKey": config.MOUSER_API_KEY})
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MouserError(f"Mouser API returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise MouserError(f"Could not reach the Mouser API: {exc.reason}")
    except ValueError:
        raise MouserError("Mouser API returned a response we could not read.")


def _first_price(part):
    """Cheapest listed unit price, as a display string."""
    breaks = part.get("PriceBreaks") or []
    if not breaks:
        return ""
    first = breaks[0]
    return f"{first.get('Price', '')} @ {first.get('Quantity', '?')}+".strip()


def _attributes(part):
    """ProductAttributes as a flat {name: value} dict."""
    out = {}
    for attr in part.get("ProductAttributes") or []:
        name, value = attr.get("AttributeName"), attr.get("AttributeValue")
        if name and value:
            out[name] = value
    return out


def normalize(payload):
    """Turn a Mouser API response into the flat dict the rest of the app uses.

    Field access is deliberately tolerant: Mouser omits keys for parts where a value
    is unknown, and a missing datasheet should not fail the whole lookup.
    """
    errors = payload.get("Errors") or []
    if errors:
        message = errors[0].get("Message") or "unknown error"
        raise MouserError(f"Mouser rejected the lookup: {message}")

    parts = ((payload.get("SearchResults") or {}).get("Parts")) or []
    if not parts:
        raise MouserError("Mouser has no part with that number.")

    part = parts[0]
    return {
        "mpn": part.get("ManufacturerPartNumber") or "",
        "manufacturer": part.get("Manufacturer") or "",
        "description": part.get("Description") or "",
        "datasheet": part.get("DataSheetUrl") or "",
        "mouser_category": part.get("Category") or "",
        "mouser_pn": part.get("MouserPartNumber") or "",
        "product_url": part.get("ProductDetailUrl") or "",
        "availability": part.get("Availability") or "",
        "price": _first_price(part),
        "attributes": _attributes(part),
    }


def lookup(url_or_part, timeout=20):
    """Resolve a Mouser link (or bare part number) to normalized part data."""
    if not configured():
        raise MouserError(
            "Mouser lookup is not configured. Get a free API key at "
            "mouser.com/api-hub and set LUGROUPLIB_MOUSER_KEY on the server."
        )
    part_number = parse_part_number(url_or_part)
    return normalize(_post(part_number, timeout))
