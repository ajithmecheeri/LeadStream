"""Step 2: Oracle Recruiting Cloud, Eightfold and companies' own careers sites. No database; HTTP goes through
httpx.MockTransport (the Oracle, Eightfold and careers-page samples are trimmed real responses of 2026-11-14)."""

from datetime import UTC, datetime

import httpx
import pytest

from jobsearch import resolver
from jobsearch.connectors import careers, eightfold, oracle
from tests.conftest import FIXTURES, sample

pytestmark = pytest.mark.nodb

JPMC = oracle.Board("jpmc.fa.oraclecloud.com", "CX_1001")


# --- Oracle Recruiting Cloud ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs", JPMC),
        ("jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210776755", JPMC),
        ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/sites/CX_1001", JPMC),
        ("https://jpmc.fa.oraclecloud.com/", None),
        ("https://evil.example.com/hcmUI/CandidateExperience/en/sites/CX_1001", None),
    ],
)
def test_oracle_links(link, expected):
    assert oracle.Board.from_url(link) == expected


def test_oracle_uses_the_sites_country_filter():
    assert oracle.country_facet(sample("oracle_search_all.json")["items"][0]) == "300000000289360"
    assert oracle.country_facet({"locationsFacet": []}) is None


def test_oracle_lists_india_jobs_without_details():
    stubs = oracle.listed(sample("oracle_search_india.json")["items"][0], JPMC, "JPMorgan Chase")
    assert [s.source_job_id for s in stubs] == ["210776755", "210782810", "210793423"]
    first, _, third = stubs
    assert first.needs_details and first.title == "Product Director - Debit Product"
    assert first.location == "Hyderabad, Telangana, India"
    assert (
        first.url
        == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210776755"
    )
    assert first.posted_at == datetime(2026, 11, 13, tzinfo=UTC)
    assert third.location == "Bengaluru, Karnataka, India; Mumbai, Maharashtra, India"


def test_oracle_details_keep_the_jobs_own_text_only():
    stub = oracle.listed(sample("oracle_search_india.json")["items"][0], JPMC, "JPMorgan Chase")[0]
    full = oracle.detailed(stub, sample("oracle_detail.json"))
    assert not full.needs_details and full.description.startswith(
        "Ignite your passion for product innovation"
    )
    assert "Company boilerplate" not in full.description  # the employer's own blurb isn't the job
    assert full.details["time_type"] == "Full time"
    assert full.posted_at == datetime(2026, 11, 13, 5, 43, 38, tzinfo=UTC)


async def test_oracle_reads_india_through_its_facet_and_details_only_new_jobs():
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        finder = request.url.params.get("finder", "")
        asked.append(finder)
        if "recruitingCEJobRequisitionDetails" in request.url.path:
            return httpx.Response(200, json=sample("oracle_detail.json"))
        if "facetsList=LOCATIONS" in finder:
            return httpx.Response(200, json=sample("oracle_search_all.json"))
        assert "selectedLocationsFacet=300000000289360" in finder
        return httpx.Response(200, json=sample("oracle_search_india.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await oracle.fetch(JPMC, "JPMorgan Chase", http, known={"210782810", "210793423"})
    assert result.total == 7005 and result.complete
    assert [p.needs_details for p in result.postings] == [False, True, True]  # only the new one was read
    assert sum("ById" in f for f in asked) == 1


# --- Eightfold ------------------------------------------------------------------------------------------------

NETFLIX = eightfold.Board("explore.jobs.netflix.net", "netflix.com")


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://explore.jobs.netflix.net/careers?domain=netflix.com", NETFLIX),
        ("https://explore.jobs.netflix.net/careers/job/790319450010?domain=netflix.com", NETFLIX),
        ("https://acme.eightfold.ai/careers", eightfold.Board("acme.eightfold.ai", "")),
        ("https://www.acme.com/about", None),
    ],
)
def test_eightfold_links(link, expected):
    assert eightfold.Board.from_url(link) == expected


def test_eightfold_lists_and_reads_details():
    stubs = eightfold.listed(sample("eightfold_search.json"), "Netflix")
    assert [s.title for s in stubs][0] == "Workplace Specialist, Eyeline Hyderabad"
    first = stubs[0]
    assert (first.location, first.work_model, first.requisition_id) == (
        "Hyderabad, India",
        "On-site",
        "JR43565",
    )
    assert first.posted_at == datetime.fromtimestamp(1794355200, UTC)
    full = eightfold.detailed(first, sample("eightfold_detail.json"))
    assert not full.needs_details and full.description.startswith("Netflix is one of the world's leading")


async def test_eightfold_finds_the_domain_on_the_careers_page():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/careers":
            return httpx.Response(200, text='<script>window.config = {"domain": "acme.com", "x": 1}</script>')
        assert request.url.params["domain"] == "acme.com"
        if request.url.path.endswith("/jobs"):
            assert request.url.params["location"] == "India"
            return httpx.Response(200, json=sample("eightfold_search.json"))
        return httpx.Response(200, json=sample("eightfold_detail.json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await eightfold.fetch(eightfold.Board("acme.eightfold.ai", ""), "Acme", http, known=set())
    assert len(result.postings) == 3 and all(not p.needs_details for p in result.postings)


# --- Careers sites ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://careers.arm.com", careers.Site("careers.arm.com")),
        (
            "https://careers.arm.com/job/bengaluru/principal-dft-engineer/33099/103239290736",
            careers.Site("careers.arm.com"),
        ),
        ("https://www.acme.com/careers/", careers.Site("www.acme.com", "/careers")),
        ("https://www.linkedin.com/company/acme/jobs", None),
        ("https://in.indeed.com/cmp/acme", None),
        ("https://www.naukri.com/acme-jobs", None),
    ],
)
def test_careers_site_links(link, expected):
    assert careers.Site.from_url(link) == expected


def test_one_id_per_job_in_any_language():
    a = "https://jobs.sap.com/en/jobs/744000159544088/head-of-product/"
    b = "https://jobs.sap.com/de/jobs/744000159544088/head-of-product/"
    assert careers.job_id(a) == careers.job_id(b) == "744000159544088"
    assert careers.pick_urls([b, a, "https://jobs.sap.com/en/about/"], "jobs.sap.com") == [a]


def test_job_pages_and_india_hints():
    arm = "https://careers.arm.com/job/bengaluru/principal-dft-engineer/33099/103239290736"
    assert careers.is_job_url(arm, "careers.arm.com")
    assert not careers.is_job_url(
        "https://careers.arm.com/category/software-engineering-jobs/33099/8081696/1", "careers.arm.com"
    )
    assert not careers.is_job_url("https://other.example.com/job/x/123456", "careers.arm.com")
    assert careers.india_hint(arm) and careers.india_hint("https://x.com/job/Navi-Mumbai-Engineer/123456/")
    assert not careers.india_hint("https://careers.arm.com/job/cambridge/engineer/33099/1")
    assert not careers.india_hint("https://x.com/job/Indiana-Engineer/123456/")


def test_sitemaps_and_indexes():
    index = "<sitemapindex><sitemap><loc>https://a.com/jobs/sitemap.xml</loc></sitemap></sitemapindex>"
    assert careers.sitemap_urls(index) == (["https://a.com/jobs/sitemap.xml"], [])
    urlset = "<urlset><url><loc> https://a.com/job/1/x?a=1&amp;b=2 </loc></url></urlset>"
    assert careers.sitemap_urls(urlset) == ([], ["https://a.com/job/1/x?a=1&b=2"])


def test_a_job_page_with_json_ld():
    job = careers.read_page((FIXTURES / "careers_job_jsonld.html").read_text())
    assert job["title"] == "Principal DFT Engineer" and job["company"] == "ARM"
    assert job["locations"] == ["Bangalore, Karnataka, India"] and careers.in_country(job)
    assert job["description"].startswith("JOB OVERVIEW") and job["requisition"] == "2026-20193"
    assert job["posted"] == "2026-11-13"


MICRODATA = """<html><body><div itemscope itemtype="http://schema.org/JobPosting">
<h1 itemprop="title">Director, Engineering</h1>
<span itemprop="datePosted" content="2026-11-10"></span>
<div itemprop="jobLocation" itemscope itemtype="http://schema.org/Place"><div itemprop="address" itemscope>
<span itemprop="addressLocality">Pune</span><meta itemprop="addressCountry" content="IN"></div></div>
<div itemprop="description"><p>Lead the platform group.</p></div></div></body></html>"""


def test_a_job_page_with_microdata():
    job = careers.read_page(MICRODATA)
    assert job["title"] == "Director, Engineering" and job["locations"] == ["Pune, IN"]
    assert job["description"] == "Lead the platform group." and careers.in_country(job)
    assert careers.read_page("<html><body>About us</body></html>") is None


def test_a_job_outside_india_is_out_of_scope():
    job = careers.read_page(MICRODATA.replace("Pune", "Dublin").replace('content="IN"', 'content="IE"'))
    assert not careers.in_country(job)


async def test_reading_a_careers_site_follows_robots_and_reads_india_pages_first():
    india = "https://careers.acme.com/job/bengaluru/director-engineering/1/1000001"
    abroad = "https://careers.acme.com/job/dublin/director-engineering/1/1000002"
    unknown = "https://careers.acme.com/job/director-platform/1/1000003"
    known = "https://careers.acme.com/job/pune/vp-engineering/1/1000004"
    hidden = "https://careers.acme.com/private/job/1000005"
    fetched = []

    def page(city: str, country: str, title: str) -> str:
        return (
            MICRODATA.replace("Pune", city)
            .replace('content="IN"', f'content="{country}"')
            .replace("Director, Engineering", title)
        )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(
                200, text="User-agent: *\nDisallow: /private/\nSitemap: https://careers.acme.com/sm.xml\n"
            )
        if url.endswith("/sm.xml"):
            return httpx.Response(
                200,
                text="<sitemapindex><sitemap><loc>https://careers.acme.com/jobs.xml</loc></sitemap></sitemapindex>",
            )
        if url.endswith("/jobs.xml"):
            locs = "".join(f"<url><loc>{u}</loc></url>" for u in (abroad, unknown, india, known, hidden))
            return httpx.Response(200, text=f"<urlset>{locs}</urlset>")
        if url == india:
            return httpx.Response(200, text=page("Bengaluru", "IN", "Director of Engineering"))
        if url == abroad:
            return httpx.Response(200, text=page("Dublin", "IE", "Director of Engineering"))
        if url == unknown:
            return httpx.Response(200, text=page("Hyderabad", "India", "Director, Platform"))
        raise AssertionError(f"unexpected {url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await careers.fetch(
            careers.Site("careers.acme.com"), "Acme", http, known={"1000004"}, skip=set()
        )
    assert hidden not in fetched and known not in fetched  # robots.txt; already read
    assert fetched.index(india) < fetched.index(abroad)  # India-looking addresses first
    by_id = {p.source_job_id: p for p in result.postings}
    assert set(by_id) == {"1000001", "1000003", "1000004"} and result.out_of_scope == ("1000002",)
    assert by_id["1000004"].needs_details and not by_id["1000001"].needs_details
    assert by_id["1000001"].location == "Bengaluru, IN" and result.complete and result.total == 4

    # Next run: the page found abroad isn't read again.
    fetched.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await careers.fetch(
            careers.Site("careers.acme.com"),
            "Acme",
            http,
            known={"1000001", "1000003", "1000004"},
            skip={"1000002"},
        )
    assert not [u for u in fetched if "/job/" in u]


async def test_a_site_without_a_sitemap_is_read_from_its_page_and_never_closes_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404)
        if request.url.path == "/careers":
            return httpx.Response(
                200, text='<a href="/careers/jobs/123456/director">Director</a><a href="/about">x</a>'
            )
        return httpx.Response(200, text=MICRODATA)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await careers.fetch(careers.Site("www.acme.com", "/careers"), "Acme", http, known=set())
    assert [p.source_job_id for p in result.postings] == ["123456"] and not result.complete


# --- Finding boards from links -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001", ("oracle", JPMC.key)),
        ("https://explore.jobs.netflix.net/careers?domain=netflix.com", ("eightfold", NETFLIX.key)),
        ("https://careers.arm.com/job/bengaluru/x/33099/1", ("careers_page", "careers.arm.com")),
        ("https://jobs.lever.co/", None),
        ("https://www.linkedin.com/jobs/view/123", None),
    ],
)
def test_step2_links(link, expected):
    assert resolver.from_link(link) == expected


def test_portals_are_recognised():
    assert resolver.is_portal_link("https://www.naukri.com/job-listings-x") and resolver.is_portal_link(
        "foundit.in/x"
    )
    assert not resolver.is_portal_link("https://careers.arm.com")


def test_step2_boards_are_valid():
    for system, board in (
        ("oracle", JPMC.key),
        ("eightfold", NETFLIX.key),
        ("careers_page", "careers.arm.com"),
    ):
        assert resolver.valid_board(system, board), system
    assert not resolver.valid_board("careers_page", "www.linkedin.com")
    assert not resolver.valid_board("oracle", "example.com/CX_1")
