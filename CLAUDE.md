# CLAUDE.md — how to run this project with Claude Code

This repo is an **H-1B-sponsor job agent**. Anyone who needs visa sponsorship can fork it
and drive it entirely through Claude Code — no terminal expertise required. This file is
your playbook: read it, then help the user set it up and operate it.

## What it does (two halves, one shared pipeline)

1. **Daily job board + digest** — pulls fresh roles from companies that are *confirmed
   H-1B sponsors*, publishes them all to a public website (GitHub Pages), ranks them
   against the user's résumé, and emails the user the **top 10** each morning.
2. **Cold-email outreach** — for a company the user applied to, finds recruiters/hiring
   managers, drafts a tailored email each (résumé attached), previews, sends, and logs.

   **Default when the user pastes a JD (or job link):** run the full prep automatically —
   (a) **do NOT check sponsorship** — per the owner's instruction, a pasted JD already meets
   their sponsorship needs, so skip `company_h1b_lookup`/research (only flag if the JD text
   itself explicitly says it will not sponsor); (b) find the company **email pattern**;
   (c) surface **~10 real recruiters** (prefer technical / early-career; never invent names);
   (d) find **a few highly-matched hiring managers** on the *specific* team (skip too-senior
   VPs); (e) draft RAG-grounded emails (recruiter + hiring-manager versions), then **show
   every draft for approval before sending**.

## 🔒 The one rule you must never break: H-1B sponsors only

The user's whole reason for this tool is that they need sponsorship. **Every role must come
from an H-1B sponsor.** Two layers enforce this — never weaken either:

- **Company universe** — the job boards scraped are derived from the USCIS H-1B Employer
  Data Hub (`data/h1b_employers.db` → `h1b_db.top_sponsors()` → `data/h1b_sponsors.json`).
  A company cannot appear unless it sponsored H-1B. Do not add non-sponsor job sources.
- **Per-role gate** — `fit_ranker.says_no_sponsorship()` drops any posting whose JD says
  "no sponsorship." Keep it.

This rule is **independent of field or résumé** — it survives every change below.

## Onboarding a new user (do this when they ask you to "set it up")

Ask for: their **field & seniority** (e.g. "new-grad software engineer", "mid-level
mechanical engineer"), their **résumé**, and the **email address** for the digest.

1. **Résumé** → save it at `assets/resume.pdf` (or paste text into `assets/resume.txt`).
   `fit_ranker` reads this automatically, so ranking adapts to whoever's résumé it is — no
   code change needed for a different *person*.
2. **Profile & keys** → fill `.env` (copy from `.env.example`). Point them to
   `docs/SETUP.md` for where each value comes from. Minimum for the daily board+email:
   `GEMINI_API_KEY` (free — ranking *and* cold-email writing), `SENDER_EMAIL` +
   `GMAIL_APP_PASSWORD`, `DIGEST_TO`, and `YOUR_NAME`. Prospeo + Sheets keys are
   only needed for the outreach half.
3. **Field switch (only if NOT software engineering)** — the pipeline pulls SWE titles by
   default. To target another field, edit these and nothing else:
   - `src/jobs/ats.py` → `_POSITIVE` (role-title keywords to KEEP, e.g. for a data analyst:
     `"data analyst"`, `"business analyst"`, `"analytics"`), `_JUNIOR`/`_SENIOR` (seniority
     words), and `_NONSOFTWARE` (titles to REJECT). **Do not touch `is_us()` or the
     sponsorship logic** — those are field-independent.
   - Display strings "Fresh SWE roles" / "SWE role": `src/digest/jobs_site.py` (`<title>` + `<h1>`)
     and `src/digest/daily_job_email.py` (subject line + empty-state text). Rename to the field.
   - Optionally `config.JOB_SEARCH_TERMS` (used by the outreach-side aggregator).
   After editing, run a dry run (below) to confirm roles still come through.
4. **Personalize outreach** — `docs/AGENT.md` holds the *current* owner's background and
   email preferences. Rewrite it for the new user (school, employer, location, tone) before
   they use the cold-email half.
5. **Automate** — daily runs happen in GitHub Actions. Have them add the `.env` values as
   **repo Secrets** (table in `docs/SETUP.md` §7) and enable **Pages → `main` / `/docs`**.
   The site publishes to `their-github-username.github.io/<repo>`.

## Running it (translate these to the user; they just talk to you)

- **Preview the daily run (no email):** `python -m src.digest.daily_workflow --to <email> --dry-run`
- **Full daily run:** `python -m src.digest.daily_workflow --to <email>` (site + top-10 email)
- **Rebuild just the site:** `python -m src.digest.jobs_site --open`
- **Cold outreach for a company (preview):**
  `python -m src.outreach.outreach --company <domain> --title "<role>" --jd jd.txt --max 5`
  (add `--send` only after the user approves the drafts)
- The GitHub Action `.github/workflows/daily.yml` runs the full daily loop at 8 AM ET.

## Guardrails (enforce these)

- **Never send outreach without showing the drafts and getting an explicit "send."**
  The daily digest goes only to the user's own inbox; cold emails go to real recruiters.
- **Send flow:** one Prospeo reveal per company to confirm the email pattern, then
  construct the rest from that pattern and send the batch immediately — no reveal per
  person, no automatic bounce-checking. `bounce_retry.py`'s IMAP bounce check is a manual,
  opt-in tool (`--check`/`--retry`) the user runs on request, never automatic.
- **Never weaken the H-1B-sponsor filter** (see the rule above).
- **Never commit secrets.** `.env`, `assets/*.json`, and `assets/resume.pdf` are gitignored;
  in CI they come from GitHub Secrets. `data/h1b_employers.db` IS committed on purpose
  (public USCIS data + which job IDs were already emailed) — keep committing it so the
  Action's dedup state persists.
- **The LLM is free by default** (Gemini free tier). Ranking falls back to a keyword
  scorer and outreach to a plain template when the quota is spent — both stay at $0.
  Don't wire in a paid API without telling the user it costs money.

## File map

`src/` is a package split into five subpackages:

- **`src/core/`** — shared infrastructure: `config.py` (secrets/paths), `gemini.py` (free
  Gemini LLM + embeddings client), `h1b_db.py` (SQLite), `gmail_sender.py` (email transport).
- **`src/jobs/`** — sourcing sponsor roles: `ats.py` (ATS parsing/filters),
  `h1b_greenhouse.py` (board discovery + fetch), `company_lookup.py` (builds `docs/employers.json`).
- **`src/ranking/`** — `fit_ranker.py` (résumé fit scoring + sponsorship gate) and
  `resume_kb.py` (RAG retrieval over `assets/experience.json`, used by the email writer).
- **`src/digest/`** — the daily half: `daily_workflow.py` is THE entry point
  (`python -m src.digest.daily_workflow`); it uses `jobs.h1b_greenhouse` to fetch,
  `ranking.fit_ranker` to score, `jobs_site.py` to build the site, `daily_job_email.py` to email the top 10.
- **`src/outreach/`** — the cold-email half: `outreach.py` / `outreach_server.py` with
  `prospeo_lookup.py`, `email_generator.py` (grounds emails via `ranking.resume_kb`),
  `sheets_logger.py`, `bounce_retry.py` (send log + bounce retry), `reply_tracker.py`
  (IMAP reply detection + classification → `reply_status`), and `applications.py`
  (job-application tracker → private `data/applications.db`, imported from a Sheets export).
- **`src/mcp/`** — `server.py` (18 FastMCP tools over the packages above) + `audit.py`
  (logs every tool call to private `data/agent_log.db`).

Run any module as `python -m src.<pkg>.<module>`. Occasional maintenance script:
`scripts/import_lca_wages.py` (DOL wage refresh). Imports are absolute (`from src.core import config`).
