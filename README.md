# popcorn-cube

Popcorn Cube is a Django app for collaboratively building a Magic: the Gathering cube round-by-round.

## Features

- Create invite-only cubes with selected participants.
- Enforce rounded max-card limits based on participant count.
- Enforce optional format legality via Scryfall card legality data.
- Enforce per-card copy limits (`1` singleton, `0` unlimited).
- Round-based submissions where round 2+ can reference prior-round cards.

## Development

This project is managed with `uv`.

```bash
~/.local/bin/uv sync
~/.local/bin/uv run python manage.py migrate
~/.local/bin/uv run python manage.py runserver
```
