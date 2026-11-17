"""Which feed and job-board listings reach a user (decision 3 in docs/plan-m9.md). No database.

Reading the boards and Adzuna moved to the Job Search Service (services/jobsearch/tests/test_connectors.py);
the relevance check stays in the app.
"""

import pytest

from app.modules.catalog.parsers import JobCard
from app.modules.matching.scoring import DEFAULT_WEIGHTS, ProfileInput
from app.modules.sources.relevance import Audience, floor_from_years, relevant

pytestmark = pytest.mark.nodb


# --- Relevance (decision 3) -----------------------------------------------------------------------------


def card(title: str, location: str = "Bengaluru, India", company: str = "Acme") -> JobCard:
    return JobCard(
        source="greenhouse",
        source_job_id="1",
        title=title,
        company=company,
        location=location,
        lead="company_feed",
    )


PROFILE = ProfileInput(
    id="p",
    name="VP Eng",
    target_roles=["VP Engineering"],
    locations=["Bengaluru", "Remote"],
    work_models=["Hybrid", "Remote"],
    min_seniority=5,
    excluded_companies=["Badco"],
    weights=dict(DEFAULT_WEIGHTS),
    threshold=85,
)
SENIOR_TECH = Audience(floor=5, families=frozenset({"technology"}), profiles=(PROFILE,), queries=())


@pytest.mark.parametrize(
    "job,expected",
    [
        (card("Director of Engineering"), True),
        (card("Principal Engineer", "Remote - India"), True),  # one level below the floor is allowed
        (card("Software Engineer II"), False),  # below the user's level
        (card("Product Designer"), False),  # no seniority word, senior user
        (card("Director, Finance"), False),  # another field
        (card("Director of Engineering", "Pune"), False),  # not one of the profile's cities
        (card("Director of Engineering", company="Badco India"), False),  # excluded company
    ],
)
def test_relevance(job, expected):
    assert relevant(job, SENIOR_TECH) is expected


def test_without_profiles_or_facts_everything_passes():
    assert relevant(
        card("Product Designer"), Audience(floor=1, families=frozenset(), profiles=(), queries=())
    )


@pytest.mark.parametrize("years,floor", [(None, 1), (3, 1), (6, 2), (12, 3), (24, 4)])
def test_floor_from_years(years, floor):
    assert floor_from_years(years) == floor
