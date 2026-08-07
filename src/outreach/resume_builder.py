# ============================================================
#  resume_builder.py — standalone ATS résumé generator for when you
#  actually apply (NOT used by cold-email outreach, which sticks to
#  the static template résumés in resume_selector.py).
#
#  Compiles a résumé PDF per job from assets/resume_template.tex,
#  reordering/selecting bullets and projects from assets/experience.json
#  by relevance to the specific JD (real ATS keyword optimization),
#  while keeping the exact same proven one-page LaTeX layout — so
#  there's no risk of an LLM-driven layout break like a free rewrite
#  would have. Bullets are rendered in strict Google XYZ format
#  ("Accomplished X, as measured by Y, by doing Z") via each
#  experience.json entry's "xyz_text" field.
#
#  Falls back to resume_selector's static variants on ANY failure
#  (no LaTeX toolchain, compile error, overflow to 2 pages).
#
#  Usage:
#    python -m src.outreach.resume_builder --title "Data Engineer Intern" \
#        --jd jd.txt --out ~/Desktop/resume_acme.pdf
# ============================================================

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.core import config
from src.ranking import resume_kb
from src.outreach.cover_letter_generator import _METRIC_RE  # reuse the same metric regex
from src.outreach.resume_selector import select_resume

TEMPLATE_PATH = Path(config.PROJECT_ROOT) / "assets" / "resume_template.tex"

GFS_BULLET_IDS = ["gfs-cost-optimization-engine", "gfs-incremental-data-engine",
                   "gfs-log-parsing-pipeline"]

# (project key -> fixed heading/date, bullet ids in FALLBACK order if untied)
PROJECTS = {
    "smalldb": {
        "heading": r"\textbf{SmallDB: High-Performance LSM-Tree Database} $|$ \emph{C++20, Linux}",
        "date": "Aug. 2025 -- Present",
        "bullet_ids": ["smalldb-lsm-tree-engine", "smalldb-wal-durability",
                        "smalldb-bloom-filter-reads"],
    },
    "nba": {
        "heading": r"\textbf{NBA Analytics Data Pipeline} $|$ \emph{Python, PySpark, PostgreSQL, dbt, Airflow}",
        "date": "Dec. 2025 -- Present",
        "bullet_ids": ["nba-pipeline-etl-airflow", "nba-pipeline-postgres-schema"],
    },
    "microservices": {
        "heading": r"\textbf{Containerized Microservices \& ETL Pipeline} $|$ \emph{Docker, Airflow, Python, SQL}",
        "date": "Dec. 2025 -- Present",
        "bullet_ids": ["microservices-ingestion-engine", "microservices-cicd",
                        "microservices-observability"],
    },
    "robotsim": {
        "heading": r"\textbf{Autonomous Robot Simulation Parallelization} $|$ \emph{Python, PyTorch, C++}",
        "date": "Dec. 2024 -- May 2025",
        "bullet_ids": ["robot-sim-gpu-parallelization"],
    },
}

SKILLS_BLOCK = (
    r"\textbf{Languages}{: C++20, C, Python, Java, SQL (PostgreSQL, MySQL), Bash} \\" "\n"
    r"    \textbf{Cloud \& Infrastructure}{: Google Cloud Platform (Cloud Run, Cloud Scheduler, "
    r"Pub/Sub, BigQuery, GCS, Secret Manager), Terraform (IaC), Docker, Linux Systems Programming, "
    r"CI/CD, GitHub Actions} \\" "\n"
    r"    \textbf{Data Infrastructure \& Orchestration}{: BigQuery, Apache Spark (PySpark), "
    r"Apache Airflow, dbt, Dataform, Pandas, NumPy, Scikit-Learn} \\" "\n"
    r"    \textbf{Systems \& Architecture}{: Concurrent Programming, Distributed Systems, "
    r"Multithreading, Microservices, Memory Management, Object-Oriented Design, gRPC} \\" "\n"
    r"    \textbf{Developer Tools}{: Git, JUnit, PyTorch, Linux/Unix, Docker}"
)

RESEARCH_BULLET_ID = "astar-transformer-profiling"


def _research_section(bullet_tex: str) -> str:
    return (
        r"\section{Research Experience}" "\n"
        r"\resumeSubHeadingListStart" "\n"
        r"  \resumeSubheading" "\n"
        r"    {Research Intern (Infrastructure)}{May 2025 -- Aug. 2025}" "\n"
        r"    {A*STAR Institute of High Performance Computing}{Singapore/Remote}" "\n"
        r"    \resumeItemListStart" "\n"
        f"      \\resumeItem{{{bullet_tex}}}\n"
        r"    \resumeItemListEnd" "\n"
        r"\resumeSubHeadingListEnd"
    )


PUBLICATIONS_SECTION = (
    r"\section{Publications \& Manuscripts}" "\n"
    r"\begin{itemize}[leftmargin=0.15in, label={}]" "\n"
    r"  \small{\item{" "\n"
    r"    \textbf{C. Y. Li}, et al. ``Learning Humanoid Locomotion on Granular Terrain.'' "
    r"\textit{International Conference on Robotics and Automation (ICRA)}, 2026. "
    r"(Under Review; Contributed parallelized simulation testing layouts) \\ \vspace{3pt}" "\n"
    r"    \textbf{C. Y. Li}, et al. ``Survey Paper on The Energy Efficiency of Large Language "
    r"Models.'' \textit{Nature Reviews Computing}, 2026. (In Progress; Profiled 40+ transformer "
    r"architectures for attention-mechanism bottlenecks)" "\n"
    r"  }}" "\n"
    r"\end{itemize}"
)

_TITLE_VARIANTS = [
    ("Data Engineer Intern", ["data engineer", "data engineering", "analytics engineer",
                               "etl", "data pipeline", "data platform"]),
    ("Cloud Infrastructure Intern", ["infrastructure", "cloud engineer", "cloud infrastructure",
                                      "devops", "site reliability", "sre", "platform engineer"]),
]
_DEFAULT_TITLE = "Software Engineer Intern"

_BOLD_OPEN, _BOLD_CLOSE = "\x01", "\x02"
_TEX_ESCAPE_MAP = [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                    ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                    ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")]


def _gfs_title(job: dict) -> str:
    text = f"{job.get('title', '')} {job.get('description_snippet', '')}".lower()
    for label, keywords in _TITLE_VARIANTS:
        if any(kw in text for kw in keywords):
            return label
    return _DEFAULT_TITLE


def _bullet_to_tex(text: str) -> str:
    """Escape for LaTeX, bolding the same quantified metrics the cover
    letter bolds (found on the RAW text, before escaping breaks the regex)."""
    marked = _METRIC_RE.sub(lambda m: f"{_BOLD_OPEN}{m.group(1)}{_BOLD_CLOSE}", text)
    for a, b in _TEX_ESCAPE_MAP:
        marked = marked.replace(a, b)
    return marked.replace(_BOLD_OPEN, r"\textbf{").replace(_BOLD_CLOSE, "}")


def _order_by_score(ids: list[str], scores: dict[str, float],
                     pinned_first: str | None = None) -> list[str]:
    """Reorder a FIXED set of bullet ids by relevance score (all ids kept —
    this isn't retrieval, it's reordering real work history/project facts).
    `pinned_first`, if given and present, is forced to the front."""
    rest = [i for i in ids if i != pinned_first]
    rest.sort(key=lambda i: scores.get(i, 0.0), reverse=True)
    return ([pinned_first] if pinned_first and pinned_first in ids else []) + rest


def _select_projects(scores: dict[str, float], max_projects: int = 2,
                      max_bullets_per_project: int = 3) -> list[dict]:
    """Pick the top `max_projects` projects by best-bullet relevance score,
    always including SmallDB (priority-2 pinned per user preference)."""
    ranked = sorted(
        PROJECTS.items(),
        key=lambda kv: max((scores.get(i, 0.0) for i in kv[1]["bullet_ids"]), default=0.0),
        reverse=True,
    )
    keys = [k for k, _ in ranked]
    chosen = ["smalldb"] + [k for k in keys if k != "smalldb"][:max_projects - 1]

    out = []
    for key in chosen:
        p = PROJECTS[key]
        ordered_ids = _order_by_score(p["bullet_ids"], scores,
                                       pinned_first="smalldb-lsm-tree-engine" if key == "smalldb" else None)
        out.append({**p, "bullet_ids": ordered_ids[:max_bullets_per_project]})
    return out


def _render_tex(job: dict, include_publications: bool = True, include_research: bool = True,
                 max_bullets_per_project: int = 3) -> str:
    scores = resume_kb.score_all(
        f"{job.get('description_snippet', '')} {job.get('req', '')}".strip(),
        title=job.get("title", ""))
    id_to_text = resume_kb.all_resume_bullets()

    gfs_ids = _order_by_score(GFS_BULLET_IDS, scores, pinned_first="gfs-cost-optimization-engine")
    gfs_bullets = "\n".join(f"      \\resumeItem{{{_bullet_to_tex(id_to_text[i])}}}"
                             for i in gfs_ids)

    projects = _select_projects(scores, max_bullets_per_project=max_bullets_per_project)
    project_blocks = []
    for p in projects:
        bullets = "\n".join(f"    \\resumeItem{{{_bullet_to_tex(id_to_text[i])}}}"
                             for i in p["bullet_ids"])
        project_blocks.append(
            f"  \\resumeProjectHeading\n      {{{p['heading']}}}{{{p['date']}}}\n"
            f"  \\resumeItemListStart\n{bullets}\n  \\resumeItemListEnd\n")
    projects_block = "\n".join(project_blocks)

    tex = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "%%NAME%%": config.YOUR_NAME,
        "%%PHONE%%": config.YOUR_PHONE,
        "%%EMAIL%%": config.YOUR_EMAIL_PRIMARY,
        "%%LINKEDIN_URL%%": config.YOUR_LINKEDIN,
        "%%LINKEDIN_DISPLAY%%": config.YOUR_LINKEDIN.replace("https://", "").replace("http://", ""),
        "%%GITHUB_BLOCK%%": (
            f" $|$\n    \\href{{{config.YOUR_GITHUB}}}"
            f"{{\\underline{{{config.YOUR_GITHUB.replace('https://', '').replace('http://', '')}}}}}"
            if config.YOUR_GITHUB else ""
        ),
        "%%SKILLS_BLOCK%%": SKILLS_BLOCK,
        "%%GFS_TITLE%%": _gfs_title(job),
        "%%GFS_BULLETS%%": gfs_bullets,
        "%%PROJECTS_BLOCK%%": projects_block,
        "%%RESEARCH_SECTION%%": (_research_section(_bullet_to_tex(id_to_text[RESEARCH_BULLET_ID]))
                                  if include_research else ""),
        "%%PUBLICATIONS_SECTION%%": PUBLICATIONS_SECTION if include_publications else "",
    }
    for placeholder, value in replacements.items():
        tex = tex.replace(placeholder, value)
    return tex


def _page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf_path)).pages)


def _compile_to(tex_source: str, dest_path: str) -> bool:
    """Compile LaTeX source to PDF and copy it to dest_path if it's a valid
    single-page PDF. Returns True on success. All temp-file handling stays
    inside this function so nothing references the temp dir after cleanup."""
    if not shutil.which("pdflatex"):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "main.tex").write_text(tex_source, encoding="utf-8")
        try:
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", str(tmp_path), "main.tex"],
                cwd=tmp_path, capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            return False
        pdf_path = tmp_path / "main.pdf"
        if result.returncode != 0 or not pdf_path.exists():
            return False
        if _page_count(pdf_path) > 1:
            return False
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf_path, dest_path)
        return True


def build_resume(job: dict, out_path: str | None = None) -> str | None:
    """Build a job-tailored résumé PDF: same proven one-page LaTeX layout,
    bullets/projects reordered and selected by relevance to THIS job (real
    ATS keyword optimization with zero layout risk).

    Falls back through: fewer project bullets -> drop publications -> the
    static résumé variant (resume_selector) -> None (caller keeps whatever
    config.RESUME_PATH already was), so outreach never breaks.
    """
    if out_path is None:
        raw = f"{job.get('company', 'company')}_{job.get('title', 'role')}"
        slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
        out_path = str(Path(config.AUTOGEN_OUTPUT_DIR) / f"{slug}_resume.pdf")

    attempts = [
        dict(include_publications=True, include_research=True, max_bullets_per_project=3),
        dict(include_publications=False, include_research=True, max_bullets_per_project=3),
        dict(include_publications=False, include_research=True, max_bullets_per_project=2),
        dict(include_publications=False, include_research=False, max_bullets_per_project=2),
    ]
    for opts in attempts:
        try:
            tex = _render_tex(job, **opts)
            if _compile_to(tex, out_path):
                print(f"  📄 Résumé tailored for this job → {out_path}")
                return out_path
        except Exception as e:
            print(f"  ⚠ Résumé build attempt failed: {e}")
            continue

    print("  ⚠ Résumé generation failed — falling back to static variant")
    fallback = select_resume(job)
    return fallback if Path(fallback).exists() else None


# ── CLI ──────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Generate an ATS-optimized résumé (strict Google XYZ bullets) for a "
                     "specific job you're actually applying to.")
    ap.add_argument("--company", default="", help="company name (for context only)")
    ap.add_argument("--title", required=True, help="job title")
    ap.add_argument("--jd", help="path to a text file with the job description")
    ap.add_argument("--out", default=str(Path(config.PROJECT_ROOT) / "assets" / "resume_ats.pdf"),
                     help="output PDF path (default: assets/resume_ats.pdf)")
    args = ap.parse_args()

    jd_text = Path(args.jd).read_text(encoding="utf-8") if args.jd else ""
    job = {"company": args.company, "title": args.title, "description_snippet": jd_text}

    path = build_resume(job, args.out)
    if path:
        print(f"\nDone: {path}")
    else:
        print("\nFailed — no résumé produced (see warnings above).")


if __name__ == "__main__":
    main()
