from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import re


@dataclass
class Job:
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    source: str = ""
    posted_at: str = ""
    salary: str = ""
    score: int = 0
    score_reason: str = ""
    status: str = "new"  # new -> shortlisted -> tailored -> applied / skipped
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    experience_level: str = ""   # fresher, junior, mid, senior, lead
    company_careers_url: str = ""
    apply_type: str = ""   # quick_apply, apply_now

    @property
    def id(self) -> str:
        key = f"{self.title}|{self.company}|{self.url}".lower()
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    @property
    def fuzzy_key(self) -> str:
        """Normalized title+company key so the same posting from two different
        sources (e.g. SimplyHired + LinkedIn) collapses to one entry even
        though their URLs differ."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
        return hashlib.sha1(f"{norm(self.title)}|{norm(self.company)}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["fuzzy_key"] = self.fuzzy_key
        low_desc = (self.description or "").lower() + " " + (self.title or "").lower()
        if "quick apply" in low_desc or "quickapply" in low_desc or self.apply_type == "quick_apply":
            d["apply_type"] = "quick_apply"
        elif not d.get("apply_type"):
            d["apply_type"] = "apply_now"
        return d
