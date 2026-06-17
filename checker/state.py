"""Persist the set of postings we have already seen, in a JSON file.

Structure:

    {
        "<company name>::<posting id>": {
            "title": ..., "url": ..., "first_seen": "2026-06-17"
        },
        ...
    }

The composite key keeps ids unique across companies (two boards can reuse the
same numeric id).
"""

from __future__ import annotations

import json
import os
from datetime import date


def key(posting: dict) -> str:
    return f"{posting['company']}::{posting['id']}"


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def record(state: dict, postings: list[dict]) -> None:
    today = date.today().isoformat()
    for p in postings:
        k = key(p)
        if k not in state:
            state[k] = {"title": p["title"], "url": p["url"], "first_seen": today}
