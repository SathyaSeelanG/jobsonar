"""Generate tailored resume bullets + cover letter per job.

Uses the local OmniRoute gateway (see llm.py) via the shared chat() helper.
"""
from pathlib import Path

from .llm import available, chat


def tailor(job, profile: dict, llm_cfg: dict, out_dir: Path) -> Path | None:
    if not available(llm_cfg):
        return None
    prompt = f"""You are helping a candidate apply for a job. Produce two sections in markdown:

## Tailored Resume Bullets
5-6 resume bullet points rewritten to emphasize what THIS job asks for. Use the candidate's real skills only — never invent experience.

## Cover Letter
A concise (~180 words), specific, non-generic cover letter. No placeholder brackets.

CANDIDATE:
Name: {profile.get('name')}
Summary: {profile.get('summary')}
Core skills: {', '.join(profile.get('skills', {}).get('core', []))}
Other skills: {', '.join(profile.get('skills', {}).get('secondary', []))}
Experience: {profile.get('years_experience')} years

JOB: {job.title} at {job.company} ({job.location})
{job.description[:4000]}"""

    text = chat(prompt, 1200, llm_cfg)
    if not text:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in f"{job.company} {job.title}")[:80]
    path = out_dir / f"{safe}.md"
    header = f"# {job.title} — {job.company}\n\nScore: {job.score} | [Job posting]({job.url})\n\n"
    path.write_text(header + text, encoding="utf-8")
    return path
