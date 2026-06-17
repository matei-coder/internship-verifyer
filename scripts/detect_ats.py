"""One-off helper: detect which ATS each company uses and emit config entries.

For every company it (1) downloads the careers page and greps the HTML for an
ATS signature, and (2) falls back to guessing the slug against the public APIs
of Greenhouse, Lever, Ashby and SmartRecruiters.

Run:  python scripts/detect_ats.py
Prints YAML-ready entries for the ones it could verify, plus a list of misses.
"""

from __future__ import annotations

import json
import re
import sys
import time

import requests

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TIMEOUT = 20


def slug_candidates(name: str) -> list[str]:
    n = name.lower()
    n = re.sub(r"\(.*?\)", "", n)  # drop parentheticals
    n = n.split("/")[0].split("&")[0].split(",")[0]
    n = n.replace(".", "").replace("'", "")
    base = re.sub(r"[^a-z0-9]+", "", n)
    spaced = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    words = [w for w in re.split(r"[^a-z0-9]+", n) if w]
    cands = {base, spaced}
    if words:
        cands.add(words[0])
        cands.add("".join(words))
    return [c for c in cands if len(c) >= 2]


def ok_json(url: str, method="GET", **kw) -> dict | None:
    try:
        r = requests.request(method, url, headers=UA, timeout=TIMEOUT, **kw)
        if r.status_code == 200 and r.text.strip():
            return r.json()
    except Exception:
        return None
    return None


def try_greenhouse(slug: str):
    d = ok_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if d and d.get("jobs"):
        return {"type": "greenhouse", "token": slug}, len(d["jobs"])
    return None, 0


def try_lever(slug: str):
    d = ok_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if isinstance(d, list) and d:
        return {"type": "lever", "token": slug}, len(d)
    return None, 0


def try_ashby(slug: str):
    d = ok_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if d and d.get("jobs"):
        return {"type": "ashby", "token": slug}, len(d["jobs"])
    return None, 0


def try_smartrecruiters(slug: str):
    d = ok_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=10")
    if d and d.get("totalFound", 0) > 0:
        return {"type": "smartrecruiters", "token": slug}, d["totalFound"]
    return None, 0


GUESSERS = [try_greenhouse, try_lever, try_ashby, try_smartrecruiters]


def from_html(careers_url: str):
    """Look for an ATS signature embedded in the careers page HTML."""
    try:
        html = requests.get(careers_url, headers=UA, timeout=TIMEOUT).text
    except Exception:
        return None
    patterns = [
        (r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", "greenhouse"),
        (r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)", "greenhouse"),
        (r"job_board\?for=([a-z0-9_-]+)", "greenhouse"),
        (r"jobs\.lever\.co/([a-z0-9_-]+)", "lever"),
        (r"api\.lever\.co/v0/postings/([a-z0-9_-]+)", "lever"),
        (r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", "ashby"),
        (r"api\.ashbyhq\.com/posting-api/job-board/([a-z0-9_-]+)", "ashby"),
        (r"([a-z0-9_-]+)\.wd\d+\.myworkdayjobs\.com", "workday"),
        (r"jobs\.smartrecruiters\.com/([a-z0-9_-]+)", "smartrecruiters"),
    ]
    for rx, kind in patterns:
        m = re.search(rx, html, re.I)
        if m:
            return kind, m.group(1)
    return None


def detect(name: str, careers_url: str):
    # 1) HTML signature (most reliable when present)
    sig = from_html(careers_url) if careers_url else None
    if sig:
        kind, token = sig
        verify = {
            "greenhouse": try_greenhouse,
            "lever": try_lever,
            "ashby": try_ashby,
            "smartrecruiters": try_smartrecruiters,
        }.get(kind)
        if kind == "workday":
            return {"type": "workday", "_token_hint": token, "_via": "html"}, 0
        if verify:
            cfg, n = verify(token)
            if cfg:
                cfg["_via"] = "html"
                return cfg, n
    # 2) Guess slugs against each API
    for slug in slug_candidates(name):
        for guess in GUESSERS:
            cfg, n = guess(slug)
            if cfg:
                cfg["_via"] = "guess"
                return cfg, n
    return None, 0


def main():
    companies = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else load_default()
    found, missed = [], []
    for name, url in companies.items():
        cfg, n = detect(name, url)
        if cfg:
            cfg["name"] = name
            cfg["_count"] = n
            found.append(cfg)
            print(f"OK   {name:40s} {cfg['type']:16s} token={cfg.get('token', cfg.get('_token_hint'))} ({n}) [{cfg['_via']}]", flush=True)
        else:
            missed.append(name)
            print(f"MISS {name}", flush=True)
        time.sleep(0.2)

    print("\n\n# ==== YAML entries (verified) ====")
    for c in found:
        if c["type"] in ("greenhouse", "lever", "ashby", "smartrecruiters") and c.get("token"):
            print(f'  - name: {c["name"]}\n    type: {c["type"]}\n    token: {c["token"]}')
    print(f"\n# Found {len(found)} / {len(companies)}.  Missed {len(missed)}:")
    print("# " + ", ".join(missed))


def load_default():
    import glob
    seen = {}
    for f in glob.glob("internship_list/*.json"):
        d = json.load(open(f))
        rows = d if isinstance(d, list) else d.get("companies", [])
        for c in rows:
            name = (c.get("companie") or c.get("name") or "").strip()
            url = c.get("link_pagina_cariere") or c.get("careers_url") or ""
            if name:
                seen.setdefault(name, url)
    return seen


if __name__ == "__main__":
    main()
