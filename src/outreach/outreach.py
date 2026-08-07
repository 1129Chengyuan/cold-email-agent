#!/usr/bin/env python3
# ============================================================
#  outreach.py — targeted, human-in-the-loop outreach
#
#  Workflow for a company you applied to:
#    1. Find US-based recruiters at the company (Prospeo)
#    2. Reveal verified emails (skips stale/unverifiable to avoid bounces)
#    3. Generate a tailored email per recruiter (Gemini)
#    4. Preview (default) — review before sending
#    5. Send + log to Google Sheets (with recipient-based dedup)
#
#  Usage:
#    python outreach.py --company twilio.com --title "Software Engineer (L1)" \
#        --jd jd.txt --max 5                 # preview only (safe default)
#    python outreach.py --company twilio.com --title "Software Engineer (L1)" \
#        --jd jd.txt --max 5 --send          # actually send
#    python outreach.py --company sony.com --title "SWE I" --jd jd.txt \
#        --allow-unverified                  # include pattern-risky emails
# ============================================================

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from src.core import config
from src.outreach.prospeo_lookup import _search_recruiters, _reveal_email
from src.outreach.email_generator import generate_outreach
from src.outreach.cover_letter_generator import generate_cover_letter
from src.outreach.resume_selector import select_resume
from src.outreach.resume_builder import build_resume
from src.core.gmail_sender import send_email
from src.outreach.sheets_logger import already_emailed, log_outreach


def find_verified_recruiters(company_domain: str, max_people: int,
                             allow_unverified: bool = False) -> list[dict]:
    """Search + reveal recruiter emails. Returns recruiters with usable emails."""
    if not config.PROSPEO_API_KEY:
        print("\n⚠ PROSPEO_API_KEY not set — verified recruiter lookup unavailable.\n"
              "  Find recruiter names yourself (e.g. LinkedIn) and use the review\n"
              "  server (python -m src.outreach.outreach_server) or ask your AI\n"
              "  assistant to build pattern-guessed addresses.")
        return []
    print(f"\n▶ Searching US recruiters at {company_domain} ...")
    try:
        people = _search_recruiters(company_domain, us_only=True)
    except Exception as e:
        print(f"  ⚠ Prospeo lookup failed ({e}) — check the key / credits.")
        return []
    if not people:
        print("  ⚠ No recruiters found.")
        return []

    out: list[dict] = []
    for p in people:
        if len(out) >= max_people:
            break
        email = _reveal_email(p, company_domain)
        if email:
            p["email"] = email
            out.append(p)
            print(f"  ✅ {p['name']} <{email}>")
        elif allow_unverified:
            # Construct nothing — Prospeo had no verified email; skip unless caller
            # explicitly wants pattern guesses (handled separately, not here).
            print(f"  ⏭ {p['name']}: no verified email (skipped)")
        else:
            print(f"  ⏭ {p['name']}: no verified email (skipped)")
        time.sleep(0.4)
    return out


def run(company_domain: str, title: str, jd_text: str, max_people: int,
        send: bool, allow_unverified: bool, hook: str | None = None) -> None:
    recruiters = find_verified_recruiters(company_domain, max_people, allow_unverified)
    if not recruiters:
        print("\nNothing to send. Try a different domain or --allow-unverified.")
        return

    company_name = company_domain.split(".")[0].title()
    job = {
        "company": company_name,
        "title": title,
        "company_domain": company_domain,
        "description_snippet": jd_text[:600],
        "job_url": "",
        "date_posted": "",
        "h1b_signal": 1,
    }

    resume_path = build_resume(job) or select_resume(job)
    config.RESUME_PATH = resume_path
    print(f"  📄 Résumé for review → {resume_path}")

    try:
        cover_letter_path = generate_cover_letter(job)
        if cover_letter_path:
            config.COVER_LETTER_PATH = cover_letter_path
    except Exception as e:
        print(f"  ⚠ Cover letter generation failed: {e} — sending without one")

    print(f"\n▶ {'SENDING' if send else 'PREVIEW (no send)'} — {len(recruiters)} recruiter(s)\n")
    sent = skipped = failed = 0

    for r in recruiters:
        if already_emailed(r["email"]):
            print(f"  ⏭ Already emailed {r['email']} — skipping.")
            skipped += 1
            continue

        recruiter = {
            "name": r["name"],
            "first_name": r.get("first_name", ""),
            "title": r.get("job_title", "Recruiter"),
            "email": r["email"],
        }
        try:
            out = generate_outreach(job, recruiter, hook=hook)
        except Exception as e:
            print(f"  ❌ Generation failed for {r['name']}: {e}")
            failed += 1
            continue

        print("\n" + "─" * 60)
        print(f"To      : {recruiter['name']} <{recruiter['email']}>")
        print(f"Subject : {out['subject']}")
        print(f"\n{out['body']}\n")
        print("─" * 60)

        ok = send_email(out["to_email"], out["to_name"], out["subject"],
                        out["body"], dry_run=not send)
        status = "Sent" if (ok and send) else ("Preview" if not send else "Failed")
        try:
            log_outreach(job, recruiter, out, status=status)
        except Exception as e:
            print(f"  ⚠ Sheets logging failed: {e}")

        if ok and send:
            sent += 1
            time.sleep(config.EMAIL_SEND_DELAY_SECONDS)
        elif not send:
            pass
        else:
            failed += 1

    print(f"\n{'═'*60}")
    print(f"  {'Sent' if send else 'Previewed'}: {sent if send else len(recruiters)-skipped-failed}"
          f" | Skipped: {skipped} | Failed: {failed}")
    if not send:
        print("  (preview mode — re-run with --send to actually send)")
    print(f"{'═'*60}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Targeted recruiter outreach")
    p.add_argument("--company", required=True, help="Company domain, e.g. twilio.com")
    p.add_argument("--title", required=True, help="Job title you applied to")
    p.add_argument("--jd", help="Path to a text file with the job description")
    p.add_argument("--max", type=int, default=5, help="Max recruiters (default 5)")
    p.add_argument("--send", action="store_true", help="Actually send (default: preview)")
    p.add_argument("--allow-unverified", action="store_true",
                   help="Include contacts without a Prospeo-verified email (bounce risk)")
    p.add_argument("--hook", help="A real, specific, current fact about the company/team "
                                   "(from web research) to open the email with")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    jd_text = ""
    if args.jd:
        jd_path = Path(args.jd)
        if not jd_path.exists():
            print(f"JD file not found: {args.jd}")
            sys.exit(1)
        jd_text = jd_path.read_text()

    try:
        run(args.company, args.title, jd_text, args.max, args.send, args.allow_unverified, args.hook)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
