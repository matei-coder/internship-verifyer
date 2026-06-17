"""Fetch open postings from various applicant-tracking systems.

Every fetcher returns a list of dicts with a stable shape:

    {
        "id":       unique string id for the posting (per company),
        "title":    job title,
        "location": human-readable location,
        "url":      link to apply,
        "company":  company display name,
    }

The `id` is what we use to detect new postings, so it must be stable across
runs for the same posting.
"""

from __future__ import annotations

import requests

TIMEOUT = 30
HEADERS = {
    "User-Agent": "internship-verifyer/1.0 (+https://github.com)",
    "Accept": "application/json",
}


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def fetch_greenhouse(company: dict) -> list[dict]:
    token = company["token"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    data = _get(url).json()
    out = []
    for job in data.get("jobs", []):
        out.append(
            {
                "id": str(job.get("id")),
                "title": job.get("title", "").strip(),
                "location": (job.get("location") or {}).get("name", "").strip(),
                "url": job.get("absolute_url", ""),
                "company": company["name"],
            }
        )
    return out


def fetch_lever(company: dict) -> list[dict]:
    token = company["token"]
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = _get(url).json()
    out = []
    for job in data:
        cats = job.get("categories") or {}
        out.append(
            {
                "id": str(job.get("id")),
                "title": job.get("text", "").strip(),
                "location": (cats.get("location") or "").strip(),
                "url": job.get("hostedUrl", ""),
                "company": company["name"],
            }
        )
    return out


def fetch_workday(company: dict) -> list[dict]:
    """Workday paginates via a POST body with limit/offset."""
    base = company["base"].rstrip("/")
    tenant = company["tenant"]
    site = company["site"]
    endpoint = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    # The public-facing job URL lives at a different path than the API.
    public_base = f"{base}/{site}"

    out = []
    offset = 0
    limit = 20
    while True:
        body = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": company.get("search", "intern"),
        }
        resp = requests.post(endpoint, json=body, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for job in postings:
            path = job.get("externalPath", "")
            req_id = (job.get("bulletFields") or [None])[0] or path
            out.append(
                {
                    "id": str(req_id),
                    "title": job.get("title", "").strip(),
                    "location": job.get("locationsText", "").strip(),
                    "url": public_base + path if path else public_base,
                    "company": company["name"],
                }
            )
        offset += limit
        if offset >= data.get("total", 0):
            break
    return out


def fetch_ashby(company: dict) -> list[dict]:
    token = company["token"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
    data = _get(url).json()
    out = []
    for job in data.get("jobs", []):
        out.append(
            {
                "id": str(job.get("id")),
                "title": job.get("title", "").strip(),
                "location": (job.get("location") or "").strip(),
                "url": job.get("jobUrl") or job.get("applyUrl", ""),
                "company": company["name"],
            }
        )
    return out


def fetch_smartrecruiters(company: dict) -> list[dict]:
    token = company["token"]
    out = []
    offset = 0
    limit = 100
    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
            f"?limit={limit}&offset={offset}"
        )
        data = _get(url).json()
        content = data.get("content", [])
        for job in content:
            loc = job.get("location") or {}
            loc_str = ", ".join(
                x for x in [loc.get("city"), loc.get("country")] if x
            )
            out.append(
                {
                    "id": str(job.get("id")),
                    "title": job.get("name", "").strip(),
                    "location": loc_str,
                    "url": f"https://jobs.smartrecruiters.com/{token}/{job.get('id')}",
                    "company": company["name"],
                }
            )
        offset += limit
        if offset >= data.get("totalFound", 0) or not content:
            break
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "workday": fetch_workday,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
}


def fetch_company(company: dict) -> list[dict]:
    kind = company.get("type")
    fetcher = FETCHERS.get(kind)
    if fetcher is None:
        raise ValueError(f"Unknown company type {kind!r} for {company.get('name')}")
    return fetcher(company)
