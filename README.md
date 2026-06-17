# Internship verifier

Checks company career boards every morning and emails you any **new** internship
postings. Runs free on GitHub Actions — your laptop doesn't need to be on.

## How it works

1. `checker/fetchers.py` pulls open postings from each company's applicant-tracking
   system via its public JSON API (Greenhouse, Lever, Workday) — no scraping, no
   anti-bot fights.
2. Titles are filtered by the keywords in `config.yaml` (intern, new grad, etc.).
3. Postings are diffed against `state.json` (the ones already seen). Only new
   ones are emailed.
4. `state.json` is committed back to the repo so the next run remembers.

## Configure companies

Edit `config.yaml`. ~70 companies are pre-configured (quant firms, big tech, AI
labs, EU scaleups). Each entry needs a `type`:

| type             | fields needed            | how to find it |
|------------------|--------------------------|----------------|
| `greenhouse`     | `token`                  | `boards.greenhouse.io/<token>` |
| `lever`          | `token`                  | `jobs.lever.co/<token>` |
| `ashby`          | `token`                  | `jobs.ashbyhq.com/<token>` |
| `smartrecruiters`| `token`                  | `jobs.smartrecruiters.com/<token>` |
| `workday`        | `base`, `tenant`, `site` | `https://<tenant>.<xx>.myworkdayjobs.com/<site>` |
| `amazon`         | `queries` (list)         | Amazon's public search.json |
| `google`         | `query` (optional)       | browser-scraped (Playwright) |
| `microsoft`      | `query` (optional)       | browser-scraped (Playwright) |

To auto-detect the ATS for a new batch of companies, drop a JSON list in
`internship_list/` and run `python scripts/detect_ats.py`.

### Note on Google / Microsoft / Amazon
These run their own systems, not a standard ATS:
- **Amazon** has a clean public JSON API — reliable.
- **Microsoft** is browser-scraped from `apply.careers.microsoft.com` — reliable.
- **Google** is browser-scraped but actively rate-limits bots. It is **best
  effort**: a fresh CI IP hitting it once a day usually works, but it may
  occasionally return nothing. The run never fails because of it.

## Email setup (Gmail)

The digest is sent via Gmail SMTP. You need a Google **app password** (not your
normal password):

1. Enable 2-Step Verification on the sending Google account.
2. Go to <https://myaccount.google.com/apppasswords>, create an app password.
3. In the GitHub repo: **Settings → Secrets and variables → Actions** → add:
   - `GMAIL_USER` — the sending Gmail address
   - `GMAIL_APP_PASSWORD` — the 16-char app password
   - `EMAIL_TO` *(optional)* — recipient; defaults to `recipient` in `config.yaml`
     (currently `mateimacqueen@gmail.com`)

## Run locally

```bash
pip install -r requirements.txt

# See what it would send, without emailing or saving state:
python -m checker.main --dry-run

# Real run (needs GMAIL_USER / GMAIL_APP_PASSWORD env vars to email):
python -m checker.main
```

## Schedule

`.github/workflows/check.yml` runs daily at 03:00 UTC (~06:00 Romania in summer).
Change the `cron` line to adjust. You can also trigger it manually from the
**Actions** tab (workflow_dispatch).

The first run seeds `state.json` with everything currently open and emails the
full list once; after that you only get genuinely new postings.
