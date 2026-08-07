# ============================================================
#  bounce_retry.py
#  Close the loop on pattern-guessed cold emails:
#    1. Read the Gmail inbox (IMAP) for delivery-failure bounces.
#    2. For each bounced recruiter, try the NEXT email-name pattern
#       (first.last -> flast -> first_last -> …) and resend the same
#       message, up to --max-retries times (default 3).
#
#  Sends are tracked in a PRIVATE, gitignored SQLite file
#  (data/outreach_state.db) so we know each recruiter's name, the
#  message, and which address patterns have already been tried.
#
#  Usage:
#    python -m src.outreach.bounce_retry --check                 # report bounces + plan
#    python -m src.outreach.bounce_retry --retry --dry-run       # show what it would resend
#    python -m src.outreach.bounce_retry --retry                 # actually resend
#    python -m src.outreach.bounce_retry --retry --max-retries 2
#
#  Reading the inbox needs GMAIL_APP_PASSWORD (IMAP must be enabled in Gmail).
# ============================================================

from __future__ import annotations

import argparse
import datetime as dt
import email
import imaplib
import re
import sqlite3
from email.header import decode_header, make_header
from pathlib import Path

from src.core import config
from src.core.gmail_sender import send_email

STATE_DB = str(Path(config.PROJECT_ROOT) / "data" / "outreach_state.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach_sends (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  first TEXT, last TEXT, domain TEXT, name TEXT, company TEXT,
  subject TEXT, body TEXT,
  tried TEXT,             -- comma-separated addresses already tried
  current_email TEXT,     -- most recent address used
  attempts INTEGER DEFAULT 1,
  status TEXT DEFAULT 'sent',   -- sent | retried | exhausted | send_error
  updated_at TEXT
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(STATE_DB)
    c.row_factory = sqlite3.Row
    c.execute(_SCHEMA)
    return c


# ── Email-name patterns, most-common first ───────────────────
def candidate_emails(first: str, last: str, domain: str) -> list[str]:
    """Ordered candidate addresses for a person. Last name is stripped of
    spaces/hyphens (e.g. 'Shepard Franklin' -> 'shepardfranklin').

    If we've already confirmed a pattern for this domain from a past send
    (see dominant_pattern_for_domain), it's tried first."""
    f = re.sub(r"[^a-z]", "", (first or "").lower())
    l = re.sub(r"[^a-z]", "", (last or "").lower())
    if not f or not domain:
        return []
    fi, li = f[:1], l[:1]
    shapes = {
        "first.last": f"{f}.{l}", "flast": f"{fi}{l}", "first": f,
        "first_last": f"{f}_{l}", "firstlast": f"{f}{l}",
        "f.last": f"{fi}.{l}", "first.l": f"{f}.{li}", "firstl": f"{f}{li}",
    }
    # order = most common patterns first, so the retries cover first.last,
    # flast, first@, and first_last (the four dominant company formats)
    order = ["first.last", "flast", "first", "first_last", "firstlast", "f.last",
             "first.l", "firstl"] if l else ["first"]

    known = dominant_pattern_for_domain(domain) if l else None
    if known and known in order:
        order = [known] + [k for k in order if k != known]

    out, seen = [], set()
    for key in order:
        p = shapes[key]
        if not p or p.endswith(".") or p.startswith("."):
            continue
        e = f"{p}@{domain}"
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


# ── Reuse patterns already confirmed for a domain ─────────────
def _classify(local_part: str, f: str, l: str) -> str | None:
    """Which pattern shape does this local-part (e.g. 'jane.doe') match?"""
    fi, li = f[:1], l[:1]
    shapes = {
        f"{f}.{l}": "first.last", f"{fi}{l}": "flast", f: "first",
        f"{f}_{l}": "first_last", f"{f}{l}": "firstlast",
        f"{fi}.{l}": "f.last", f"{f}.{li}": "first.l", f"{f}{li}": "firstl",
    }
    return shapes.get(local_part)


def dominant_pattern_for_domain(domain: str) -> str | None:
    """Look at addresses we've actually sent to at this domain before
    (data/outreach_state.db) and return the most common pattern shape,
    preferring Prospeo-verified sends over unconfirmed guesses. Returns
    None if we have no history for this domain. Pure lookup — spends no
    API credits and does no network I/O."""
    c = _conn()
    rows = c.execute("SELECT first, last, current_email, status FROM outreach_sends "
                     "WHERE domain=?", (domain,)).fetchall()
    c.close()
    if not rows:
        return None

    from collections import Counter
    verified, all_seen = Counter(), Counter()
    for r in rows:
        f = re.sub(r"[^a-z]", "", (r["first"] or "").lower())
        l = re.sub(r"[^a-z]", "", (r["last"] or "").lower())
        local = (r["current_email"] or "").split("@")[0].lower()
        key = _classify(local, f, l)
        if not key:
            continue
        all_seen[key] += 1
        if r["status"] in ("retried_verified", "retried"):
            verified[key] += 1

    if verified:
        return verified.most_common(1)[0][0]
    if all_seen:
        return all_seen.most_common(1)[0][0]
    return None


# ── Record a send (call this from the outreach flow) ─────────
def record_send(first: str, last: str, domain: str, name: str, company: str,
                subject: str, body: str, emailed: str, status: str = "sent") -> None:
    c = _conn()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    row = c.execute("SELECT id, tried, attempts FROM outreach_sends "
                    "WHERE lower(first)=? AND lower(last)=? AND domain=?",
                    (first.lower(), last.lower(), domain)).fetchone()
    if row:
        tried = {e for e in (row["tried"] or "").split(",") if e} | {emailed}
        c.execute("UPDATE outreach_sends SET tried=?, current_email=?, attempts=?, "
                  "status=?, subject=?, body=?, name=?, company=?, updated_at=? WHERE id=?",
                  (",".join(sorted(tried)), emailed, row["attempts"] + 1, status,
                   subject, body, name, company, now, row["id"]))
    else:
        c.execute("INSERT INTO outreach_sends (first,last,domain,name,company,subject,"
                  "body,tried,current_email,attempts,status,updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                  (first, last, domain, name, company, subject, body,
                   emailed, emailed, status, now))
    c.commit()
    c.close()


def send_tracked(first: str, last: str, domain: str, name: str, company: str,
                 subject: str, body: str, dry_run: bool = False) -> str | None:
    """Send the first-choice pattern and record it. Returns the address used."""
    cands = candidate_emails(first, last, domain)
    if not cands:
        return None
    to = cands[0]
    if dry_run:
        print(f"  [dry-run] would send to {to} ({name})")
        return to
    ok = send_email(to, name, subject, body)
    record_send(first, last, domain, name, company, subject, body, to,
                status="sent" if ok else "send_error")
    return to if ok else None


# ── Read the inbox for bounces ───────────────────────────────
def _hdr(v: str) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def fetch_bounced(since_days: int = 3) -> set[str]:
    """Return the set of recipient addresses that hard-bounced recently."""
    if not config.GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD not set — cannot read inbox via IMAP.")
    since = (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
    M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    M.login(config.SENDER_EMAIL, config.GMAIL_APP_PASSWORD)
    M.select("INBOX")
    failed: set[str] = set()
    for frm in ("mailer-daemon", "postmaster"):
        _, data = M.search(None, "SINCE", since, "FROM", frm)
        for i in data[0].split():
            _, d = M.fetch(i, "(BODY.PEEK[TEXT])")
            body = d[0][1].decode("utf-8", "ignore") if d and d[0] else ""
            for addr in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", body):
                a = addr.lower()
                if any(x in a for x in ("mailer-daemon", "googlemail", "google.com",
                                        "postmaster")) or a == config.SENDER_EMAIL.lower():
                    continue
                failed.add(a)
    M.logout()
    return failed


# ── Retry bounced recruiters with the next pattern ───────────
def retry_bounced(max_retries: int = 3, dry_run: bool = False,
                  since_days: int = 3) -> list[dict]:
    bounced = fetch_bounced(since_days)
    c = _conn()
    rows = c.execute("SELECT * FROM outreach_sends").fetchall()
    actions = []
    for r in rows:
        if (r["current_email"] or "").lower() not in bounced:
            continue
        if r["status"] == "exhausted":
            continue
        tried = {e for e in (r["tried"] or "").split(",") if e}
        cands = [e for e in candidate_emails(r["first"], r["last"], r["domain"])
                 if e not in tried]
        retries_done = r["attempts"] - 1
        if retries_done >= max_retries or not cands:
            c.execute("UPDATE outreach_sends SET status='exhausted', updated_at=? WHERE id=?",
                      (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), r["id"]))
            actions.append({"name": r["name"], "bounced": r["current_email"],
                            "action": "exhausted (no more patterns / max retries)"})
            continue
        nxt = cands[0]
        if dry_run:
            actions.append({"name": r["name"], "bounced": r["current_email"],
                            "action": f"would retry -> {nxt}",
                            "remaining_after": max_retries - retries_done - 1})
        else:
            ok = send_email(nxt, r["name"], r["subject"], r["body"])
            tried.add(nxt)
            c.execute("UPDATE outreach_sends SET tried=?, current_email=?, attempts=?, "
                      "status=?, updated_at=? WHERE id=?",
                      (",".join(sorted(tried)), nxt, r["attempts"] + 1,
                       "retried" if ok else "send_error",
                       dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), r["id"]))
            actions.append({"name": r["name"], "bounced": r["current_email"],
                            "action": f"{'resent' if ok else 'SEND FAILED'} -> {nxt}"})
    c.commit()
    c.close()
    return actions


def main():
    ap = argparse.ArgumentParser(description="Check inbox for bounces and retry with other email patterns")
    ap.add_argument("--check", action="store_true", help="report bounces + the retry plan (no send)")
    ap.add_argument("--retry", action="store_true", help="resend the next pattern to bounced recruiters")
    ap.add_argument("--dry-run", action="store_true", help="with --retry, print instead of sending")
    ap.add_argument("--max-retries", type=int, default=3, help="max resends per recruiter (default 3)")
    ap.add_argument("--since-days", type=int, default=3, help="how far back to scan the inbox")
    args = ap.parse_args()

    if args.check:
        bounced = fetch_bounced(args.since_days)
        print(f"Bounced addresses found in inbox ({len(bounced)}):")
        for b in sorted(bounced):
            print(f"  {b}")
        plan = retry_bounced(args.max_retries, dry_run=True, since_days=args.since_days)
        print(f"\nRetry plan ({len(plan)} recruiter(s) matched to tracked sends):")
        for p in plan:
            print(f"  {p['name']:24} {p['bounced']:34} -> {p['action']}")
        return

    if args.retry:
        actions = retry_bounced(args.max_retries, dry_run=args.dry_run, since_days=args.since_days)
        if not actions:
            print("No tracked bounces to retry.")
        for a in actions:
            print(f"  {a['name']:24} {a['bounced']:34} {a['action']}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
