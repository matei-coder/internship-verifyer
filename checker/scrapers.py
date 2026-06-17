"""Browser-based scrapers for companies without a usable public JSON API.

Google and Microsoft both retired their simple careers APIs and now serve
JavaScript single-page apps protected against plain HTTP scraping. We render
them with a headless Chromium (Playwright) and read the DOM.

Selectors on these sites are obfuscated and change often, so we lean on
accessibility attributes (aria-label, role=heading) which are far more stable
than CSS class names. If a site redesign breaks one of these, only this file
needs updating.

Playwright is imported lazily so API-only runs don't need it installed.
"""

from __future__ import annotations

import re
from urllib.parse import quote


def _make_id(*parts: str) -> str:
    """Stable id from title+location when the site exposes no real job id."""
    raw = "::".join(p.strip().lower() for p in parts if p)
    return re.sub(r"\s+", "-", raw)[:120]


def scrape(company: dict) -> list[dict]:
    kind = company["type"]
    if kind == "google":
        return scrape_google(company)
    if kind == "microsoft":
        return scrape_microsoft(company)
    if kind == "apple":
        return scrape_apple(company)
    if kind == "meta":
        return scrape_meta(company)
    raise ValueError(f"No scraper for {kind!r}")


def _browser_page():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        locale="en-US",
    )
    page = ctx.new_page()
    return pw, browser, page


def _title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().title()


def scrape_google(company: dict) -> list[dict]:
    query = company.get("query", "intern")
    max_pages = company.get("max_pages", 8)
    out: dict[str, dict] = {}
    pw, browser, page = _browser_page()
    try:
        for pg in range(1, max_pages + 1):
            base = "https://www.google.com/about/careers/applications/jobs/results/"
            # page=1 redirects to a login wall; the first page must omit it.
            url = f"{base}?q={quote(query)}" + (f"&page={pg}" if pg > 1 else "")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            # Dismiss the cookie-consent overlay, which otherwise blocks rendering.
            for sel in ("text=OK, got it", 'button:has-text("got it")', "text=Accept all"):
                try:
                    page.click(sel, timeout=1500)
                    break
                except Exception:
                    pass
            page.wait_for_timeout(2500)
            hrefs = page.eval_on_selector_all(
                'a[href*="/jobs/results/"]',
                "els => els.map(a => a.href).filter(h => !h.includes('accounts.google'))",
            )
            if not hrefs:
                break
            found_this_page = 0
            # URL form: /jobs/results/<id>-<slug>?q=...  — id and title both live
            # in the path, so no fragile CSS selector is needed for the title.
            for href in hrefs:
                m = re.search(r"/jobs/results/(\d+)-([^?/]+)", href)
                if not m:
                    continue
                jid, slug = m.group(1), m.group(2)
                if jid in out:
                    continue
                out[jid] = {
                    "id": jid,
                    "title": _title_from_slug(slug),
                    "location": "",
                    "url": href.split("?")[0],
                    "company": company["name"],
                }
                found_this_page += 1
            if found_this_page == 0:
                break
    finally:
        browser.close()
        pw.stop()
    return list(out.values())


def scrape_apple(company: dict) -> list[dict]:
    """Apple's careers site is a CSRF-protected SPA with no usable public API,
    so we render it and read the result links.

    Each result is an <a href="/.../details/<id>/<slug>"> whose text is the job
    title. The id and a title slug both live in the path, so we never depend on
    a fragile CSS class. Pagination is a plain ?page=N query param.
    """
    query = company.get("query", "intern")
    max_pages = company.get("max_pages", 8)
    out: dict[str, dict] = {}
    pw, browser, page = _browser_page()
    try:
        for pg in range(1, max_pages + 1):
            base = "https://jobs.apple.com/en-us/search"
            url = f"{base}?search={quote(query)}&sort=newest" + (
                f"&page={pg}" if pg > 1 else ""
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector('a[href*="/details/"]', timeout=15000)
            except Exception:
                break
            page.wait_for_timeout(1500)
            cards = page.eval_on_selector_all(
                'a[href*="/details/"]',
                """els => els.map(a => ({
                    title: (a.textContent || '').trim(),
                    href: a.href
                }))""",
            )
            found_this_page = 0
            for c in cards:
                m = re.search(r"/details/(\d+)/([^?/]+)", c["href"])
                if not m:
                    continue
                jid, slug = m.group(1), m.group(2)
                if jid in out:
                    continue
                out[jid] = {
                    "id": jid,
                    "title": c["title"] or _title_from_slug(slug),
                    "location": "",
                    "url": c["href"].split("?")[0],
                    "company": company["name"],
                }
                found_this_page += 1
            if found_this_page == 0:
                break
    finally:
        browser.close()
        pw.stop()
    return list(out.values())


def scrape_meta(company: dict) -> list[dict]:
    """Meta's careers site (metacareers.com) blocks plain HTTP and lazy-loads
    results as you scroll, so we render it and scroll to pull in more cards.

    Each result is an <a href="/jobs/<id>/..."> whose text is the title.
    """
    query = company.get("query", "intern")
    max_scrolls = company.get("max_scrolls", 15)
    out: dict[str, dict] = {}
    pw, browser, page = _browser_page()
    try:
        url = f"https://www.metacareers.com/jobs?q={quote(query)}"
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Dismiss the cookie-consent banner, which otherwise overlays results.
        for sel in (
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept")',
            '[data-cookiebanner] button',
        ):
            try:
                page.click(sel, timeout=1500)
                break
            except Exception:
                pass
        try:
            page.wait_for_selector('a[href*="/profile/job_details/"]', timeout=15000)
        except Exception:
            return []
        page.wait_for_timeout(1500)
        for _ in range(max_scrolls):
            cards = page.eval_on_selector_all(
                'a[href*="/profile/job_details/"]',
                """els => els.map(a => {
                    // The anchor glues title+location+categories with no
                    // separators, but a sub-div holds the location ("City⋅Cat⋅").
                    // The city is glued right after the title in the full text,
                    // so splitting the full text on the city recovers the title.
                    const full = (a.textContent || '').trim();
                    // Many nested divs contain '⋅'; the location leaf is the
                    // shortest of them ("City⋅Category⋅...").
                    const locDiv = [...a.querySelectorAll('div')]
                        .map(d => d.textContent.trim())
                        .filter(t => t.includes('\\u22c5'))
                        .sort((x, y) => x.length - y.length)[0] || '';
                    const city = locDiv.split('\\u22c5')[0].trim();
                    let title = full;
                    if (city && full.includes(city)) title = full.split(city)[0].trim();
                    return { title, location: city, href: a.href };
                })""",
            )
            for c in cards:
                m = re.search(r"/profile/job_details/(\d+)", c["href"])
                if not m:
                    continue
                jid = m.group(1)
                if jid in out or not c["title"]:
                    continue
                out[jid] = {
                    "id": jid,
                    "title": c["title"],
                    "location": c.get("location", ""),
                    "url": c["href"].split("?")[0],
                    "company": company["name"],
                }
            # Lazy-loaded list: scroll to the bottom to request the next batch.
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1500)
    finally:
        browser.close()
        pw.stop()
    return list(out.values())


def scrape_apple(company: dict) -> list[dict]:
    """Apple's jobs site is a CSRF-protected SPA. We render the search page and
    read the result anchors (/details/<id>/<slug>); the title comes from the
    slug, which avoids depending on obfuscated CSS classes.
    """
    query = company.get("query", "intern")
    max_pages = company.get("max_pages", 5)
    out: dict[str, dict] = {}
    pw, browser, page = _browser_page()
    try:
        for pg in range(1, max_pages + 1):
            url = (
                f"https://jobs.apple.com/en-us/search?search={quote(query)}"
                f"&sort=newest&page={pg}"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector('a[href*="/details/"]', timeout=15000)
            except Exception:
                break
            page.wait_for_timeout(1500)
            hrefs = page.eval_on_selector_all(
                'a[href*="/details/"]', "els => els.map(a => a.href)"
            )
            found_this_page = 0
            for href in hrefs:
                m = re.search(r"/details/(\d+)/([a-z0-9-]+)", href)
                if not m:
                    continue
                jid, slug = m.group(1), m.group(2)
                if jid in out:
                    continue
                out[jid] = {
                    "id": jid,
                    "title": _title_from_slug(slug),
                    "location": "",
                    "url": href.split("?")[0],
                    "company": company["name"],
                }
                found_this_page += 1
            if found_this_page == 0:
                break
    finally:
        browser.close()
        pw.stop()
    return list(out.values())


def scrape_microsoft(company: dict) -> list[dict]:
    query = company.get("query", "intern")
    max_pages = company.get("max_pages", 8)
    page_size = 20
    out: dict[str, dict] = {}
    pw, browser, page = _browser_page()
    try:
        for pg in range(max_pages):
            start = pg * page_size
            url = (
                "https://apply.careers.microsoft.com/careers"
                f"?query={quote(query)}&start={start}&sort_by=relevance"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector('a[aria-label^="View job:"]', timeout=15000)
            except Exception:
                break
            page.wait_for_timeout(1500)
            # Each result card is itself an <a href="/careers/job/<id>"> whose
            # aria-label holds the title ("View job: <title>").
            cards = page.eval_on_selector_all(
                'a[aria-label^="View job:"]',
                """els => els.map(a => ({
                    title: (a.getAttribute('aria-label') || '').replace('View job: ', ''),
                    href: a.getAttribute('href') || ''
                }))""",
            )
            found_this_page = 0
            for c in cards:
                m = re.search(r"/job/(\d+)", c["href"])
                jid = m.group(1) if m else _make_id(c["title"])
                if not c["title"] or jid in out:
                    continue
                out[jid] = {
                    "id": jid,
                    "title": c["title"].strip(),
                    "location": "",
                    "url": "https://apply.careers.microsoft.com" + c["href"]
                    if c["href"].startswith("/")
                    else c["href"],
                    "company": company["name"],
                }
                found_this_page += 1
            if found_this_page == 0:
                break
    finally:
        browser.close()
        pw.stop()
    return list(out.values())
