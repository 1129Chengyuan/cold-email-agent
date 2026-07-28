# AGENT.md — How to drive this tool with Claude / Cowork

This file tells you (Claude, running in Cowork) how to operate this project when the user
gives you a company + job description. Read this first, then follow the workflow.

---

## What this project is
A human-in-the-loop cold-outreach tool. The user applies to a job, then pastes the
**company name + job description (JD)** to you. Your job: find the right people, write
tailored emails referencing the user's resume, get approval, send, and log.

- Code lives in `src/`. Secrets/config in `.env` (loaded by `src/core/config.py`).
- The user's resume is at `assets/resume.pdf` (attached automatically on every send).
- Every send is logged to Google Sheets.
- **Always run Python from the repo root** with the venv active:
  `source venv/bin/activate` then `python src/<module>.py`.

---

## The workflow (when the user pastes a company + JD)

**a. Confirm eligibility & fit.**
   - Check the JD for location/eligibility restrictions (e.g. "not eligible in CA, NY, PA…").
     The user's resume location is **Atlanta, GA** — flag any conflict before proceeding.
   - Note the exact **role title** and **team** (you'll reference these in the email).

**b. Determine the company's email pattern (ONCE) — then GUESS the rest to save Prospeo credits.**
   - **Reveal only ONE verified email** via Prospeo to learn the company's format
     (patterns vary: `first.last@`, `flast@`, `firstname@`, `lastname.first@`, and the
     domain may differ, e.g. `@bloomberg.net`, `@qti.qualcomm.com`).
   - Then get the remaining recruiter **names** from Prospeo *search* (cheap, no reveal) or
     web search, and **construct their emails from the confirmed pattern** — do NOT spend a
     Prospeo enrich credit per person. The free tier is ~75 credits/month, so one reveal +
     pattern-guessing the rest is the default.
   - Caveat: pattern-guessing bounces if the pattern is inconsistent (Uber/Qualcomm use
     several formats) or the person left the company. If a company's format looks
     inconsistent, fall back to revealing verified emails for the few that matter.

**c. Find the right people (US-based).**
   - **Default: whenever a JD comes in, automatically find 10 US-based recruiters online**
     (LinkedIn / web search) for that role — no need to be asked. Prioritize
     technical/university/early-career recruiters. If fewer than 10 are publicly reachable,
     surface as many good-fit names as you can find and say so.
   - **Always find 10 real recruiter NAMES online first (web/LinkedIn), then construct each
     email using the company's HIGHEST-PROBABILITY pattern** (look the dominant format up
     online — e.g. RocketReach/LeadIQ report the % — and use that single best pattern for
     everyone). Do NOT invent names to hit 10, and do NOT spray multiple pattern variants at
     the same person (that just multiplies bounces). If a specific address bounces, retry
     ONLY that person with the next-most-common pattern.
   - **Also default: for every JD, find 2 hiring managers highly correlated to this specific
     role/team** (engineering manager, team lead, or director over the JD's exact team — verify
     the team on LinkedIn/web before recommending). The user wants to reach hiring managers
     directly, not only route through recruiters. If a manager's email can't be verified,
     construct it from the confirmed company pattern and flag the bounce risk.
   - **Always ask the user before sending any cold email** — show the drafts (recruiters +
     the 2 hiring managers) and wait for an explicit "send".
   - Search Prospeo for **US-based recruiters** (technical/university recruiters fit SWE roles)
     and, when asked, **hiring managers** on the JD's specific team.
   - Filter to `person_location_search: {include: ["United States"]}`.
   - **Only use Prospeo-VERIFIED emails** — `UNAVAILABLE` means the person likely left;
     guessed/pattern emails to them bounce. If the user insists on someone unverified,
     warn about bounce risk first.
   - Verify a hiring manager's team on LinkedIn (web search) before recommending them —
     don't email someone on the wrong team.

**d. Draft a tailored email per person.**
   - Use `src/outreach/email_generator.py` (Gemini) or write it directly. Keep it ~100–120 words.
   - Tie the user's resume specifics to the JD (e.g. messaging-app project ↔ messaging role,
     LangGraph/AI agent work ↔ AI roles, GCP/FastAPI ↔ backend/cloud roles).
   - Lead with **UC Berkeley CS** + **Genuine Parts Company (Fortune 200)**.
   - Signature: name, phone, **both emails** (gmail + berkeley), LinkedIn. **No GitHub.**
   - **Always include the job number / requisition ID in the email if the JD has one**
     (e.g. "Job 210759344", "Role #200669637") — put it in the first sentence next to the
     role title so the recruiter can route you instantly.
   - Do **not** mention H1B unless the user confirms the company sponsors.

**e. Show the draft(s) and WAIT for approval.**
   - Always preview before sending. Let the user edit wording, recipients, count.

**f. Send + log.**
   - On approval, send with resume attached and log each to the Google Sheet.
   - Dedup is by **recipient email** — the same person won't be emailed twice, but multiple
     people for one role is fine.

**g. Report results + watch for bounces.**
   - Summarize who was emailed. Tell the user to watch for bounce-backs (only relevant if
     any unverified addresses were used).

---

## Defaults & preferences (the user, Cheng-Yuan Li)
- Georgia Tech CS student (GPA 4.0/4.0, expected May 2028), seeking Software Engineering /
  Data Engineering / Infrastructure & Cloud **internships**, needs H-1B sponsorship down the
  road. Based in Atlanta, GA (eligible for most US-remote roles).
- Email tone: concise, professional, specific. No buzzwords, no "I hope this finds you well."
- Prefers **quality over volume** — targeted, verified, tailored. 5–10 contacts per role is plenty.
- Resume highlights to draw from: Georgia Tech CS; SWE/Data/Cloud Infra internship at Gordon
  Food Service (Python, Terraform, GCP — BigQuery/Cloud Run/Cloud Scheduler/Secret Manager,
  Apache Airflow/PySpark/dbt); TA for Database Systems & Intro to OOP; SmallDB (C++20 LSM-tree
  storage engine); NBA Analytics data pipeline (Airflow/PySpark/dbt); Research Intern at A*STAR.
- **Three tailored resumes exist** — pick the one matching the role's focus when attaching:
  `assets/resume.pdf` (general/SWE, the default), `assets/resume_de.pdf` (Data Engineering),
  `assets/resume_infra_cloud.pdf` (Infrastructure/Cloud). There's no CLI flag to pick one —
  to use a non-default resume for a specific outreach run, temporarily set `RESUME_PATH` in
  `.env` to its path before running `src.outreach.outreach`, then switch it back afterward.

## Guardrails
- **ALWAYS give the user a look at the email before you send. Show the full draft(s) and wait for an explicit "send" — no exceptions.**
- Never commit or paste secrets. They live only in `.env` (gitignored).
- Never send without showing a preview and getting an explicit "send".
- Prefer verified emails; warn before sending to guessed/pattern addresses.
- Respect Prospeo's free-tier credits (~75/month) — don't reveal more emails than needed.
