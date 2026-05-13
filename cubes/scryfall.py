import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"


def fetch_card_by_name(card_name: str) -> dict[str, Any] | None:
    query = urlencode({"exact": card_name.strip()})
    request = Request(f"{SCRYFALL_NAMED_URL}?{query}", headers={"User-Agent": "popcorn-cube/0.1"})
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def is_card_legal_for_format(card_data: dict[str, Any], mtg_format: str) -> bool:
    if not mtg_format:
        return True
    legalities = card_data.get("legalities") or {}
    return legalities.get(mtg_format) == "legal"
