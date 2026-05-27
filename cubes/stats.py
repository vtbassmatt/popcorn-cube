import re
import statistics
from collections import Counter, defaultdict
from typing import Any

COLOR_ORDER = ("W", "U", "B", "R", "G")
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
    return "Colorless" if not colors else "".join(colors)


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
    main, _, subtype_line = type_line.partition("—")
    card_types = [token for token in main.split() if token in CARD_TYPES]
    subtypes = [token for token in subtype_line.split() if token]
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
    by_color_combination: dict[str, list[int]] = defaultdict(list)

    for colors, value in entries:
        by_color_combination[_combo_label(colors)].append(value)
        if not colors:
            by_color["Colorless"].append(value)
        for color in colors:
            by_color[color].append(value)

    return {
        "overall": _value_stats(values),
        "by_color": {color: _value_stats(by_color[color]) for color in by_color},
        "by_color_combination": {
            combo: _value_stats(combo_values)
            for combo, combo_values in sorted(by_color_combination.items(), key=lambda item: item[0])
        },
    }


def _compute_scope_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    strict_color_counts: Counter[str] = Counter()
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

        strict_color_counts[_combo_label(colors)] += 1
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
            "strict": dict(sorted(strict_color_counts.items(), key=lambda item: item[0])),
            "inclusive": dict(sorted(inclusive_color_counts.items(), key=lambda item: item[0])),
        },
        "mana_pips": dict(sorted(mana_pip_counts.items(), key=lambda item: item[0])),
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
