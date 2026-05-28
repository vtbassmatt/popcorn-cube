import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
SCRYFALL_CARD_URL = "https://api.scryfall.com/cards"
SCRYFALL_CARD_SEARCH_URL = f"{SCRYFALL_CARD_URL}/search"


def fetch_card_by_name(card_name: str) -> dict[str, Any] | None:
    query = urlencode({"exact": card_name.strip()})
    request = Request(f"{SCRYFALL_NAMED_URL}?{query}", headers={"User-Agent": "popcorn-cube/0.1"})
    request.add_header("Accept", "application/json;q=0.9,*/*;q=0.8")
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
        return None


def fetch_card_by_id(scryfall_id: str) -> dict[str, Any] | None:
    request = Request(f"{SCRYFALL_CARD_URL}/{scryfall_id}", headers={"User-Agent": "popcorn-cube/0.1"})
    request.add_header("Accept", "application/json;q=0.9,*/*;q=0.8")
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None


def fetch_card_name_suggestions(query: str, mtg_format: str = "", limit: int = 20) -> list[str]:
    card_query = query.strip()
    if len(card_query) < 2:
        return []

    search_terms = [card_query, "in:paper"]
    if mtg_format:
        search_terms.append(f"legal:{mtg_format}")
    search_query = urlencode({"q": " ".join(search_terms), "order": "name", "unique": "cards"})
    request = Request(f"{SCRYFALL_CARD_SEARCH_URL}?{search_query}", headers={"User-Agent": "popcorn-cube/0.1"})
    request.add_header("Accept", "application/json;q=0.9,*/*;q=0.8")
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []

    names: list[str] = []
    seen_names: set[str] = set()
    for card in payload.get("data", []):
        name = card.get("name")
        if not isinstance(name, str) or name in seen_names:
            continue
        names.append(name)
        seen_names.add(name)
        if len(names) >= limit:
            break

    return names


def is_card_legal_for_format(card_data: dict[str, Any], mtg_format: str) -> bool:
    if not mtg_format:
        return True
    legalities = card_data.get("legalities") or {}
    return legalities.get(mtg_format) == "legal"
