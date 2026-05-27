import re
import statistics
from collections import Counter, defaultdict
from typing import Any

COLOR_ORDER = ("W", "U", "B", "R", "G")
ALLY_COLOR_PAIR_ORDER = ("WU", "UB", "BR", "RG", "GW")
ENEMY_COLOR_PAIR_ORDER = ("WB", "UR", "BG", "RW", "GU")
COLOR_PAIR_ORDER = ALLY_COLOR_PAIR_ORDER + ENEMY_COLOR_PAIR_ORDER
COLOR_PAIR_BY_SET = {frozenset(pair): pair for pair in COLOR_PAIR_ORDER}
COLOR_TO_INDEX = {color: index for index, color in enumerate(COLOR_ORDER)}
CARD_TYPES = {
    "Artifact",
    "Battle",
    "Conspiracy",
    "Creature",
    "Dungeon",
    "Enchantment",
    "Instant",
    "Kindred",
    "Land",
    "Phenomenon",
    "Plane",
    "Planeswalker",
    "Scheme",
    "Sorcery",
    "Tribal",
    "Vanguard",
}
MANA_SYMBOL_PATTERN = re.compile(r"\{([^}]+)\}")
INTEGER_PATTERN = re.compile(r"^-?\d+$")


def _normalized_colors(colors: Any) -> tuple[str, ...]:
    if not isinstance(colors, list):
        return ()
    return tuple(color for color in COLOR_ORDER if color in colors)


def _combo_label(colors: tuple[str, ...]) -> str:
    if not colors:
        return "Colorless"
    if len(colors) == 2:
        return COLOR_PAIR_BY_SET.get(frozenset(colors), "".join(colors))
    return "".join(colors)


def _color_combo_sort_key(colors: tuple[str, ...]) -> tuple[Any, ...]:
    if not colors:
        return (5, 0)

    if len(colors) == 1:
        return (0, COLOR_TO_INDEX[colors[0]])

    if len(colors) == 2:
        combo = COLOR_PAIR_BY_SET.get(frozenset(colors), "".join(colors))
        color_pair = _classify_color_pair(combo)
        if color_pair is not None:
            return color_pair

    return (3, len(colors), tuple(COLOR_TO_INDEX[color] for color in colors))


def _ordered_color_combo_counts(counts: Counter[tuple[str, ...]]) -> dict[str, int]:
    return {_combo_label(colors): counts[colors] for colors in sorted(counts, key=_color_combo_sort_key)}


def _ordered_inclusive_color_counts(counts: Counter[str]) -> dict[str, int]:
    ordered = {color: counts.get(color, 0) for color in COLOR_ORDER if counts.get(color, 0)}
    if counts.get("Colorless", 0):
        ordered["Colorless"] = counts["Colorless"]
    return ordered


def _classify_color_pair(pair: str) -> tuple[int, int] | None:
    if pair in ALLY_COLOR_PAIR_ORDER:
        return (1, ALLY_COLOR_PAIR_ORDER.index(pair))
    if pair in ENEMY_COLOR_PAIR_ORDER:
        return (2, ENEMY_COLOR_PAIR_ORDER.index(pair))
    return None


def _normalized_two_color_pair(parts: list[str]) -> str | None:
    if len(parts) != 2 or not all(part in COLOR_ORDER for part in parts):
        return None
    return COLOR_PAIR_BY_SET.get(frozenset(parts))


def _normalized_two_color_pair_symbol(parts: list[str]) -> str | None:
    pair = _normalized_two_color_pair(parts)
    if pair is None:
        return None
    return f"{pair[0]}/{pair[1]}"


def _mana_symbol_sort_key(symbol: str) -> tuple[Any, ...]:
    if symbol in COLOR_ORDER:
        return (0, COLOR_TO_INDEX[symbol])
    if symbol in {"C", "S"}:
        return (4, symbol)
    if "/" in symbol:
        parts = symbol.split("/")
        combo = _normalized_two_color_pair(parts)
        if combo:
            color_pair = _classify_color_pair(combo)
            if color_pair is not None:
                return color_pair
            return (3, combo)
        return (3, symbol)
    return (5, symbol)


def _ordered_mana_pips(counts: Counter[str]) -> dict[str, int]:
    return {symbol: counts[symbol] for symbol in sorted(counts, key=_mana_symbol_sort_key)}


def _iter_faces(snapshot: dict[str, Any]):
    card_faces = snapshot.get("card_faces")
    if isinstance(card_faces, list) and card_faces:
        for face in card_faces:
            if isinstance(face, dict):
                yield face
        return
    yield snapshot


def _extract_types(type_line: Any) -> tuple[list[str], list[str]]:
    if not isinstance(type_line, str) or not type_line:
        return [], []
    card_types: list[str] = []
    subtypes: list[str] = []

    # Parse both single-faced and split-card type lines by handling each "//" segment
    # and extracting subtypes only from the em-dash section for that segment.
    for card_part in type_line.split("//"):
        main, _, subtype_line = card_part.strip().partition("—")
        card_types.extend(token for token in main.split() if token in CARD_TYPES)
        subtypes.extend(token for token in subtype_line.split() if token)

    # Deduplicate while preserving the first-seen order from the type line.
    card_types = list(dict.fromkeys(card_types))
    subtypes = list(dict.fromkeys(subtypes))
    return card_types, subtypes


def _add_mana_pips(counter: Counter[str], mana_cost: Any) -> None:
    if not isinstance(mana_cost, str):
        return
    for symbol in MANA_SYMBOL_PATTERN.findall(mana_cost):
        symbol = symbol.upper()
        if symbol in COLOR_ORDER or symbol in {"C", "S"}:
            counter[symbol] += 1
            continue
        if symbol.endswith("/P"):
            color = symbol.split("/")[0]
            if color in COLOR_ORDER:
                counter[color] += 1
            continue
        if "/" in symbol:
            parts = symbol.split("/")
            # Normalize two-color hybrid symbols (for example, G/W and W/G both become G/W)
            # so display ordering and aggregation stay consistent.
            pair_symbol = _normalized_two_color_pair_symbol(parts)
            if pair_symbol:
                counter[pair_symbol] += 1
                continue
            counter[symbol] += 1


def _to_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and INTEGER_PATTERN.fullmatch(value):
        return int(value)
    return None


def _value_stats(values: list[int]) -> dict[str, Any]:
    count_by_value_counter = Counter(values)
    count_by_value = {value: count_by_value_counter[value] for value in sorted(count_by_value_counter)}
    if not values:
        return {"count_by_value": count_by_value, "count": 0, "mean": None, "std_dev": None}
    return {
        "count_by_value": count_by_value,
        "count": len(values),
        "mean": statistics.fmean(values),
        "std_dev": statistics.pstdev(values),
    }


def _bucketed_numeric_stats(entries: list[tuple[tuple[str, ...], int]]) -> dict[str, Any]:
    values = [value for _, value in entries]
    by_color: dict[str, list[int]] = {color: [] for color in COLOR_ORDER}
    by_color["Colorless"] = []
    by_color_combination: dict[tuple[str, ...], list[int]] = defaultdict(list)

    for colors, value in entries:
        by_color_combination[colors].append(value)
        if not colors:
            by_color["Colorless"].append(value)
        for color in colors:
            by_color[color].append(value)

    return {
        "overall": _value_stats(values),
        "by_color": {color: _value_stats(by_color[color]) for color in by_color},
        "by_color_combination": {
            _combo_label(colors): _value_stats(by_color_combination[colors])
            for colors in sorted(by_color_combination, key=_color_combo_sort_key)
        },
    }


def _compute_scope_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    strict_color_counts: Counter[tuple[str, ...]] = Counter()
    inclusive_color_counts: Counter[str] = Counter()
    mana_pip_counts: Counter[str] = Counter()

    mana_value_entries: list[tuple[tuple[str, ...], int]] = []
    power_entries: list[tuple[tuple[str, ...], int]] = []
    toughness_entries: list[tuple[tuple[str, ...], int]] = []

    for item in items:
        colors = _normalized_colors(item.get("colors"))
        if not colors and item.get("card_faces"):
            face_colors = set()
            for face in _iter_faces(item):
                face_colors.update(_normalized_colors(face.get("colors")))
            colors = tuple(color for color in COLOR_ORDER if color in face_colors)

        strict_color_counts[colors] += 1
        if colors:
            for color in colors:
                inclusive_color_counts[color] += 1
        else:
            inclusive_color_counts["Colorless"] += 1

        card_types, subtypes = _extract_types(item.get("type_line"))
        type_counts.update(card_types)
        subtype_counts.update(subtypes)
        _add_mana_pips(mana_pip_counts, item.get("mana_cost"))

        mana_value = _to_int(item.get("cmc"))
        if mana_value is not None:
            mana_value_entries.append((colors, mana_value))

        power = _to_int(item.get("power"))
        if power is not None:
            power_entries.append((colors, power))

        toughness = _to_int(item.get("toughness"))
        if toughness is not None:
            toughness_entries.append((colors, toughness))

    return {
        "type_counts": dict(sorted(type_counts.items(), key=lambda item: item[0])),
        "subtype_counts": dict(sorted(subtype_counts.items(), key=lambda item: item[0])),
        "color_breakdown": {
            "strict": _ordered_color_combo_counts(strict_color_counts),
            "inclusive": _ordered_inclusive_color_counts(inclusive_color_counts),
        },
        "mana_pips": _ordered_mana_pips(mana_pip_counts),
        "mana_value": _bucketed_numeric_stats(mana_value_entries),
        "power": _bucketed_numeric_stats(power_entries),
        "toughness": _bucketed_numeric_stats(toughness_entries),
    }


def compute_cube_stats(submissions) -> dict[str, Any]:
    card_items: list[dict[str, Any]] = []
    face_items: list[dict[str, Any]] = []

    for submission in submissions:
        snapshot = submission.card_snapshot or {}
        if not snapshot:
            continue
        card_items.append(snapshot)
        face_items.extend(_iter_faces(snapshot))

    return {
        "cards": _compute_scope_stats(card_items),
        "faces": _compute_scope_stats(face_items),
        "card_count": len(card_items),
        "face_count": len(face_items),
    }
