"""The screening questions LinkedIn and Naukri forms ask most often, and how the profile answers them.

`required` questions block readiness until the answer bank or the candidate profile answers them.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.modules.candidate.models import CandidateProfile


@dataclass(frozen=True)
class Standard:
    key: str
    question: str
    required: bool
    from_profile: Callable[[CandidateProfile], str | None] = lambda c: None
    choices: tuple[str, ...] = ()  # the usual answers, offered as quick picks (a dropdown on the form)


def _notice(c: CandidateProfile) -> str | None:
    if c.notice_days is None:
        return None
    return "Immediate" if c.notice_days == 0 else f"{c.notice_days} days"


YES_NO = ("Yes", "No")

STANDARD: list[Standard] = [
    Standard("notice_period", "What is your notice period?", True, _notice),
    Standard("current_ctc", "What is your current CTC?", True, lambda c: c.current_ctc),
    Standard("expected_ctc", "What is your expected CTC?", True, lambda c: c.expected_ctc),
    Standard(
        "total_experience",
        "How many years of total experience do you have?",
        True,
        lambda c: None if c.years_experience is None else f"{c.years_experience} years",
    ),
    Standard("relocation", "Are you willing to relocate?", False),
    Standard("work_authorization", "What is your work authorisation?", False, lambda c: c.work_authorization),
    Standard("reason_for_change", "Why are you looking for a change?", False),
    # Asked on most company application forms (user, 2026-11-15, from a GE HealthCare Workday form). Yes/No
    # dropdowns there; the extension picks the option that means the saved answer.
    Standard(
        "legally_authorized",
        "Are you legally authorised to work in the country where the job is located?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "sponsorship",
        "Will you now or in the future require sponsorship for an employment visa?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "work_location",
        "Are you willing to work in the job's location (not fully remote roles)?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "non_compete",
        "Are you subject to a non-compete or non-solicitation agreement with another employer that may restrict "
        "you in this job?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "confidentiality",
        "Do you agree not to disclose or use confidential or proprietary information of others, including any "
        "former employer?",
        False,
        choices=("Yes, I agree", "No"),
    ),
    Standard("under_18", "Are you younger than 18 years old?", False, choices=YES_NO),
    Standard(
        "former_government",
        "Were you ever a government employee (civil service or military)?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "family_government",
        "Have your immediate family members (spouse, parent, sibling or child) or business partners ever been "
        "employed by any government?",
        False,
        choices=YES_NO,
    ),
    # From an Oracle form (user, 2026-11-16). Voluntary: the extension fills gender and ethnicity only from the
    # answer saved here, never by a loose match; leave them blank to answer on each form.
    Standard(
        "uniformed_forces",
        "Have you served in any of the India Uniformed forces (Army, Navy, Air Force, paramilitary or police)?",
        False,
        choices=YES_NO,
    ),
    Standard(
        "gender",
        "Gender (voluntary)",
        False,
        choices=("Male", "Female", "Non-binary", "Prefer not to say"),
    ),
    Standard(
        "ethnicity",
        "Ethnicity (voluntary)",
        False,
        choices=("Asian", "Indian", "Prefer not to say"),
    ),
]
BY_KEY = {s.key: s for s in STANDARD}
MAX_CUSTOM = 50


def slug(question: str) -> str:
    """'Do you have a valid passport?' → 'do_you_have_a_valid_passport'."""
    s = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")
    return s[:60].rstrip("_") or "question"
