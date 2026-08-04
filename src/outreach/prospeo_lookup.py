# ============================================================
#  prospeo_lookup.py
#  Finds the best recruiter email for a company via Prospeo.io.
#  Free tier: ~75 credits/month.
#
#  Two-step flow (new Prospeo API):
#    1. search-person  → find recruiters at the company domain
#                        (returns names + person_id, email hidden)
#    2. enrich-person  → reveal the verified email for the best match
#
#  Public interface:
#    find_recruiter(company_name, company_domain) -> dict | None
#    batch_find_recruiters(jobs) -> list[dict]
# ============================================================

from __future__ import annotations

import time
from typing import Optional

import requests
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.core import config

SEARCH_PERSON = "https://api.prospeo.io/search-person"
ENRICH_PERSON = "https://api.prospeo.io/enrich-person"

# Statuses that mean "this key is done" (out of credits / bad key / rate
# limited), not a transient server hiccup — no point retrying the same key.
_KEY_DEAD_STATUSES = {401, 402, 403, 429}


class ProspeoKeyExhausted(RuntimeError):
    """A Prospeo key returned an out-of-credits / auth / rate-limit status."""


_dead_keys: set[str] = set()   # keys exhausted this run

# Job titles we ask Prospeo to search for (recruiter / talent / HR)
RECRUITER_SEARCH_TITLES = [
    "Technical Recruiter",
    "Engineering Recruiter",
    "Recruiter",
    "Talent Acquisition",
    "Talent Acquisition Partner",
    "Recruiting",
    "University Recruiter",
    "Technical Sourcer",
    "People Partner",
]

RECRUITER_TITLE_KEYWORDS = [
    "recruiter", "talent acquisition", "talent partner", "recruiting",
    "talent sourcer", "sourcer", "hr partner", "people partner",
    "staffing", "human resources", "people operations", "university recruiter",
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_not_exception_type(ProspeoKeyExhausted))
def _post_with_key(url: str, payload: dict, key: str) -> dict:
    """POST to Prospeo with one key, retrying only on transient errors —
    an exhausted/bad key fails fast so the caller can try the next one."""
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-KEY": key,
        },
        timeout=30,
    )
    if resp.status_code in _KEY_DEAD_STATUSES:
        raise ProspeoKeyExhausted(f"prospeo key …{key[-4:]}: HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def _post(url: str, payload: dict) -> dict:
    """POST to Prospeo, cycling through PROSPEO_API_KEY (comma-separated —
    several free-trial keys can be stacked) once a key runs out of credits."""
    if not config.PROSPEO_API_KEYS:
        raise RuntimeError("PROSPEO_API_KEY not set")
    last_err: Exception | None = None
    for key_i, key in enumerate(config.PROSPEO_API_KEYS):
        if key in _dead_keys:
            continue
        try:
            return _post_with_key(url, payload, key)
        except ProspeoKeyExhausted as e:
            _dead_keys.add(key)
            print(f"  ⚠ prospeo key #{key_i + 1}/{len(config.PROSPEO_API_KEYS)} exhausted, switching: {e}")
            last_err = e
    raise last_err or RuntimeError("all PROSPEO_API_KEY entries exhausted")


def _title_is_recruiter(title: str) -> bool:
    title_lower = (title or "").lower()
    return any(kw in title_lower for kw in RECRUITER_TITLE_KEYWORDS)


def _score_person(p: dict) -> int:
    """Higher = better recruiter contact."""
    score = 0
    title = (p.get("job_title") or "").lower()
    if "technical" in title or "engineering" in title or "software" in title:
        score += 3
    if "recruiter" in title or "recruiting" in title:
        score += 2
    if "talent" in title:
        score += 2
    if "university" in title or "campus" in title or "early career" in title:
        score += 2   # great for new-grad outreach
    if "people" in title or "hr" in title or "human resources" in title:
        score += 1
    if "senior" in title or "lead" in title or "head" in title:
        score += 1
    return score


def _search_recruiters(company_domain: str, us_only: bool = True) -> list[dict]:
    """Return a list of recruiter-ish people at the domain (emails hidden).

    If us_only is True, restrict to US-based people via Prospeo's
    person_location_search filter (no extra credit cost for search filters).
    """
    filters = {
        "company": {"websites": {"include": [company_domain]}},
        "person_job_title": {"include": RECRUITER_SEARCH_TITLES},
    }
    if us_only:
        filters["person_location_search"] = {"include": ["United States"]}

    payload = {"page": 1, "filters": filters}
    data = _post(SEARCH_PERSON, payload)
    results = data.get("results", []) or []

    people = []
    for r in results:
        person = r.get("person", {}) or {}
        title = (person.get("current_job_title")
                 or person.get("job_title")
                 or person.get("headline", ""))
        people.append({
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", ""),
            "name": person.get("full_name")
                    or f"{person.get('first_name','')} {person.get('last_name','')}".strip()
                    or "Recruiting Team",
            "job_title": title,
            "person_id": person.get("person_id", ""),
            "linkedin_url": person.get("linkedin_url", ""),
        })
    return people


def _reveal_email(person: dict, company_domain: str) -> Optional[str]:
    """Enrich a single person to reveal their verified work email."""
    data_payload: dict = {}
    if person.get("person_id"):
        data_payload["person_id"] = person["person_id"]
    else:
        if not (person.get("first_name") and person.get("last_name")):
            return None
        data_payload = {
            "first_name": person["first_name"],
            "last_name": person["last_name"],
            "company_website": company_domain,
        }

    try:
        data = _post(ENRICH_PERSON, {
            "only_verified_email": False,
            "data": data_payload,
        })
    except Exception as exc:
        print(f"  ⚠ Enrich failed for {person.get('name')}: {exc}")
        return None

    p = data.get("person", {}) or {}
    email_obj = p.get("email")

    # email may be a dict {status, revealed, email} or a plain string
    if isinstance(email_obj, dict):
        if email_obj.get("revealed") and email_obj.get("email") and "*" not in email_obj["email"]:
            return email_obj["email"]
        return None
    if isinstance(email_obj, str) and email_obj and "*" not in email_obj:
        return email_obj
    return None


def find_recruiter(company_name: str, company_domain: str) -> Optional[dict]:
    """
    Find a recruiter + verified email at the company.
    Returns dict: name, first_name, title, email, linkedin_url, company.
    Returns None if nothing usable found.
    """
    if not company_domain:
        print(f"  ⚠ No company domain for {company_name} — skipping lookup")
        return None

    print(f"  🔎 Prospeo search: {company_name} ({company_domain})")

    try:
        people = _search_recruiters(company_domain)
    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:200]
        except Exception:
            pass
        print(f"  ⚠ Prospeo search error: {e} {body}")
        return None
    except Exception as exc:
        print(f"  ⚠ Prospeo search error: {exc}")
        return None

    if not people:
        print(f"  ℹ No recruiters found for {company_name}")
        return None

    # Prefer real recruiters; rank best-first
    recruiters = [p for p in people if _title_is_recruiter(p.get("job_title", ""))]
    pool = recruiters if recruiters else people
    pool.sort(key=_score_person, reverse=True)

    # Try to reveal an email, best candidate first (stop at first success)
    for cand in pool[:3]:   # cap reveals to protect credits
        email = _reveal_email(cand, company_domain)
        if email:
            result = {
                "name": cand.get("name", "Recruiting Team"),
                "first_name": cand.get("first_name", ""),
                "title": cand.get("job_title") or "Recruiter",
                "email": email,
                "linkedin_url": cand.get("linkedin_url", ""),
                "company": company_name,
            }
            print(f"  ✅ Found: {result['name']} <{result['email']}>")
            return result

    print(f"  ℹ No verified email revealed for {company_name}")
    return None


def batch_find_recruiters(jobs: list[dict], delay: float = 1.5) -> list[dict]:
    """Add recruiter info to each job; skip jobs with no email found."""
    enriched = []
    for job in jobs:
        recruiter = find_recruiter(
            company_name=job["company"],
            company_domain=job.get("company_domain", ""),
        )
        if recruiter:
            job["recruiter"] = recruiter
            enriched.append(job)
        else:
            print(f"  ⏭ Skipping {job['company']} — no recruiter email found")
        time.sleep(delay)
    return enriched


# ── Quick test ───────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("── SEARCH RAW ─────────────────────────────")
    try:
        raw = _post(SEARCH_PERSON, {
            "page": 1,
            "filters": {
                "company": {"websites": {"include": ["stripe.com"]}},
                "person_job_title": {"include": RECRUITER_SEARCH_TITLES},
            },
        })
        print(json.dumps(raw, indent=2)[:1500])
    except Exception as e:
        print(f"Search failed: {e}")

    print("\n── FULL LOOKUP ────────────────────────────")
    result = find_recruiter("Stripe", "stripe.com")
    print(result if result else "No recruiter found")
