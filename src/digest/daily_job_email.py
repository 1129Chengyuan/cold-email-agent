#!/usr/bin/env python3
# ============================================================
#  daily_job_email.py
#  Pull fresh explicit-junior SWE roles from the top-sponsor
#  ATS boards (Greenhouse/Lever/Ashby) and email them as a
#  clean HTML digest. Intended to run daily from launchd.
#
#  Usage:
#    python -m src.digest.daily_job_email --to you@example.com          # all roles
#    python -m src.digest.daily_job_email --to you@example.com --top 20 # cap at 20
#    python -m src.digest.daily_job_email --to you@example.com --new-only
#    python -m src.digest.daily_job_email --to you@example.com --dry-run
# ============================================================

from __future__ import annotations

import argparse
import datetime as dt
import sys
from email.mime.text import MIMEText
from urllib.parse import urlencode, quote

from src.jobs import h1b_greenhouse as hg
from src.ranking import fit_ranker
from src.core import gmail_sender  # reuse the authenticated Gmail service
from src.core import config

OUTREACH_PORT = 8770  # local outreach_server.py (the "Email recruiters" button)

# Big-name employers surfaced as "browse yourself" links instead of individual
# cards: their boards are huge (Amazon) or block scraping (Google/Apple/Tesla/
# Bloomberg) / would bloat the email. Single source of truth: jobs_site.py
# (which also renders them at the top of the public site).
from src.digest.jobs_site import BROWSE_LINKS


def _browse_section() -> str:
    """A compact row of pill links to big employers' own careers search pages."""
    pills = "".join(
        f'<a href="{url}" style="display:inline-block;margin:0 8px 8px 0;'
        f'padding:9px 15px;background:#f1f3f4;color:#1a56c4;font-size:12px;'
        f'font-weight:600;text-decoration:none;border-radius:18px">{name} &rarr;</a>'
        for name, url, _color in BROWSE_LINKS)
    return (
        '<tr><td style="padding:22px 6px 6px 6px">'
        '<div style="font-size:15px;font-weight:700;color:#202124">Browse these employers directly</div>'
        '<div style="font-size:12px;color:#80868b;margin-top:2px;margin-bottom:12px">'
        'Big or scrape-blocked boards — open each one’s software-engineer search and filter yourself.'
        '</div>'
        f'{pills}</td></tr>')


def _card_link(job: dict) -> str:
    """Real job URL, or — if a click tracker is configured — a tracker link that
    logs the company to the 'Job' sheet first, then redirects to the posting."""
    if not config.CLICK_TRACKER_URL:
        return job["url"]
    q = urlencode({"company": job["company"], "url": job["url"],
                   "title": job.get("title", "")})
    sep = "&" if "?" in config.CLICK_TRACKER_URL else "?"
    return f"{config.CLICK_TRACKER_URL}{sep}{q}"

# A calm, distinct color per ATS / source badge.
_ATS_COLOR = {"greenhouse": "#1a7f5a", "lever": "#5a4fcf", "ashby": "#b4531f",
              "smartrecruiters": "#0a6ed1", "workable": "#00756a",
              "amazon": "#c45500", "linkedin": "#0a66c2", "indeed": "#2557a7"}
# Monogram background palette (deterministic by first letter).
_MONO = ["#e8f0fe", "#e6f4ea", "#fce8e6", "#fef7e0", "#f3e8fd", "#e0f7fa"]


def _job_card(j: dict) -> str:
    """One clickable card (whole card links out). Rendered inside a 50%-width cell."""
    # Clean display name: Workday tokens are "tenant|pod|site" — show the tenant.
    company = j["company"].split("|")[0]
    letter = (company[:1] or "?").upper()
    mono_bg = _MONO[ord(letter) % len(_MONO)] if letter.isalpha() else _MONO[0]
    ats = j.get("ats", "")
    ats_color = _ATS_COLOR.get(ats, "#6b7280")
    new_badge = (
        '<span style="display:inline-block;background:#e6f4ea;color:#137333;'
        'font-size:10px;font-weight:700;letter-spacing:.03em;padding:2px 7px;'
        'border-radius:10px;margin-left:6px;vertical-align:middle">NEW</span>'
        if j.get("is_new") else "")
    grad_badge = (
        '<span style="display:inline-block;background:#e8f0fe;color:#1a56c4;'
        'font-size:10px;font-weight:700;letter-spacing:.03em;padding:2px 7px;'
        'border-radius:10px;margin-left:6px;vertical-align:middle">INTERNSHIP</span>'
        if j.get("new_grad") else "")
    seen = j.get("first_seen", j.get("updated_at", ""))

    # Fit score chip (color-graded) + reason, if the ranker ran.
    score = j.get("fit_score")
    fit_html = reason_html = ""
    if isinstance(score, int) and score >= 0:
        sc_bg, sc_fg = ("#e6f4ea", "#137333") if score >= 80 else \
                       ("#fef7e0", "#a56300") if score >= 60 else ("#f1f3f4", "#5f6368")
        fit_html = (f'<span style="display:inline-block;background:{sc_bg};color:{sc_fg};'
                    f'font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px">'
                    f'{score} fit</span>')
        if j.get("fit_reason"):
            reason_html = (f'<div style="font-size:11px;color:#80868b;margin-top:6px;'
                           f'line-height:1.4;font-style:italic;white-space:nowrap;'
                           f'overflow:hidden;text-overflow:ellipsis">{j["fit_reason"]}</div>')

    href = _card_link(j)
    # Button opens the local server, which fetches the full JD and copies it.
    rec_url = f"http://127.0.0.1:{OUTREACH_PORT}/jd?" + urlencode(
        {"company": j["company"], "title": j["title"], "ats": j.get("ats", ""),
         "job_id": j.get("job_id", "")}, quote_via=quote)
    # Upper block is one big job link (click the card -> job); the recruiter
    # button sits in its own row below (can't nest <a> inside <a>).
    return f"""<div style="border:1px solid #e6e8eb;border-radius:12px;background:#ffffff;
        padding:16px 16px 20px;height:276px;overflow:hidden;box-sizing:border-box">
      <a href="{href}" style="display:block;text-decoration:none;color:inherit;
         height:196px;overflow:hidden">
        <div style="margin-bottom:10px;white-space:nowrap">
          <span style="display:inline-block;width:34px;height:34px;border-radius:9px;
               background:{mono_bg};color:#3c4043;font-weight:700;font-size:15px;
               line-height:34px;text-align:center;vertical-align:middle">{letter}</span>
          <span style="font-size:13px;font-weight:600;color:#3c4043;margin-left:9px;
               vertical-align:middle">{company}</span>
          <span style="float:right">{fit_html}</span>
        </div>
        <div style="font-size:14px;font-weight:650;line-height:1.35;color:#1a73e8">{j['title']}{grad_badge}{new_badge}</div>
        <div style="font-size:12px;color:#5f6368;margin-top:5px;line-height:1.4">{j['location'] or 'Location N/A'}</div>
        {reason_html}
        <div style="margin-top:8px;font-size:11px;color:#80868b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          <span style="color:{ats_color};font-weight:600;text-transform:capitalize">{ats}</span>
          &nbsp;·&nbsp; first seen {seen}
        </div>
      </a>
      <a href="{rec_url}" target="_blank" style="display:block;margin-top:10px;text-align:center;
         background:#e8f0fe;color:#1a56c4;font-weight:700;font-size:12px;
         text-decoration:none;padding:8px 0;border-radius:8px">&#128203;&nbsp; Copy job description</a>
    </div>"""


def _cards_grid(jobs: list[dict], per_row: int = 4) -> str:
    """Lay cards out as fluid inline-block cells that WRAP to the screen width:
    up to `per_row` across on a wide screen, collapsing to 2 then 1 across as the
    screen narrows. Using inline-block (not fixed-width table cells) means the
    cards reflow on a phone even in clients that ignore media queries, e.g. the
    Gmail mobile app — which is why the old fixed 25%-wide cells looked cramped."""
    if not jobs:
        return ('<tr><td style="padding:28px;text-align:center;color:#80868b;'
                'border:1px dashed #dadce0;border-radius:12px">'
                'No explicit SWE/DE/Infra internship roles today. New postings surge in the fall/spring cycles.'
                '</td></tr>')
    max_w = max(240, 1200 // max(per_row, 1))   # ~300px per card at per_row=4
    cells = "".join(
        f'<div class="jcell" style="display:inline-block;width:100%;max-width:{max_w}px;'
        f'vertical-align:top;padding:6px;box-sizing:border-box;font-size:14px">'
        f'{_job_card(j)}</div>'
        for j in jobs)
    # font-size:0 / line-height:0 on the wrapper collapses the whitespace gaps
    # between inline-block cards; each .jcell resets its own font size.
    return (f'<tr><td align="center" style="font-size:0;line-height:0;padding:0">'
            f'{cells}</td></tr>')


def build_html(jobs: list[dict]) -> str:
    today = dt.date.today().strftime("%A, %B %-d, %Y")
    n_total = len(jobs)
    n_new = sum(1 for j in jobs if j.get("is_new"))
    n_boards = len(hg.valid_boards(include_custom=False))

    # Pin roles first seen today at the top, keep the rest (best-fit order) below.
    new_jobs = [j for j in jobs if j.get("is_new")]
    rest_jobs = [j for j in jobs if not j.get("is_new")]

    def _section(label: str, sub: str, items: list[dict]) -> str:
        if not items:
            return ""
        head = (f'<tr><td style="padding:18px 6px 6px 6px">'
                f'<div style="font-size:15px;font-weight:700;color:#202124">{label}'
                f'<span style="color:#9aa0a6;font-weight:600;font-size:13px">'
                f'&nbsp;·&nbsp;{len(items)}</span></div>'
                f'<div style="font-size:12px;color:#80868b;margin-top:2px">{sub}</div>'
                f'</td></tr>')
        body = (f'<tr><td><table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" style="table-layout:fixed">'
                f'{_cards_grid(items, per_row=4)}</table></td></tr>')
        return head + body

    if new_jobs:
        grid = (_section("🆕 New today", "First spotted today", new_jobs) +
                _section("All best-fit roles", "Still live, ranked by fit", rest_jobs))
    else:
        grid = (f'<tr><td><table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" style="table-layout:fixed">'
                f'{_cards_grid(jobs, per_row=4)}</table></td></tr>')

    new_chip = (f'<span style="display:inline-block;background:#e6f4ea;color:#137333;'
                f'font-size:12px;font-weight:600;padding:4px 12px;border-radius:20px;'
                f'margin-left:8px">{n_new} new</span>' if n_new else "")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light only">
<style>
  /* Backup for clients that honor media queries (Gmail web + app, Apple Mail):
     on phones give each card a full-width row and tighten the side padding. */
  @media only screen and (max-width:600px) {{
    .jcell {{ max-width:100% !important; }}
    .wrap-pad {{ padding-left:8px !important; padding-right:8px !important; }}
    .hdr-title {{ font-size:20px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#ffffff">
    <div class="wrap-pad" style="margin:0;padding:24px 12px;background:#ffffff;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:1280px">

            <!-- Header -->
            <tr><td style="padding:4px 6px 16px 6px">
              <div class="hdr-title" style="font-size:22px;font-weight:750;color:#202124;letter-spacing:-.01em">Fresh SWE/DE/Infra internships</div>
              <div style="font-size:13px;color:#5f6368;margin-top:4px">{today}</div>
              <div style="margin-top:12px">
                <span style="display:inline-block;background:#eef1f4;color:#3c4043;
                     font-size:12px;font-weight:600;padding:4px 12px;border-radius:20px">{n_total} roles</span>
                {new_chip}
              </div>
              <div style="font-size:12px;color:#80868b;margin-top:10px;line-height:1.5">
                Internship roles in Software Engineering, Data Engineering &amp; Infrastructure/Cloud
                from your top H-1B sponsor boards. US-only.
              </div>
            </td></tr>

            <!-- Job cards: NEW today section (if any) then all best-fit roles -->
            {grid}

            <!-- Browse-yourself links for big / scrape-blocked employers -->
            {_browse_section()}

            <!-- Footer -->
            <tr><td style="padding:16px 6px 4px 6px">
              <div style="border-top:1px solid #eaecef;padding-top:14px;
                   font-size:11px;color:#9aa0a6;line-height:1.5">
                Sent automatically by h1b-job-agent · watching {n_boards} sponsor boards
                across Greenhouse, Lever, Ashby, SmartRecruiters, Workable &amp; Workday. Big employers with their own
                boards (Amazon, Google, Microsoft, Apple, Tesla, Bloomberg, LinkedIn) are
                linked above to browse directly.<br>
                &ldquo;First seen&rdquo; is the date this tool first spotted the posting.
              </div>
            </td></tr>

          </table>
        </td></tr>
      </table>
    </div>
</body></html>"""


def send_digest(to_email: str, jobs: list[dict]) -> None:
    msg = MIMEText(build_html(jobs), "html")
    msg["To"] = to_email
    msg["From"] = config.SENDER_EMAIL
    n = len(jobs)
    msg["Subject"] = f"{n} fresh SWE/DE/Infra intern role{'s' if n != 1 else ''} — {dt.date.today():%b %-d}"
    gmail_sender.send_mime(msg)  # SMTP app-password when set, else Gmail API


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="recipient email for the digest")
    ap.add_argument("--top", type=int, default=40,
                    help="cap on number of roles per email (default: 40; pass 0 for no cap)")
    ap.add_argument("--new-only", action="store_true",
                    help="only include roles first seen today")
    ap.add_argument("--rank", action="store_true",
                    help="score fit with Gemini + drop no-sponsorship roles, sort by fit")
    ap.add_argument("--rank-limit", type=int, default=40,
                    help="max roles to score with Gemini (quota bound)")
    ap.add_argument("--dry-run", action="store_true", help="print instead of emailing")
    args = ap.parse_args()

    try:
        # Email cards use ORIGINAL sources only (Workday + Greenhouse/Lever/Ashby).
        # Amazon + the big-tech companies are surfaced as "browse yourself" links
        # in the digest instead of individual cards (keeps the email short).
        jobs = hg.daily_fresh_swe(us_only=True, new_only=args.new_only, limit=None,
                                  include_aggregator=False, include_custom=False)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Cross-email dedup: drop roles already sent in a previous digest.
    before_dedup = len(jobs)
    jobs = hg.filter_unemailed(jobs)
    print(f"  {before_dedup - len(jobs)} roles already emailed before — skipped")

    if args.rank and jobs:
        before = len(jobs)
        jobs = fit_ranker.enrich(jobs, limit=args.rank_limit)
        print(f"  ranked top {min(before, args.rank_limit)} by fit; "
              f"{before - len(jobs)} dropped (no sponsorship)")

    # Cap to the freshest N (default: no cap).
    if args.top:
        jobs = jobs[:args.top]

    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] emailing {len(jobs)} roles to {args.to}")
    for j in jobs:
        tag = " NEW" if j.get("is_new") else ""
        print(f"  {j.get('first_seen','')}  [{j['ats']}:{j['company']}]  {j['title']} - {j['location']}{tag}")

    if args.dry_run:
        print("(dry-run — no email sent; not marking roles as emailed)")
        return
    if not jobs:
        print("Nothing new to send — every current role was already emailed.")
        return
    send_digest(args.to, jobs)
    hg.mark_emailed(jobs, to_email=args.to)
    print(f"Digest emailed — {len(jobs)} roles sent and marked so they won't repeat.")


if __name__ == "__main__":
    main()
