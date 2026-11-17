from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# Scoring factors (same keys as the POC and the LLD). Weights per search profile must sum to 100.
FACTORS: dict[str, str] = {
    "role": "Role and seniority",
    "exp": "Experience and leadership",
    "core": "Core product/engineering",
    "cloud": "Cloud and architecture",
    "ai": "AI/GenAI",
    "domain": "Industry/domain",
    "loc": "Location/work model",
    "skills": "Skills",
    "comp": "Compensation",
}
DEFAULT_WEIGHTS = {
    "role": 20,
    "exp": 15,
    "core": 15,
    "cloud": 10,
    "ai": 10,
    "domain": 10,
    "loc": 10,
    "skills": 5,
    "comp": 5,
}
# Suggested Skills weight once a profile has key skills (the editor offers it; defaults stay as they were).
SKILLS_WEIGHT_WITH_KEY_SKILLS = 15
SENIORITY = {
    1: "Engineer",
    2: "Lead",
    3: "Manager",
    4: "Senior manager",
    5: "Director",
    6: "Head / Sr director",
    7: "VP",
    8: "SVP",
    9: "CXO",
}
WorkModel = Literal["Remote", "Hybrid", "On-site"]
MAX_PROFILES = 5  # one per resume (four at most) and one more made through the API
MAX_SKILLS = 40  # skills the user adds by hand; the resume's own are on top
SKILL_MAX_CHARS = 40


def _clean(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = " ".join(v.split())
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _check_weights(w: dict[str, int]) -> dict[str, int]:
    if set(w) != set(FACTORS):
        missing, extra = set(FACTORS) - set(w), set(w) - set(FACTORS)
        raise ValueError(
            f"weights must have exactly these keys: {', '.join(FACTORS)}"
            + (f" (missing {sorted(missing)})" if missing else "")
            + (f" (unknown {sorted(extra)})" if extra else "")
        )
    if any(v < 0 or v > 60 for v in w.values()):
        raise ValueError("each weight must be between 0 and 60")
    if sum(w.values()) != 100:
        raise ValueError(f"weights must add up to 100 (they add up to {sum(w.values())})")
    return w


def _check_skills(v: list[str]) -> list[str]:
    v = _clean(v)
    if len(v) > MAX_SKILLS:
        raise ValueError(f"up to {MAX_SKILLS} skills")
    if any(len(s) > SKILL_MAX_CHARS for s in v):
        raise ValueError(f"each skill must be at most {SKILL_MAX_CHARS} characters")
    return v


class SearchProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_roles: list[str] = Field(min_length=1, max_length=20)
    locations: list[str] = Field(min_length=1, max_length=20)
    work_models: list[WorkModel] = Field(min_length=1)
    min_seniority: int = Field(ge=1, le=9)
    excluded_companies: list[str] = Field(default_factory=list, max_length=100)
    skills: list[str] = Field(
        default_factory=list,
        description="Skills you added by hand (the resume's own are in resume_skills); jobs asking for them score "
        "higher",
    )
    weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    threshold: int = Field(85, ge=50, le=100, description="Minimum overall score for a 'strong' match")
    active: bool = True

    _lists = field_validator("target_roles", "locations", "excluded_companies")(lambda cls, v: _clean(v))
    _skills = field_validator("skills")(lambda cls, v: _check_skills(v))
    _w = field_validator("weights")(lambda cls, v: _check_weights(v))

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("work_models")
    @classmethod
    def _wm(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class SearchProfileIn(SearchProfileBase):
    pass


class SearchProfilePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    target_roles: list[str] | None = Field(None, max_length=20)  # empty: from the title family only
    locations: list[str] | None = Field(None, max_length=20)  # empty: anywhere
    work_models: list[WorkModel] | None = Field(None, min_length=1)
    min_seniority: int | None = Field(None, ge=1, le=9)
    excluded_companies: list[str] | None = Field(None, max_length=100)
    skills: list[str] | None = None
    weights: dict[str, int] | None = None
    threshold: int | None = Field(None, ge=50, le=100)
    active: bool | None = None
    version: int = Field(description="The version you last read; a stale version returns 409")

    _skills = field_validator("skills")(lambda cls, v: _check_skills(v or []))  # null clears the list

    @model_validator(mode="after")
    def _validate(self):
        for f in ("target_roles", "locations", "excluded_companies"):
            if getattr(self, f) is not None:
                setattr(self, f, _clean(getattr(self, f)))
        if self.weights is not None:
            _check_weights(self.weights)
        if self.name is not None:
            self.name = " ".join(self.name.split())
        return self


class SearchProfileOut(BaseModel):
    """A match profile as stored: a resume's profile may start with no target roles or locations (read from the
    resume; the user fills them in)."""

    model_config = {"from_attributes": True}
    id: UUID
    name: str
    target_roles: list[str]
    locations: list[str]
    work_models: list[str]
    min_seniority: int
    excluded_companies: list[str]
    skills: list[str] = Field(description="Skills you added by hand")
    weights: dict[str, int]
    threshold: int
    active: bool
    resume_id: UUID | None = Field(
        None, description="The resume this profile is made from; None: every resume"
    )
    resume_label: str | None = None
    resume_skills: list[str] = Field(
        default_factory=list, description="Read from the resume, refreshed with it"
    )
    resume_read_at: datetime | None = None
    not_in_resume: list[str] = Field(
        default_factory=list, description="Skills you added that the resume doesn't show yet"
    )
    version: int
    created_at: datetime
    updated_at: datetime


class SkillIn(BaseModel):
    skill: str = Field(min_length=1, max_length=SKILL_MAX_CHARS)


class ProfilesMeta(BaseModel):
    factors: dict[str, str]
    default_weights: dict[str, int]
    seniority: dict[int, str]
    work_models: list[str]
    max_profiles: int
    max_skills: int = MAX_SKILLS
    suggested_skills_weight: int = SKILLS_WEIGHT_WITH_KEY_SKILLS
