# ============================================================
#  ats.py
#  Unified reader for the public ATS job-board APIs: Greenhouse,
#  Lever, Ashby, SmartRecruiters, Workable (+ curated Workday
#  endpoints and Amazon's native board). Each company hosts on ONE
#  of them; none offers a global cross-company search, so we probe
#  a company slug against each provider.
#
#  Every provider is normalized to the same job dict:
#    {company, ats, title, location, url, updated_at, job_id}
#
#  Public interface:
#    fetch(provider, slug)                 -> list[normalized job]
#    board_name(provider, slug)            -> str | None   (for verification)
#    is_junior_swe(title) / is_us(location)
# ============================================================

from __future__ import annotations

import datetime as dt
import re

import requests

TIMEOUT = 15
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# ── Title / location filters (strict, explicit-junior) ────────
# Must contain an actual SOFTWARE role keyword. Bare "engineer i" is NOT here
# on purpose — it matched mechanical / propulsion / civil / hardware "Engineer I"
# roles (e.g. Relativity Space, LG). We require a software-specific title.
_POSITIVE = [
    "software engineer", "software developer", "software development engineer",
    "swe", "backend engineer", "back end engineer", "back-end engineer",
    "frontend engineer", "front end engineer", "front-end engineer",
    "full stack engineer", "fullstack engineer", "full-stack engineer",
    "data engineer", "machine learning engineer", "ml engineer",
    "platform engineer", "infrastructure engineer", "devops engineer",
    "site reliability engineer", "mobile engineer", "ios engineer",
    "android engineer", "web developer", "member of technical staff",
    "applications developer", "programmer",
]
# User seeks INTERNSHIPS (SWE/Data Engineering/Infra), not full-time — a title
# must explicitly signal an internship/co-op to pass.
_JUNIOR = ["intern", "internship", "co-op", "coop", "co op"]
_SENIOR = ["senior", "staff", "principal", " lead", "lead ", "manager",
           "director", " ii", " iii", " iv", " 2", " 3", " 4", "sr.", "sr ",
           " l3", " l4", " l5", " l6", "distinguished", "architect", "head of"]
# Extra safety: reject non-software disciplines even if a keyword sneaks in.
_NONSOFTWARE = ["technical support", "support engineer", "sales engineer",
                "field service", "hardware", "mechanical", "electrical",
                "civil", "structural", "propulsion", "aerospace", "aerodynamic",
                "facilities", "validation", "manufacturing", "in training",
                "chemical", "biomedical", "optical", "materials",
                # talent-pool / pipeline postings that aren't real openings
                "talent community", "talent network", "talent pool",
                "expression of interest", "general application", "future opportunities"]


def is_explicit_junior(title: str) -> bool:
    """True only if the title explicitly signals an internship/co-op."""
    t = f" {title.lower().strip()} "
    return any(j in t for j in _JUNIOR)


def is_junior_swe(title: str) -> bool:
    """An internship-level SWE/Data/Infra role: a software title that explicitly
    signals an internship/co-op, is not senior, and is not a non-software discipline.
    """
    t = f" {title.lower().strip()} "
    if not any(p in t for p in _POSITIVE):
        return False
    if not is_explicit_junior(t):
        return False
    if any(s in t for s in _SENIOR):
        return False
    if any(n in t for n in _NONSOFTWARE):
        return False
    return True


def is_us(location: str) -> bool:
    loc = (location or "").lower()
    if not loc:
        return True
    non_us = ["china", "shanghai", "beijing", "shenzhen", "india", "bangalore",
              "bengaluru", "hyderabad", "pune", "gurgaon", "gurugram", "chennai",
              "mumbai", "delhi", "noida", "asia", "london", "uk",
              "united kingdom", "scotland", "edinburgh", "glasgow", "manchester",
              "wales", "cardiff", "belfast", "cork",
              "canada", "toronto", "vancouver", "montreal",
              "mexico", "brazil", "sao paulo", "ireland", "dublin", "germany",
              "berlin", "munich", "portugal", "lisbon", "singapore", "japan",
              "tokyo", "australia", "sydney", "france", "paris", "netherlands",
              "amsterdam", "poland", "warsaw", "spain", "madrid", "korea",
              "seoul", "hwaseong", "taiwan", "hsinchu", "taipei", "hong kong",
              "philippines", "manila", "vietnam", "malaysia", "thailand",
              "indonesia", "israel", "tel aviv", "sweden", "denmark", "norway",
              "finland", "italy", "switzerland", "zurich", "austria", "belgium",
              "czech", "prague", "romania", "ukraine", "turkey", "uae", "dubai",
              "saudi", "qatar", "argentina", "chile", "colombia", "costa rica",
              "new zealand", "emea", "apac"]
    return not any(x in loc for x in non_us)


# ── Provider: Greenhouse ──────────────────────────────────────
def _greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []) or []:
        out.append({
            "company": slug, "ats": "greenhouse", "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "updated_at": (j.get("updated_at") or "")[:10],
            "job_id": j.get("id"),
        })
    return out


def _greenhouse_name(slug: str) -> str | None:
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}",
                         timeout=TIMEOUT)
        return (r.json() or {}).get("name") if r.status_code == 200 else None
    except Exception:
        return None


# ── Provider: Lever ───────────────────────────────────────────
def _lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    data = r.json()
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        cat = p.get("categories") or {}
        created = p.get("createdAt")
        iso = ""
        if created:
            iso = dt.datetime.fromtimestamp(created / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "company": slug, "ats": "lever", "title": p.get("text", ""),
            "location": cat.get("location", ""),
            "url": p.get("hostedUrl", ""),
            "updated_at": iso,
            "job_id": p.get("id"),
            # Lever returns the full description in the list — capture it free.
            "description": p.get("descriptionPlain") or p.get("description", ""),
        })
    return out


# ── Provider: Ashby ───────────────────────────────────────────
_ASHBY_GQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
_ASHBY_GQL_QUERY = (
    "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {"
    " jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {"
    " jobPostings { id title locationName employmentType } } }"
)


def _ashby_frontend(slug: str) -> list[dict]:
    """Fallback for Ashby orgs whose public posting-api is disabled (e.g. Whatnot).
    Uses the same GraphQL endpoint the careers page itself calls."""
    r = requests.post(_ASHBY_GQL, timeout=TIMEOUT, headers={"Content-Type": "application/json"},
                      json={"operationName": "ApiJobBoardWithTeams",
                            "variables": {"organizationHostedJobsPageName": slug},
                            "query": _ASHBY_GQL_QUERY})
    if r.status_code != 200:
        return []
    board = ((r.json() or {}).get("data") or {}).get("jobBoard") or {}
    out = []
    for j in board.get("jobPostings", []) or []:
        out.append({
            "company": slug, "ats": "ashby", "title": j.get("title", ""),
            "location": j.get("locationName", ""),
            "url": f"https://jobs.ashbyhq.com/{slug}/{j.get('id','')}",
            "updated_at": "",  # not exposed here; first-seen tracking covers freshness
            "job_id": j.get("id"),
        })
    return out


def _ashby(slug: str) -> list[dict]:
    # 1) public posting API (has dates); 2) frontend GraphQL fallback if disabled
    r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=TIMEOUT)
    if r.status_code == 200:
        data = r.json() or {}
        out = []
        for j in data.get("jobs", []) or []:
            pub = j.get("publishedAt") or j.get("updatedAt") or ""
            out.append({
                "company": slug, "ats": "ashby", "title": j.get("title", ""),
                "location": j.get("location", "") or j.get("locationName", ""),
                "url": j.get("jobUrl", "") or j.get("applyUrl", ""),
                "updated_at": str(pub)[:10],
                "job_id": j.get("id"),
            })
        if out:
            return out
    return _ashby_frontend(slug)


# ── Provider: SmartRecruiters ─────────────────────────────────
# Public postings API; country comes back as a 2-letter code, so map the
# common ones to names the is_us() keyword filter understands.
_SR_COUNTRY = {
    "us": "US", "gb": "United Kingdom", "de": "Germany", "in": "India",
    "ca": "Canada", "mx": "Mexico", "br": "Brazil", "ie": "Ireland",
    "pt": "Portugal", "sg": "Singapore", "jp": "Japan", "au": "Australia",
    "fr": "France", "nl": "Netherlands", "pl": "Poland", "es": "Spain",
    "kr": "Korea", "tw": "Taiwan", "hk": "Hong Kong", "ph": "Philippines",
    "vn": "Vietnam", "my": "Malaysia", "th": "Thailand", "id": "Indonesia",
    "il": "Israel", "se": "Sweden", "dk": "Denmark", "no": "Norway",
    "fi": "Finland", "it": "Italy", "ch": "Switzerland", "at": "Austria",
    "be": "Belgium", "cz": "Czech", "ro": "Romania", "ua": "Ukraine",
    "tr": "Turkey", "ae": "UAE", "sa": "Saudi", "qa": "Qatar",
    "ar": "Argentina", "cl": "Chile", "co": "Colombia", "cr": "Costa Rica",
    "nz": "New Zealand", "cn": "China",
}


def _smartrecruiters(slug: str) -> list[dict]:
    base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    out, offset = [], 0
    while offset < 500:
        r = requests.get(base, params={"limit": 100, "offset": offset}, timeout=TIMEOUT)
        if r.status_code != 200:
            break
        data = r.json() or {}
        posts = data.get("content", []) or []
        if not posts:
            break
        for p in posts:
            loc = p.get("location") or {}
            country = (loc.get("country") or "").lower()
            parts = [loc.get("city", ""), loc.get("region", ""),
                     _SR_COUNTRY.get(country, country.upper())]
            out.append({
                "company": slug, "ats": "smartrecruiters",
                "title": p.get("name", ""),
                "location": ", ".join(x for x in parts if x),
                "url": f"https://jobs.smartrecruiters.com/{slug}/{p.get('id', '')}",
                "updated_at": (p.get("releasedDate") or "")[:10],
                "job_id": p.get("id"),
                # SR exposes a definitive ISO country code — keep it so the US
                # filter doesn't depend on keyword-matching the location string.
                "country_code": country,
            })
        offset += 100
        if offset >= (data.get("totalFound") or 0):
            break
    return out


def _smartrecruiters_name(slug: str) -> str | None:
    """SR has no company endpoint, but every posting embeds company.name."""
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                         params={"limit": 1}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        content = (r.json() or {}).get("content") or []
        return (content[0].get("company") or {}).get("name") if content else None
    except Exception:
        return None


# ── Provider: Workable ────────────────────────────────────────
# Public widget API: one GET returns the whole board (plus the company name,
# so Workable boards are name-verifiable like Greenhouse).
def _workable(slug: str) -> list[dict]:
    r = requests.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
                     timeout=TIMEOUT, headers={"User-Agent": _UA})
    if r.status_code != 200:
        return []
    data = r.json() or {}
    out = []
    for j in data.get("jobs", []) or []:
        parts = [j.get("city", ""), j.get("state", ""), j.get("country", "")]
        out.append({
            "company": slug, "ats": "workable",
            "title": j.get("title", ""),
            "location": ", ".join(x for x in parts if x),
            "url": j.get("url") or f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}/",
            "updated_at": (j.get("published_on") or "")[:10],
            "job_id": j.get("shortcode") or j.get("code"),
        })
    return out


def _workable_name(slug: str) -> str | None:
    try:
        r = requests.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
                         timeout=TIMEOUT, headers={"User-Agent": _UA})
        return (r.json() or {}).get("name") if r.status_code == 200 else None
    except Exception:
        return None


# ── Provider: Workday ─────────────────────────────────────────
# Workday has no name search and every company has a unique
# tenant/pod/site, so the "slug" here is a composite "tenant|pod|site".
# Endpoint: https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
def _workday(slug: str) -> list[dict]:
    try:
        tenant, pod, site = slug.split("|")
    except ValueError:
        return []
    base = f"https://{tenant}.{pod}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    out, offset = [], 0
    # Narrow with searchText and page a few times (Workday caps limit at 20).
    while offset < 200:
        try:
            r = requests.post(api, timeout=TIMEOUT,
                              headers={"Content-Type": "application/json", "Accept": "application/json"},
                              json={"limit": 20, "offset": offset, "searchText": "software engineer",
                                    "appliedFacets": {}})
            if r.status_code != 200:
                break
            data = r.json() or {}
        except Exception:
            break
        posts = data.get("jobPostings", []) or []
        if not posts:
            break
        for p in posts:
            ext = p.get("externalPath", "")
            out.append({
                "company": slug, "ats": "workday", "title": p.get("title", ""),
                "location": p.get("locationsText", ""),
                "url": f"{base}/en-US/{site}{ext}",
                "updated_at": "",  # only relative "Posted N days ago"; first-seen covers it
                "job_id": ext,
            })
        offset += 20
        if offset >= (data.get("total") or 0):
            break
    return out


# ── Provider: Amazon (native board — amazon.jobs) ─────────────
# Amazon runs its own board with a clean public JSON search. It is NOT
# slug-based — there's one global board — so `slug` is ignored. We pull the
# most-recent US software roles; the pipeline's junior/US filters narrow them.
# Included via h1b_greenhouse.CUSTOM_BOARDS, not the sponsor-slug resolver.
def _amazon_date(s: str) -> str:
    """Parse amazon.jobs 'posted_date' (e.g. 'July  1, 2026') -> 'YYYY-MM-DD'."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    try:
        return dt.datetime.strptime(s, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _amazon(slug: str = "amazon") -> list[dict]:
    base = "https://www.amazon.jobs"
    out = []
    for offset in range(0, 500, 100):  # a few pages of the freshest roles
        try:
            r = requests.get(
                f"{base}/en/search.json", timeout=TIMEOUT,
                headers={"User-Agent": _UA},
                params={"base_query": "software engineer", "country": "USA",
                        "sort": "recent", "result_limit": 100, "offset": offset})
            if r.status_code != 200:
                break
            jobs = (r.json() or {}).get("jobs", []) or []
        except Exception:
            break
        if not jobs:
            break
        for j in jobs:
            out.append({
                "company": "amazon", "ats": "amazon",
                "title": j.get("title", ""),
                "location": j.get("normalized_location", "") or j.get("location", ""),
                "url": base + (j.get("job_path", "") or ""),
                "updated_at": _amazon_date(j.get("posted_date", "")),
                "job_id": str(j.get("id_icims") or j.get("id") or ""),
                # amazon.jobs returns the JD inline — capture it for fit ranking.
                "description": _strip_html(j.get("description", "")),
            })
    return out


_PROVIDERS = {"greenhouse": _greenhouse, "lever": _lever,
              "ashby": _ashby, "workday": _workday, "amazon": _amazon,
              "smartrecruiters": _smartrecruiters, "workable": _workable}


def fetch(provider: str, slug: str) -> list[dict]:
    """Normalized jobs for one company on one provider. [] on any error."""
    try:
        return _PROVIDERS[provider](slug)
    except Exception:
        return []


def board_name(provider: str, slug: str) -> str | None:
    """Company name for verification (Greenhouse/SmartRecruiters/Workable
    expose one; Lever/Ashby don't — those are verified by slug strength)."""
    if provider == "greenhouse":
        return _greenhouse_name(slug)
    if provider == "smartrecruiters":
        return _smartrecruiters_name(slug)
    if provider == "workable":
        return _workable_name(slug)
    return None


# ── Job description (on-demand; for sponsorship check + fit ranking) ──
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    import html
    return html.unescape(_TAG_RE.sub(" ", s or "")).replace("\xa0", " ")


_ASHBY_POST_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {"
    " jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName,"
    " jobPostingId: $jobPostingId) { descriptionHtml } }"
)


def description(job: dict) -> str:
    """Best-effort full JD text for one job. '' if unavailable."""
    # Inline JD already captured at fetch time (Amazon native, aggregator, Lever).
    if job.get("description"):
        return job["description"]
    prov, slug, jid = job.get("ats"), job.get("company"), job.get("job_id")
    try:
        if prov == "lever":
            if job.get("description"):
                return job["description"]  # captured in the list fetch
            r = requests.get(f"https://api.lever.co/v0/postings/{slug}/{jid}?mode=json",
                             timeout=TIMEOUT)
            if r.status_code == 200:
                p = r.json() or {}
                parts = [_strip_html(p.get("descriptionPlain") or p.get("description", ""))]
                for lst in p.get("lists", []) or []:
                    parts.append((lst.get("text", "") + " " + _strip_html(lst.get("content", ""))).strip())
                return "\n".join(x for x in parts if x)
        if prov == "greenhouse":
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}", timeout=TIMEOUT)
            if r.status_code == 200:
                return _strip_html((r.json() or {}).get("content", ""))
        if prov == "ashby":
            r = requests.post(
                "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting",
                timeout=TIMEOUT, headers={"Content-Type": "application/json"},
                json={"operationName": "ApiJobPosting",
                      "variables": {"organizationHostedJobsPageName": slug, "jobPostingId": jid},
                      "query": _ASHBY_POST_QUERY})
            if r.status_code == 200:
                jp = ((r.json() or {}).get("data") or {}).get("jobPosting") or {}
                return _strip_html(jp.get("descriptionHtml", ""))
        if prov == "workday":
            tenant, pod, site = slug.split("|")
            r = requests.get(
                f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{jid}",
                timeout=TIMEOUT, headers={"Accept": "application/json"})
            if r.status_code == 200:
                info = (r.json() or {}).get("jobPostingInfo") or {}
                return _strip_html(info.get("jobDescription", ""))
        if prov == "smartrecruiters":
            r = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}",
                timeout=TIMEOUT)
            if r.status_code == 200:
                sections = ((r.json() or {}).get("jobAd") or {}).get("sections") or {}
                return "\n".join(
                    _strip_html(s.get("text", ""))
                    for s in sections.values() if isinstance(s, dict) and s.get("text"))
        if prov == "workable":
            r = requests.get(
                f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{jid}",
                timeout=TIMEOUT, headers={"User-Agent": _UA})
            if r.status_code == 200:
                p = r.json() or {}
                return "\n".join(_strip_html(p.get(k, ""))
                                 for k in ("description", "requirements", "benefits")
                                 if p.get(k))
    except Exception:
        pass
    return ""
