# ============================================================
#  resume_selector.py
#  Picks which résumé variant (assets/resume*.pdf) to attach for a
#  given job, based on keywords in the title + JD text. Falls back
#  to the general résumé when nothing more specific matches.
# ============================================================

from __future__ import annotations

from pathlib import Path

from src.core import config

_VARIANTS = [
    # (resume filename, keywords that indicate this variant fits best)
    ("resume_de.pdf", [
        "data engineer", "data engineering", "analytics engineer", "etl",
        "data pipeline", "data platform", "dbt", "data warehouse",
    ]),
    ("resume_infra_cloud.pdf", [
        "infrastructure", "cloud engineer", "cloud infrastructure", "devops",
        "site reliability", "sre", "platform engineer", "systems engineer",
        "network engineer",
    ]),
]
_DEFAULT = "resume.pdf"


def select_resume(job: dict) -> str:
    """Return an absolute path to the résumé variant best matching this job.

    Checks the job title first (stronger signal), then the JD snippet.
    Falls back to the general résumé (assets/resume.pdf) if no variant
    file exists or nothing matches.
    """
    text = f"{job.get('title', '')} {job.get('description_snippet', '')}".lower()

    for filename, keywords in _VARIANTS:
        if any(kw in text for kw in keywords):
            path = Path(config.PROJECT_ROOT) / "assets" / filename
            if path.exists():
                return str(path)

    return str(Path(config.PROJECT_ROOT) / "assets" / _DEFAULT)
