"""Entry point: fetch postings, filter internships, diff against state, notify.

Usage:
    python -m checker.main                 # normal run (fetch, diff, email, save)
    python -m checker.main --dry-run       # fetch + diff, print to stdout, no email, no save
    python -m checker.main --no-email      # like normal but skip email (still saves state)

Environment:
    CONFIG   path to config.yaml   (default: config.yaml)
    STATE    path to state.json    (default: state.json)
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

from checker import fetchers, notify, state as state_mod


def matches_keywords(posting: dict, keywords: list[str]) -> bool:
    # Whole-word match so "intern" does not match "internal"/"international".
    title = posting["title"].lower()
    return any(
        re.search(r"\b" + re.escape(kw.lower()) + r"\b", title) for kw in keywords
    )


def matches_location(posting: dict, locations: list[str]) -> bool:
    if not locations:
        return True
    loc = posting["location"].lower()
    return any(l.lower() in loc for l in locations)


def collect(config: dict) -> tuple[list[dict], list[str]]:
    """Return (internship_postings, errors)."""
    keywords = config.get("keywords", [])
    locations = config.get("locations", [])
    postings: list[dict] = []
    errors: list[str] = []

    for company in config.get("companies", []):
        name = company.get("name", company.get("token", "?"))
        try:
            jobs = fetchers.fetch_company(company)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            errors.append(f"{name}: {exc}")
            continue
        kept = [
            j
            for j in jobs
            if matches_keywords(j, keywords) and matches_location(j, locations)
        ]
        print(f"{name}: {len(jobs)} postings, {len(kept)} internships")
        postings.extend(kept)

    return postings, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Internship verifier")
    parser.add_argument("--dry-run", action="store_true", help="no email, no state write")
    parser.add_argument("--no-email", action="store_true", help="skip sending email")
    args = parser.parse_args()

    config_path = os.environ.get("CONFIG", "config.yaml")
    state_path = os.environ.get("STATE", "state.json")

    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    prior_state = state_mod.load(state_path)
    first_run = len(prior_state) == 0

    postings, errors = collect(config)

    if errors:
        print("\nErrors:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)

    # New = postings whose composite key is not in the prior state.
    new_postings = [p for p in postings if state_mod.key(p) not in prior_state]
    print(f"\nTotal internships: {len(postings)} | New since last run: {len(new_postings)}")

    # On the very first run, seed state from everything and report the full set
    # so the inbox doesn't get spammed with a giant "new" list later.
    to_report = postings if first_run else new_postings

    if args.dry_run:
        text, _ = notify.render(to_report, first_run) if to_report else ("(nothing)", "")
        print("\n--- DRY RUN: email body ---\n")
        print(text)
        return 0

    if to_report and not args.no_email:
        subject = (
            f"[Internships] Tracking started — {len(to_report)} open"
            if first_run
            else f"[Internships] {len(to_report)} new posting(s)"
        )
        text, html = notify.render(to_report, first_run)
        recipient = config.get("recipient", "")
        notify.send(subject, text, html, recipient)
        print(f"Email sent ({len(to_report)} postings).")
    elif not to_report:
        print("No new postings — no email sent.")

    # Always update state with everything we saw this run.
    state_mod.record(prior_state, postings)
    state_mod.save(state_path, prior_state)
    print(f"State saved: {len(prior_state)} postings tracked.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
