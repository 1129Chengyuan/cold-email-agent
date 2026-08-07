# ============================================================
#  cover_letter_generator.py
#  Uses Gemini (free tier) to write a cover letter tailored to a
#  specific job, in the candidate's own voice — grounded in
#  assets/experience.json (same RAG source as email_generator.py)
#  and styled after a real example letter the candidate wrote.
#  Renders the result to PDF for attachment.
# ============================================================

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from src.core import config
from src.core import gemini
from src.ranking import resume_kb

STYLE_EXAMPLE_PATH = config.PROJECT_ROOT / "assets" / "cover_letter_style_example.txt"

_SYSTEM_PROMPT = """You write cover letters for a job seeker applying to a specific role. \
You are given one REAL example letter the candidate previously wrote — copy its voice, \
structure, and paragraph rhythm, but write entirely new content for the new company and role.

Structure to follow (mirror the example's shape):
1. Header: candidate name, phone | email | linkedin, date, company name, "Application for <role>".
2. "Dear <Company> Hiring Team," greeting.
3. Opening paragraph: one clear hook connecting a genuine interest to the specific role and team.
4. One or two body paragraphs: concrete past experience/projects, drawn ONLY from the candidate \
   background provided, connected to what this specific role needs.
5. Closing paragraph: brief, forward-looking, ties back to why this company specifically.
6. "Thank you for your time and consideration..." line, then "Sincerely," and the candidate's name.

Hard rules:
- GROUNDING (critical): use ONLY experience, projects, and outcomes that appear verbatim in the \
  candidate background provided. NEVER state or imply the candidate has done something merely \
  because the job posting asks for it. Do NOT copy requirements/phrases from the posting into the \
  candidate's experience. If the background doesn't cover something the role wants, omit it.
- Specific and factual: name real technologies, numbers, and outcomes rather than adjectives.
- Professional, confident tone — never groveling, salesy, or full of buzzwords/clichés.
- 350-450 words total.
- NEVER mention H1B, visa status, work authorization, or sponsorship.
- Output ONLY the letter text (plain text, no markdown). Formatting is STRICT: the header \
  lines (name, phone/email/linkedin, date, company, "Application for <role>") sit on consecutive \
  lines with NO blank line between them, then exactly ONE blank line, then the "Dear ..." \
  greeting on its own line, then exactly ONE blank line, then each subsequent paragraph \
  (opening, each body paragraph, closing, and the "Thank you..."/"Sincerely," block) separated \
  from the one before it by exactly ONE blank line. Never run two paragraphs together without a \
  blank line between them, and never omit the blank line right before the greeting."""


def _style_example() -> str:
    if STYLE_EXAMPLE_PATH.exists():
        return STYLE_EXAMPLE_PATH.read_text().strip()
    return ""


def _relevant_experience(job: dict) -> str | None:
    query = f"{job.get('description_snippet', '')} {job.get('title', '')}".strip()
    try:
        hits = resume_kb.retrieve(query, title=job.get("title", ""), k=6)
    except Exception:
        return None
    if not hits:
        return None
    return "\n".join(f"- {h['text']}" for h in hits)


def _signature_block() -> str:
    lines = [config.YOUR_NAME]
    if config.YOUR_PHONE:
        lines.append(f"{config.YOUR_PHONE} | {config.YOUR_EMAIL_PRIMARY} | {config.YOUR_LINKEDIN}")
    return "\n".join(lines)


def generate_cover_letter_text(job: dict) -> str | None:
    """Returns generated cover letter text, or None if Gemini is unavailable
    (caller should skip attaching a cover letter rather than send a stale one)."""
    example = _style_example()
    evidence = _relevant_experience(job)
    background_block = (
        "Candidate's REAL experience, in priority order — write the body paragraphs "
        "using ONLY these facts, and do NOT invent or embellish. The FIRST bullet is "
        "the candidate's flagship, most-impressive achievement — it MUST appear as one "
        "of the body paragraphs in every letter, regardless of role. The SECOND bullet "
        "(if present) is a strong secondary highlight — include it too unless it's a "
        "poor fit for this specific role. Use the remaining bullets to fill out the "
        "rest of the body with whatever best fits THIS role:\n" + evidence
        if evidence else
        f"Candidate background — use ONLY this to write the body:\n- {config.YOUR_BIO}"
    )

    user_prompt = f"""Write a cover letter for this application.

Company: {job['company']}
Role: {job['title']}
Job posting snippet: {job.get('description_snippet', '')[:800]}

{background_block}

Header contact line (use verbatim): {_signature_block()}
Today's date (use verbatim in MM/DD/YYYY format): {date.today().strftime('%m/%d/%Y')}

EXAMPLE letter (match this voice/structure exactly, write new content):
{example if example else '(no example available — use a clean, professional structure)'}"""

    try:
        text = gemini.generate(user_prompt, system=_SYSTEM_PROMPT,
                               max_output_tokens=1400, temperature=0.4)
        return _normalize_spacing(text.strip())
    except gemini.GeminiUnavailable:
        print("  ⚠ Gemini unavailable — skipping cover letter generation")
        return None


def _normalize_spacing(text: str) -> str:
    """Guarantee the blank-line separation the renderer relies on, even if the
    model's own blank lines slipped: one blank line before the 'Dear ...'
    greeting, and no run of 3+ blank lines elsewhere."""
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("dear ") and out and out[-1].strip():
            out.append("")
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


# Quantitative achievement metrics worth visually emphasizing: $ amounts, percentages,
# multipliers ("33x"), and data-volume figures ("7 TB", "150 GB").
_METRIC_RE = re.compile(
    r"(\$[\d,]+(?:\.\d+)?\+?"
    r"|\d+(?:\.\d+)?%"
    r"|\d+(?:\.\d+)?[xX]\b"
    r"|\d+(?:,\d{3})*(?:\.\d+)?[KMB]?\+?\s?(?:TB|GB|MB)\b"
    r"|\d+(?:,\d{3})*(?:\.\d+)?[KMB]?\+?\s?ops/sec)"
)


def _bold_metrics(text: str) -> str:
    return _METRIC_RE.sub(r"<b>\1</b>", text)


def render_pdf(text: str, out_path: str) -> None:
    """Render plain cover-letter text (blank-line-separated paragraphs) to a PDF."""
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=11, leading=15,
                                 spaceAfter=10)
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                             topMargin=1 * inch, bottomMargin=1 * inch,
                             leftMargin=1 * inch, rightMargin=1 * inch)
    story = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # Preserve single line breaks within a paragraph (e.g. header block).
        html_para = _bold_metrics(para.replace("\n", "<br/>"))
        story.append(Paragraph(html_para, body_style))
        story.append(Spacer(1, 4))
    doc.build(story)


def _autogen_filename(job: dict, suffix: str) -> str:
    """Slugified '<Company>_<Title>_<suffix>.pdf' filename, safe for any
    company/title text."""
    raw = f"{job.get('company', 'company')}_{job.get('title', 'role')}"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
    return f"{slug}_{suffix}.pdf"


def generate_cover_letter(job: dict, out_path: str | None = None) -> str | None:
    """Generate and write a tailored cover letter PDF for this job into
    config.AUTOGEN_OUTPUT_DIR (or out_path if given) — the user reviews it
    there before it's attached to any outreach email.

    Returns the path written, or None if generation failed (Gemini unavailable) —
    caller should proceed without a cover letter attachment in that case.
    """
    out_path = out_path or str(Path(config.AUTOGEN_OUTPUT_DIR) / _autogen_filename(job, "cover_letter"))
    text = generate_cover_letter_text(job)
    if not text:
        return None
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    render_pdf(text, out_path)
    print(f"  📝 Cover letter generated → {out_path}")
    return out_path


# ── Quick test ───────────────────────────────────────────────
if __name__ == "__main__":
    test_job = {
        "company": "Stripe",
        "title": "Software Engineer I",
        "description_snippet": "We are looking for a software engineer to join our payments team.",
    }
    path = generate_cover_letter(test_job, "/tmp/test_cover_letter.pdf")
    print("Wrote:", path)
