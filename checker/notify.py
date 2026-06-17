"""Send the morning digest by email via Gmail SMTP.

Requires two environment variables (set as GitHub Actions secrets):
    GMAIL_USER          - the sending Gmail address
    GMAIL_APP_PASSWORD  - a Google "app password" (not your normal password)

Optional:
    EMAIL_TO            - overrides the recipient from config.yaml
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from html import escape


def _group_by_company(postings: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for p in postings:
        grouped.setdefault(p["company"], []).append(p)
    return grouped


def render(postings: list[dict], first_run: bool) -> tuple[str, str]:
    """Return (plain_text, html) bodies."""
    grouped = _group_by_company(postings)
    n = len(postings)

    intro = (
        f"Tracking started. {n} internship postings are currently open."
        if first_run
        else f"{n} new internship posting(s) found this morning."
    )

    # Plain text
    lines = [intro, ""]
    for company in sorted(grouped):
        lines.append(f"== {company} ({len(grouped[company])}) ==")
        for p in grouped[company]:
            loc = f" — {p['location']}" if p["location"] else ""
            lines.append(f"  • {p['title']}{loc}")
            lines.append(f"    {p['url']}")
        lines.append("")
    text = "\n".join(lines)

    # HTML
    html_parts = [f"<h2>{escape(intro)}</h2>"]
    for company in sorted(grouped):
        html_parts.append(f"<h3>{escape(company)} ({len(grouped[company])})</h3><ul>")
        for p in grouped[company]:
            loc = f" — {escape(p['location'])}" if p["location"] else ""
            html_parts.append(
                f'<li><a href="{escape(p["url"])}">{escape(p["title"])}</a>{loc}</li>'
            )
        html_parts.append("</ul>")
    html = "\n".join(html_parts)

    return text, html


def send(subject: str, text: str, html: str, recipient: str) -> None:
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    # Empty env var (e.g. an unset GitHub secret expands to "") must fall back
    # to the configured recipient, not become an empty To: address.
    to = os.environ.get("EMAIL_TO") or recipient

    if not to:
        raise RuntimeError("No recipient: set EMAIL_TO or `recipient` in config.yaml.")

    if not user or not password:
        raise RuntimeError(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set to send email."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.send_message(msg)
