from typing import Any


FACE_FIELDS = ("name", "mana_cost", "type_line", "colors", "cmc", "power", "toughness")
CARD_FIELDS = FACE_FIELDS + ("id",)


def _pick_fields(card_data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for field in fields:
        if field in card_data:
            snapshot[field] = card_data[field]
    return snapshot


def build_card_snapshot(card_data: dict[str, Any]) -> dict[str, Any]:
    snapshot = _pick_fields(card_data, CARD_FIELDS)
    card_faces = card_data.get("card_faces")
    if isinstance(card_faces, list):
        snapshot["card_faces"] = [_pick_fields(face, FACE_FIELDS) for face in card_faces if isinstance(face, dict)]
    return snapshot
