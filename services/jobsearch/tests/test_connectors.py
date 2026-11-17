"""Reading company boards, Workday and Adzuna, and finding boards from links. No database, no network."""

from datetime import UTC, datetime

import pytest

from jobsearch import resolver
from jobsearch.connectors import adzuna, feeds, workday
from jobsearch.connectors.base import text_of
from jobsearch.locations import in_scope
from tests.conftest import sample

pytestmark = pytest.mark.nodb


def test_greenhouse_keeps_india_jobs_with_their_descriptions():
    result = feeds.postings_from_greenhouse(sample("greenhouse.json"), "Acme Cloud")
    assert result.total == 5
    assert [p.source_job_id for p in result.postings] == ["7001", "7002", "7004", "7005"]  # not Dublin
    first = result.postings[0]
    assert (first.source, first.company) == ("greenhouse", "Acme Cloud")
    assert first.description == "Lead the platform teams.\n- Kubernetes\n- Go"
    assert first.details == {"department": "Engineering"}
    assert first.posted_at == datetime(2026, 10, 28, 13, 0, tzinfo=UTC)
    assert result.postings[1].work_model == "Remote"


def test_lever_reads_all_locations_lists_and_salary():
    result = feeds.postings_from_lever(sample("lever.json"), "BrightPay")
    assert [p.source_job_id for p in result.postings] == [
        "a1b2c3d4-0001",
        "a1b2c3d4-0002",
    ]  # Pune via allLocations
    vp = result.postings[0]
    assert vp.work_model == "Hybrid" and vp.salary == "INR 9,000,000–12,000,000 per year salary"
    assert "What you'll do\n- Hire leaders\n- Ship" in vp.description
    assert vp.url == "https://jobs.lever.co/brightpay/a1b2c3d4-0001"
    assert result.postings[1].work_model == "On-site"


def test_ashby_skips_unlisted_jobs_and_reads_the_country():
    result = feeds.postings_from_ashby(sample("ashby.json"), "Quanta")
    assert [p.source_job_id for p in result.postings] == ["ash-1", "ash-2"]
    assert result.postings[0].salary == "₹80L – ₹1.1Cr" and result.postings[0].work_model == "Hybrid"
    assert result.postings[1].work_model == "Remote"


def test_smartrecruiters_tidies_locations_and_joins_sections():
    data = sample("smartrecruiters.json")
    result = feeds.postings_from_smartrecruiters(data["postings"], data["details"], "Freshdesk", "freshdesk")
    first, second = result.postings
    assert first.location == "Chennai, India"
    assert first.description == "Job Description\nLead billing engineering.\n\nQualifications\n- 12+ years"
    assert first.url == "https://jobs.smartrecruiters.com/freshdesk/744000000000001"
    assert first.details == {"department": "Engineering", "level": "Director"}
    assert second.description is None and second.work_model == "Remote"


def test_adzuna_cleans_titles_and_marks_estimated_salaries():
    nimbus, typing = adzuna.postings_from_adzuna(sample("adzuna.json"))
    assert (nimbus.source, nimbus.title, nimbus.company) == ("adzuna", "VP Engineering", "Nimbus Tech")
    assert nimbus.salary == "₹9,000,000 / year (Adzuna estimate)"
    assert nimbus.description == "Lead a 200-person engineering org…"
    assert typing.salary is None


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Bengaluru, India", True),
        ("Remote - India", True),
        ("Bangalore, IND", True),
        ("Gurugram", True),
        ("Dublin, Ireland", False),
        ("Indiana, USA", False),
        (None, False),
    ],
)
def test_in_scope(location, expected):
    assert bool(in_scope(location)) is expected


def test_text_of_handles_escaped_html():
    assert text_of("&lt;p&gt;One&lt;br&gt;Two&lt;/p&gt;") == "One\nTwo"
    assert text_of("") is None


# --- Workday ----------------------------------------------------------------------------------------------

NVIDIA = workday.Board("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", NVIDIA),
        ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/India-Pune/X_JR1", NVIDIA),
        ("nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs", NVIDIA),
        (
            "https://wd3.myworkdaysite.com/en-US/recruiting/acme/Careers",
            workday.Board("wd3.myworkdaysite.com", "acme", "Careers"),
        ),
        ("https://nvidia.wd5.myworkdayjobs.com/", None),
        ("https://www.nvidia.com/careers", None),
        ("https://evil.example.com/nvidia.wd5.myworkdayjobs.com/x", None),
    ],
)
def test_workday_links(link, expected):
    assert workday.Board.from_url(link) == expected


def test_a_workday_board_key_round_trips():
    assert workday.Board.parse(NVIDIA.key) == NVIDIA
    assert NVIDIA.api == "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"
    assert NVIDIA.careers_url == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"


def test_workday_uses_the_boards_country_filter():
    facets = sample("workday_search_all.json")["facets"]
    assert workday.country_facet(facets) == {"locationHierarchy1": ["2fcb99c455831013ea52b82135ba3266"]}
    assert workday.country_facet([]) is None


def test_workday_lists_postings_without_details():
    now = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    stubs = workday.listed(sample("workday_search_india.json"), NVIDIA, "NVIDIA", now)
    assert [s.source_job_id for s in stubs] == [
        "/job/India-Remote/Senior-Network-Infrastructure-Engineer_JR2015526",
        "/job/India-Pune/Senior-System-Software-Engineer_JR2029360",
        "/job/India-Pune/Senior-Software-Engineer---Infrastructure_JR2029287-1",
    ]
    first = stubs[0]
    assert first.needs_details and first.requisition_id == "JR2015526"
    assert first.location == "India, Remote"  # "5 Locations": the first one, from the job's path
    assert first.work_model == "Remote"
    assert first.url == NVIDIA.careers_url + first.source_job_id
    assert first.posted_at == datetime(2026, 11, 14, tzinfo=UTC)  # "Posted Today"
    assert stubs[1].location == "India, Pune"


def test_workday_details_fill_the_posting():
    stub = workday.listed(sample("workday_search_india.json"), NVIDIA, "NVIDIA", datetime.now(UTC))[0]
    full = workday.detailed(stub, sample("workday_detail.json"))
    assert not full.needs_details
    assert full.description.startswith("NVIDIA is looking for a Network Operations Engineer")
    assert full.location == "India, Remote; India, Mumbai; India, Gurugram; India, Hyderabad; India, Pune"
    assert full.requisition_id == "JR2015526"
    assert full.posted_at == datetime(2026, 11, 13, tzinfo=UTC)
    assert full.url.startswith("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/")
    assert full.details == {"time_type": "Full time"}


@pytest.mark.parametrize(
    "text,days",
    [("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 3 Days Ago", 3), ("Posted 30+ Days Ago", None)],
)
def test_workday_posting_dates(text, days):
    now = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
    got = workday.posted(text, now)
    assert (got is None) if days is None else got == datetime(2026, 11, 14 - days, tzinfo=UTC)


# --- Finding boards -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://boards.greenhouse.io/okta", ("greenhouse", "okta")),
        ("job-boards.greenhouse.io/databricks/jobs/123", ("greenhouse", "databricks")),
        ("https://boards.greenhouse.io/embed/job_board?for=stripe&b=x", ("greenhouse", "stripe")),
        ("https://jobs.lever.co/meesho/7d9a", ("lever", "meesho")),
        ("https://jobs.ashbyhq.com/notion", ("ashby", "notion")),
        ("https://careers.smartrecruiters.com/Freshworks", ("smartrecruiters", "Freshworks")),
        ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", ("workday", NVIDIA.key)),
        ("https://www.okta.com/careers", ("careers_page", "www.okta.com/careers")),  # step 2
        ("https://jobs.lever.co/", None),
    ],
)
def test_board_links(link, expected):
    assert resolver.from_link(link) == expected


def test_board_guesses_drop_company_suffixes():
    assert resolver.board_guesses("Zeta Suite Pvt Ltd") == ["zetasuite", "zeta-suite", "zeta"]
    assert resolver.board_guesses("Okta, Inc.") == ["okta"]
    assert resolver.board_guesses("Ltd") == []


def test_valid_boards():
    assert resolver.valid_board("greenhouse", "okta")
    assert resolver.valid_board("workday", NVIDIA.key)
    assert not resolver.valid_board("workday", "nvidia")
    assert not resolver.valid_board("workday", "evil.example.com/a/b")
    assert not resolver.valid_board("greenhouse", "../etc")
