# ============================================================
#  email_generator.py
#  Uses Gemini (free tier) to write a short, specific cold email
#  per job. Target: under 90 words. Personalized to company + role.
#  If Gemini is unavailable (no key / daily quota spent), falls back
#  to a plain template so outreach never hard-fails.
# ============================================================

from __future__ import annotations

from src.core import config
from src.core import gemini
from src.ranking import resume_kb

_SYSTEM_PROMPT = """You write short, natural, human cold emails from a Georgia Tech CS sophomore to engineering leaders, recruiters, or technical founders. The tone must sound like a real person writing a thoughtful note in Gmail—not an automated marketing script.

---

### STRUCTURAL FLOW

1. **Greeting & Hook:**
   - Always start with "Hi {Name}," on its own line.
   - Line 1 of the body: Open naturally with a specific company news item, engineering milestone, or technical focus area. Connect it briefly to platform or infrastructure engineering.

2. **Background & Technical Proof (1 short paragraph, 3-4 sentences max):**
   - **Identity:** State who you are succinctly (e.g., "I'm a CS sophomore at Georgia Tech focused on backend and systems engineering.").
   - **Gordon Food Service:** State what you engineered and its impact ($50,000+ saved annually via dynamic slot allocation) in a natural, flowing sentence. Name AT MOST 2 specific tools/technologies (e.g., "Python and BigQuery," or "Terraform and Cloud Scheduler") — never stack 3+ tools into one sentence.
   - **SmallDB:** Highlight building SmallDB—a crash-consistent C++20 storage engine using an LSM-tree architecture. Append the bare URL in parentheses directly after the project name: (https://github.com/1129Chengyuan/smalldb).

3. **Call to Action & Sign-off:**
   - Mention "Resume attached for context." followed by exactly ONE question, chosen by the Recipient's title:
     - **Recruiting/HR title** (contains "Recruiter", "Talent", "Sourcer", "HR", "People"): ask a referral-style question about who owns the hiring for this specific internship track — e.g. "Are you managing the search for this internship, or is another recruiter leading it?"
     - **Engineering/technical title** (Engineering Manager, Director of Engineering, Lead, Principal, Staff, etc.): ask ONE technical question about their team's compute scaling, resource scheduling, or cost efficiency.
   - Sign off with "Best," followed by the provided signature block.

---

### STRICT RULES

- **Greeting:** ALWAYS include "Hi {Name}," at the top.
- **Tone & Flow:** Write in smooth, natural sentences. Avoid choppy one-liners or fragmented phrasing (e.g., never write "This dynamic slot allocation reduced...").
- **Length:** Under 120 words total (excluding signature).
- **Questions:** Exactly ONE question mark in the entire email (in the CTA).
- **Grounding:** ONLY use facts and metrics from the candidate background.
- **Forbidden Phrases:** Never use clichés like "I hope this email finds you well", "I wanted to reach out", "directly", "passionate", "leverage", or "touch base".
- **Links:** Output plain-text bare URLs (no Markdown brackets like `[Text](url)`). Max 1 link in the email body.
- **Output:** Output ONLY the email body (starting with "Hi {Name},") — no preamble, no Markdown code blocks, no notes."""


_SUBJECT_SYSTEM_PROMPT = """You write subject lines for cold outreach emails to corporate \
recruiters. The subject is the ONLY thing that decides whether the email gets opened — it needs \
a real reason to click, not a label.

Hard rules:
- 3-7 words. No em dashes, no colons-as-separator ("Role — Name" style), no "Application for...".
- If a PERSONALIZATION_HOOK is given, reference the SPECIFIC thing from it (a technology, a \
  number, a project name) — that specificity is what earns the open. Do not generalize it away.
- If no hook, reference the specific team/problem area from the job title/JD instead of just \
  restating the job title verbatim.
- No clickbait, no emoji, no exclamation points, no "Quick question" / "Following up" / spammy \
  filler. It should read like a real person's subject line, specific enough that a generic mass \
  email couldn't have used it.
- Output ONLY the subject line text — nothing else."""


def generate_subject(job: dict, hook: str | None = None) -> str:
    """A specific, hook-aware subject line — falls back to a plain template
    (role + name) if Gemini is unavailable."""
    hook_line = f"PERSONALIZATION_HOOK: {hook}" if hook else "PERSONALIZATION_HOOK: (none)"
    user_prompt = (f"Company: {job['company']}\nJob title: {job['title']}\n"
                   f"Job posting snippet: {job.get('description_snippet', '')[:200]}\n{hook_line}")
    try:
        subject = gemini.generate(user_prompt, system=_SUBJECT_SYSTEM_PROMPT,
                                  max_output_tokens=30, temperature=0.5)
        return subject.strip().strip('"')
    except gemini.GeminiUnavailable:
        return f"{job['title']} — {config.YOUR_NAME}"


def _signature() -> str:
    """The exact contact lines to close every email with, one per line."""
    lines = [config.YOUR_NAME]
    if config.YOUR_PHONE:
        lines.append(config.YOUR_PHONE)
    emails = config.YOUR_EMAIL_PRIMARY
    if config.YOUR_EMAIL_ALT:
        emails += f" | {config.YOUR_EMAIL_ALT}"
    lines.append(emails)
    if config.YOUR_LINKEDIN:
        lines.append(config.YOUR_LINKEDIN)
    return "\n".join(lines)


def _template_body(job: dict, recruiter: dict) -> str:
    """Deterministic fallback email when Gemini is unavailable. Lower-touch
    than the generated version but still specific and sendable. Never
    mentions H1B / visa / sponsorship."""
    greeting = recruiter.get("first_name") or recruiter.get("name") or "there"
    return (
        f"Hi {greeting},\n\n"
        f"I'm writing about the {job['title']} role at {job['company']}. "
        f"I'm {config.YOUR_BIO}, and I believe my background is a close match for what "
        f"the role calls for.\n\n"
        f"My résumé is attached. Would you be the right person to speak with about this "
        f"role, or could you point me to whoever is?\n\n"
        f"Thanks for your time,\n{_signature()}"
    )


def _relevant_experience(job: dict) -> str | None:
    """Retrieve the candidate's most relevant real experience for THIS job
    (semantic + keyword search over assets/experience.json). Returns a bullet
    list the model must ground the email in, or None when retrieval yields
    nothing / is unavailable so the caller falls back to the plain bio."""
    query = f"{job.get('description_snippet', '')} {job.get('req', '')}".strip()
    try:
        hits = resume_kb.retrieve(query, title=job.get("title", ""), k=4)
    except Exception:
        return None
    if not hits:
        return None
    lines = []
    for h in hits:
        line = f"- {h['text']}"
        if h.get("link"):
            line += f" [LINK: {h['link']}]"
        lines.append(line)
    return "\n".join(lines)


def generate_email_body(job: dict, recruiter: dict, hook: str | None = None) -> str:
    """
    Call Gemini to write a personalized cold email body. Falls back to a
    plain template if Gemini is unavailable.

    job keys: title, company, description_snippet
    recruiter keys: first_name, name, title, email
    hook: a real, specific, current fact about the company/team (a launch, a
    blog post, news) to open the email with — found via web research, NOT
    inferred from the JD. Without one, the opener falls back to naming the
    specific team/problem the role exists to solve.
    """
    req = job.get("req") or job.get("job_id") or ""
    # Ground the value sentence(s) in the résumé bullets most relevant to THIS
    # role (RAG). Falls back to the one-line bio when nothing is retrieved.
    evidence = _relevant_experience(job)
    if evidence:
        background_block = (
            f"Candidate identity — use this verbatim (or a natural short paraphrase of it) as "
            f"the identity/context sentence (Sentence A) in the bridge paragraph:\n"
            f"- {config.YOUR_BIO}\n\n"
            "Candidate's REAL experience, in priority order — write the rest of the value "
            "sentence(s) using ONLY these facts, and do NOT invent, embellish, or "
            "add anything not stated here. The FIRST bullet is the candidate's "
            "flagship, most-impressive achievement — it MUST be included and led "
            "with as the primary evidence in every email, regardless of "
            "role. You may add ONE more bullet from below it as secondary support "
            "if it specifically strengthens the pitch for THIS role. "
            "Do NOT put these in the signature:\n"
            f"{evidence}")
    else:
        background_block = (
            "Candidate background — use this ONLY to write the value sentence(s); "
            "do NOT put it in the signature:\n"
            f"- {config.YOUR_BIO}")

    hook_block = f"PERSONALIZATION_HOOK: {hook}" if hook else "PERSONALIZATION_HOOK: (none provided — use the team/problem fallback)"

    user_prompt = f"""Write a cold outreach email for this situation.

Recipient: {recruiter.get('first_name') or recruiter.get('name', 'Recruiter')} ({recruiter['title']} at {job['company']})
Job title: {job['title']}
Company: {job['company']}
Requisition/ID (mention only if non-empty): {req}
Job posting snippet: {job.get('description_snippet', '')[:300]}
{hook_block}

{background_block}

Signature — end with a short sign-off ("Best," or "Thanks for your time,") then EXACTLY these lines, one per line, verbatim, with nothing after them:
{_signature()}"""

    try:
        body = gemini.generate(user_prompt, system=_SYSTEM_PROMPT,
                               max_output_tokens=800, temperature=0.4)
        return body.strip()
    except gemini.GeminiUnavailable:
        print("  ⚠ Gemini unavailable — using template email")
        return _template_body(job, recruiter)


def generate_outreach(job: dict, recruiter: dict, hook: str | None = None) -> dict:
    """
    Returns dict with keys: subject, body, to_email, to_name
    """
    print(f"  ✍️  Generating email for {job['title']} @ {job['company']} ...")
    subject = generate_subject(job, hook=hook)
    body = generate_email_body(job, recruiter, hook=hook)

    return {
        "subject": subject,
        "body": body,
        "to_email": recruiter["email"],
        "to_name": recruiter["name"],
    }


# ── Quick test ───────────────────────────────────────────────
if __name__ == "__main__":
    test_job = {
        "title": "Software Engineer I",
        "company": "Stripe",
        "description_snippet": (
            "We are looking for a software engineer to join our payments team. "
            "We sponsor H1B visas for qualified candidates."
        ),
        "h1b_signal": 2,
    }
    test_recruiter = {
        "first_name": "Sarah",
        "name": "Sarah Johnson",
        "title": "Technical Recruiter",
        "email": "sarah.johnson@stripe.com",
    }

    result = generate_outreach(test_job, test_recruiter)
    print("\n── SUBJECT ────────────────────────────────")
    print(result["subject"])
    print("\n── BODY ───────────────────────────────────")
    print(result["body"])
