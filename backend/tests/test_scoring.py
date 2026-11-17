"""Rule-based scoring: the words it understands, hard filters, factors, blending and the verdict."""

from dataclasses import replace

import pytest

from app.modules.matching import scoring, taxonomy
from app.modules.matching.scoring import Candidate, JobInput, ProfileInput, ResumeInput
from app.modules.profiles.schemas import DEFAULT_WEIGHTS

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("CTO/Head Technology/Chief Engineering Head", 9),
        ("Chief Architect - Physical AI & Robotics", 6),
        ("Chief Engineer", 6),
        ("Principal Technologist / Field CTO", 7),  # customer-facing, not the company CTO
        ("Chief of Staff, Office of the CTO", 6),
        ("Sr. Vice President- Projects", 8),
        ("VP, Product Development", 7),
        ("Program Manager Global - DVP/AVP - Automotive Domain", 6),
        ("Head of AI Platform & Architecture", 6),
        ("Director, Technical POM Product Management", 5),
        ("Principal AI Architect", 4),
        ("Engineering Manager", 3),
        ("Something Else", None),
    ],
)
def test_seniority_from_titles(title, level):
    assert taxonomy.seniority(title) == level


def test_families_cities_and_remote():
    assert taxonomy.families("Head S&OP/SIOP") == {"operations"}
    assert taxonomy.families("SEG & India CFO") == {"finance"}
    assert {"technology", "ai_data"} <= taxonomy.families("Head of AI Platform & Architecture")
    assert taxonomy.families("Director, Product Design") == {"design"}
    assert taxonomy.families("Product Development") == {"technology", "product"}
    # A packaged-application specialism is its own field; the title's main function decides.
    assert taxonomy.title_families("SAP GRC / BR&C Technology Architect") == {"enterprise_apps"}
    assert taxonomy.title_families("SAP Technology Architect") == {"enterprise_apps"}
    assert taxonomy.title_families("ServiceNow Developer") == {"enterprise_apps"}
    assert taxonomy.title_families("VP Engineering, SAP Labs") == {"technology"}
    assert taxonomy.cities("Bangalore Urban") == ({"bengaluru"}, False)
    assert taxonomy.cities("Pune(Kharadi)") == ({"pune"}, False)
    assert taxonomy.cities("Pune, Chennai, Be...") == ({"pune", "chennai"}, True)
    assert taxonomy.cities("Gurgaon") == ({"gurugram"}, False)
    assert taxonomy.is_remote("Remote, India") and not taxonomy.is_remote("Bengaluru")


@pytest.mark.parametrize(
    ("text", "lakh"),
    [
        ("₹5M-₹6M / year", 60.0),
        ("85 LPA", 85.0),
        ("1.1 Cr", 110.0),
        ("₹ 25,00,000", 25.0),
        ("40-55 Lacs", 55.0),
        (None, None),
    ],
)
def test_salary_in_lakh(text, lakh):
    assert scoring.lakh(text) == lakh


def test_experience_ranges():
    assert scoring.years_range("14-20 years") == (14, 20)
    assert scoring.years_range("15+ Yrs") == (15, 20)
    assert scoring.years_range(None) is None


def job(title="VP Engineering", location="Bengaluru", **kw) -> JobInput:
    base = dict(
        title=title,
        company="Example Co",
        location=location,
        work_model=None,
        experience=None,
        salary=None,
        skills=[],
        text=title.lower(),
        full_description=False,
    )
    return JobInput(**{**base, **kw})


CAND = Candidate(
    years=21,
    level=7,
    families={"technology", "product"},
    locations=["Bengaluru"],
    expected_ctc_lakh=100.0,
    domains=["banking"],
)
PROFILE = ProfileInput(
    id="p1",
    name="VP Engineering",
    target_roles=["VP Engineering"],
    locations=["Bengaluru"],
    work_models=["Hybrid"],
    min_seniority=5,
    excluded_companies=["Bad Corp"],
    weights=dict(DEFAULT_WEIGHTS),
    threshold=85,
)


def resume(
    id="r1",
    text="vp engineering aws azure kubernetes microservices llm genai rag product development saas",
    similarity=None,
) -> ResumeInput:
    return ResumeInput(id=id, label=id, text=text, skills={"aws", "python"}, similarity=similarity)


def test_hard_filters_name_the_reason():
    assert scoring.hard_filter(job(location="Pune"), PROFILE) == "Pune isn't one of your locations"
    assert (
        scoring.hard_filter(job(company="Bad Corp India"), PROFILE)
        == "Bad Corp India is on your excluded list"
    )
    assert scoring.hard_filter(job(title="Engineering Manager"), PROFILE) == "Below your seniority (Manager)"
    # Unknown or cut-off facts never rule a job out.
    assert scoring.hard_filter(job(location=None), PROFILE) is None
    assert scoring.hard_filter(job(location="Pune, Chennai, Be..."), PROFILE) is None
    assert (
        scoring.hard_filter(job(title="Senior Manager, Platforms"), PROFILE) is None
    )  # one level below is fine
    remote = ProfileInput(**{**PROFILE.__dict__, "work_models": ["Remote"]})
    assert scoring.hard_filter(job(location="Pune", work_model="Remote"), remote) is None


def test_factors_the_job_says_nothing_about_are_left_out():
    f = scoring.factors(job(), CAND, PROFILE, resume())
    # Title and location only: no salary, skills, experience or domain. "Engineering" in the title is a
    # core-theme signal.
    assert set(f) == {"role", "loc", "core"}
    assert f["loc"] == 100 and f["role"] == 100


def test_factors_with_a_full_job():
    j = job(
        experience="15-22 years",
        salary="1.2 Cr",
        skills=["AWS", "Python", "Kafka"],
        text="vp engineering for a bank: aws, kubernetes, llm, genai, product development, saas platform",
        full_description=True,
    )
    f = scoring.factors(j, CAND, PROFILE, resume())
    assert f["exp"] == 100 and f["comp"] == 100 and f["domain"] == 100
    # Listed AWS, Python, Kafka plus Kubernetes, GenAI ("llm") and SaaS from the text: all but Kafka shown.
    assert f["skills"] == 83
    assert f["ai"] >= 80 and f["cloud"] >= 80


def test_role_family_mismatch_scores_low():
    finance = scoring.factors(job(title="Director, Finance"), CAND, PROFILE, resume())
    assert finance["role"] < 40


def test_similarity_blends_into_the_score():
    f = {"role": 100, "loc": 100}
    assert scoring.combine(f, DEFAULT_WEIGHTS, None) == 100
    assert (
        scoring.similarity_score(scoring.SIM_LOW) == 0 and scoring.similarity_score(scoring.SIM_HIGH) == 100
    )
    assert scoring.combine(f, DEFAULT_WEIGHTS, 0) == round(100 * (1 - scoring.SIM_WEIGHT))
    assert scoring.combine({}, DEFAULT_WEIGHTS, None) == 0


def test_verdict_bands_and_resume_ranking():
    strong = scoring.score_job(
        job(full_description=True),
        CAND,
        [PROFILE],
        [resume("a"), resume("b", text="vp engineering", similarity=0.2)],
    )
    assert strong.band == "strong" and strong.profile_id == "p1" and not strong.provisional
    assert [r.resume_id for r in strong.ranking] == ["a", "b"]  # b's low similarity pulls it down

    weak = scoring.score_job(job(title="Director, Finance"), CAND, [PROFILE], [resume()])
    assert weak.band == "low" and "Role and seniority" in weak.gaps
    assert weak.score <= scoring.CLASH_CAP  # a different line of work is capped below the Top band

    out = scoring.score_job(job(location="Pune"), CAND, [PROFILE], [resume()])
    assert (out.band, out.filter_reason) == ("filtered", "Pune isn't one of your locations")


def test_the_best_passing_profile_wins():
    pune = ProfileInput(**{**PROFILE.__dict__, "id": "p2", "name": "Pune", "locations": ["Pune"]})
    v = scoring.score_job(job(location="Pune", full_description=True), CAND, [PROFILE, pune], [resume()])
    assert (v.band, v.profile_id) == ("strong", "p2")


def test_a_title_only_job_is_judged_without_wording_and_tops_out_as_good():
    far = [resume(similarity=0.2)]  # a title alone reads as far from a whole resume
    title_only = scoring.score_job(job(), CAND, [PROFILE], far)
    assert title_only.provisional and title_only.band == "good" and title_only.score == PROFILE.threshold - 1
    assert "similarity" not in title_only.ranking[0].lost and title_only.ranking[0].lost["title_only"] > 0
    described = scoring.score_job(job(full_description=True), CAND, [PROFILE], far)
    assert described.ranking[0].lost["similarity"] > 0  # wording counts once the description is in


def test_without_search_profiles_nothing_is_filtered():
    v = scoring.score_job(job(location="Pune"), CAND, [], [resume()])
    assert v.band != "filtered" and v.profile_id is None


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Director of Recruiting, Engineering & IT, Bangalore India", {"people"}),
        ("Director, Product Design", {"design"}),
        ("Director of Engineering (Data Infrastructure)", {"technology"}),
        ("VP - Engineering", {"technology"}),
        ("Head (Senior Manager) - Industrial Relations", {"people"}),
        ("Associate Director - Legal", {"legal"}),
        ("Director, Support (Bengaluru)", {"customer"}),
        ("Growth Management - Merchant Lending (GM/DGM)", {"lending"}),
        ("City Supply Head", {"operations"}),
        ("Director, Product Management - Integrations", {"product"}),
        ("Principal Software Development Engineer - Agentic Systems", {"technology"}),
        ("Country Director, India", set()),
    ],
)
def test_title_families_follow_the_main_function(title, expected):
    assert taxonomy.title_families(title) == expected


def test_out_of_field_titles_clash_with_an_engineering_leader():
    cand = scoring.Candidate(
        years=24,
        level=7,
        families=taxonomy.families(
            "Engineering and product leader, cloud SaaS Platforms and Product Development"
        ),
        locations=["Bengaluru"],
        expected_ctc_lakh=None,
        domains=[],
    )

    def job(title):
        return scoring.JobInput(title, "X", "Bengaluru", None, None, None, [], "", False)

    for title in (
        "Director, Product Design",
        "Director of Recruiting, Engineering & IT",
        "Associate Director - Legal",
    ):
        assert scoring.family_clash(job(title), cand), title
    for title in ("Director of Engineering", "Director - Product", "Director, Solutions Architecture"):
        assert not scoring.family_clash(job(title), cand), title


def test_digital_marketing_is_marketing_not_technology():
    # Strategy and operations beside a function only qualify it; alone they are the function.
    assert taxonomy.title_families("DIRECTOR,DIGITAL MARKETING STRATEGY & OPERATIONS") == {"marketing"}
    assert taxonomy.title_families("Director, Strategy & Operations") == {"strategy", "operations"}
    assert "technology" in taxonomy.title_families("Head of Digital Transformation")
    cand = Candidate(21, 7, {"technology", "product", "strategy"}, ["Bengaluru"], None, [])
    assert scoring.family_clash(job(title="DIRECTOR,DIGITAL MARKETING STRATEGY & OPERATIONS"), cand)


MCCB = (
    "mccb product engineering lead. expertise in product development, industrialization, manufacturing "
    "processes, validation and quality engineering for low-voltage switchgear products. drive new product "
    "introduction (npi), pilot builds. apqp: pfmea, control plan, cp/cpk, ppap. moulding, stamping, plating. "
    "our digital and software technology experts; certifications in cloud and ai."
)


def test_specialisms_come_from_the_description():
    assert taxonomy.specialisms(MCCB) == {"hardware"}
    sap = "we need s/4hana, abap and fiori experience on sap erp."
    assert taxonomy.specialisms(sap, "HCLTech") == {"enterprise_apps"}
    # A vendor building its own product, or a software job listing integrations, is not the specialism.
    assert taxonomy.specialisms(sap, "SAP Labs India") == set()
    assert taxonomy.specialisms("connectors for salesforce, workday, servicenow and sap erp.") == set()
    assert taxonomy.specialisms("salesforce sales cloud, apex and lightning web components.") == {
        "enterprise_apps"
    }
    oracle = (
        "oracle technical director. oracle cloud infrastructure and oracle data integration; oracle application "
        "development framework (adf) and oracle business intelligence (bi) publisher."
    )
    assert taxonomy.specialisms(oracle, "PwC Acceleration Center India") == {"enterprise_apps"}
    assert taxonomy.specialisms("we migrate from oracle and postgres to the cloud.") == set()
    assert taxonomy.has_specialism("led sap s/4hana rollout", "enterprise_apps")
    assert not taxonomy.has_specialism("moved billing off oracle onto an in-house erp", "enterprise_apps")
    assert not taxonomy.has_specialism(resume().text, "hardware")


def test_a_specialist_job_the_resumes_dont_show_stays_out_of_top_matches():
    mccb = job(
        title="MCCB Product Engineering", company="Capgemini Engineering", text=MCCB, full_description=True
    )
    v = scoring.score_job(mccb, CAND, [PROFILE], [resume(similarity=0.7)])
    assert v.score <= scoring.SPECIALISM_CAP and v.band == "low"
    assert v.ranking[0].lost.get("clash", 0) > 0
    # A resume that shows the specialism lifts the cap.
    maker = resume(text=resume().text + " apqp ppap npi for switchgear", similarity=0.7)
    assert scoring.score_job(mccb, CAND, [PROFILE], [maker]).score > scoring.SPECIALISM_CAP


AXIRO = (
    "a fabless semiconductor design company driving innovation in rf, wireless infrastructure and high-speed "
    "connectivity. with millions of chips powering global networks and expertise in rf, mmwave and gan. we "
    "are seeking a product line director to lead strategy, roadmap and p&l for a portfolio of semiconductor "
    "products."
)


def test_a_chip_job_is_another_line_of_work_for_a_software_product_leader():
    # User feedback 2026-11-09: Axiro's "Product Line Director" scored 85; every product-management word matched.
    assert taxonomy.specialisms(AXIRO, "Axiro Semiconductor") == {"semiconductor"}
    axiro = job(
        title="Product Line Director", company="Axiro Semiconductor", text=AXIRO, full_description=True
    )
    v = scoring.score_job(axiro, CAND, [PROFILE], [resume(similarity=0.7)])
    assert v.score <= scoring.SPECIALISM_CAP and v.band == "low"
    # A title that names chip design is enough, even on an alert with nothing else.
    assert taxonomy.title_specialisms("Senior Director, Analog & Mixed-Signal (AMS) Engineering") == {
        "semiconductor"
    }
    # Software jobs that mention chips, Silicon Valley or Palantir Foundry are not chip jobs.
    assert (
        taxonomy.specialisms("ai chips team in silicon valley building on palantir foundry and kubernetes.")
        == set()
    )
    assert taxonomy.title_specialisms("Director, Product Management") == set()


@pytest.mark.parametrize(
    ("title", "company", "text", "specialism"),
    [
        (  # Rakuten Symphony, 92 before
            "Senior Director, Software Development (Wireless O-RAN)",
            "Altiostar / Rakuten Symphony",
            "architecture for advanced wireless platforms across 5g, o-ran and emerging 6g, spanning phy, baseband "
            "and platform layers. must have been part of a ran product organization. prior experience working "
            "directly on ran (radio access network) systems.",
            "wireless",
        ),
        (  # HARMAN, 87 before
            "Executive Director, Product Management, SBU Connectivity",
            "HARMAN India",
            "20+ years in automotive, connectivity or adjacent industries. broad understanding of automotive "
            "connectivity and telematics technologies including cellular/5g, v2x, wi-fi/bluetooth/gnss, ota and "
            "automotive-grade hardware/software platforms. global oem commercialization.",
            "automotive",
        ),
        (  # GSK, 89 before
            "Senior Director - Design Assurance & Product Management",
            "GSK",
            "own the governance framework and the independent design assurance process. maintain the risk "
            "register, prioritised against the cyber risk appetite. engage internal audit, regulators and the "
            "second and third lines of defence. present security posture reporting to the ciso.",
            "security_governance",
        ),
    ],
)
def test_jobs_the_user_said_were_another_field_are_capped(title, company, text, specialism):
    # User feedback 2026-11-11 ("Not my field"): each scored Strong for a software product and engineering leader.
    assert specialism in taxonomy.specialisms(f"{title.lower()}\n{text}", company)
    v = scoring.score_job(
        job(title=title, company=company, text=text, full_description=True),
        CAND,
        [PROFILE],
        [resume(similarity=0.7)],
    )
    assert v.score <= scoring.SPECIALISM_CAP and v.band == "low"


def test_a_footwear_and_apparel_title_and_a_consulting_title_are_other_fields():
    # PUMA's "Head, Product Line Management, Footwear & Apparel" scored 84 from its title alone.
    assert taxonomy.title_specialisms("Head, Product Line Management, Footwear & Apparel") == {
        "apparel_retail"
    }
    puma = job(title="Head, Product Line Management, Footwear & Apparel", company="PUMA")
    assert scoring.score_job(puma, CAND, [PROFILE], [resume(similarity=0.7)]).band == "low"
    # NTT DATA's "Data & AI Consulting Mgt. Managing Dir." (client advisory and presales) scored 76.
    assert taxonomy.title_families("Data & AI Consulting Mgt. Managing Dir.") == {"consulting"}
    ntt = job(title="Data & AI Consulting Mgt. Managing Dir.", company="NTT DATA")
    assert scoring.score_job(ntt, CAND, [PROFILE], [resume(similarity=0.7)]).score <= scoring.CLASH_CAP
    # Software jobs that mention the same words are not those fields.
    assert (
        taxonomy.specialisms("we ran a retail e-commerce platform; ota updates for our mobile app; 5g-ready.")
        == set()
    )
    assert taxonomy.specialisms("soc 2 audit evidence and cybersecurity reviews with the ciso.") == set()
    assert taxonomy.title_families("Director, Product Management") == {"product"}


EV_JOB = (
    "vp engineering. shell recharge solutions delivers ev charging infrastructure; we operate 70,000 charge "
    "points, a cpo and msp platform.\n"
    "• ev industry experience: 15+ years, including leadership in ev charging, e-mobility, cpo/msp platforms, "
    "charging networks or energy management.\n"
    "• strong knowledge of ev charging ecosystems, including roaming, ocpp and ocpi charging protocols.\n"
    "• experience with aws, kubernetes and microservices."
)


def test_industries_come_from_what_the_job_asks_for():
    assert taxonomy.industries(EV_JOB) == {"ev_charging"}
    # What the job page lists under the industry gap.
    assert taxonomy.industry_terms(EV_JOB)[:4] == [
        "ev charging",
        "e-mobility",
        "charging networks",
        "charging protocols",
    ]
    # An EV company describing itself, for a job that asks for no EV experience, is not the industry.
    blurb = EV_JOB.split("\n")[0] + "\n• experience with aws, kubernetes and microservices."
    assert taxonomy.industries(blurb) == set()


def test_a_job_asking_for_industry_experience_the_resumes_dont_show_stays_out_of_top_matches():
    ev = job(company="Shell Recharge Solutions", text=EV_JOB, full_description=True)
    v = scoring.score_job(ev, CAND, [PROFILE], [resume(similarity=0.7)])
    assert v.score <= scoring.INDUSTRY_CAP and v.band == "low"
    assert v.ranking[0].lost.get("industry", 0) > 0 and "clash" not in v.ranking[0].lost
    ev_leader = resume(text=resume().text + " led ev charging platform (ocpp)", similarity=0.7)
    assert scoring.score_job(ev, CAND, [PROFILE], [ev_leader]).band == "strong"


SKILLED = ProfileInput(**{**PROFILE.__dict__, "skills": ["Java", "Kafka", "Spring Boot", "C++"]})


def test_key_skills_found_in_the_job_raise_the_skills_factor():
    described = job(
        text="vp engineering. we build with java, kafka and spring boot on aws.", full_description=True
    )
    hits = scoring.profile_skill_hits(described, SKILLED)
    assert [s for s, _ in hits] == ["Java", "Kafka", "Spring Boot"]

    def skills(j, p=SKILLED):
        return scoring.factors(j, CAND, p, resume()).get("skills")

    one = job(text="vp engineering. java shop.", full_description=True)
    none = job(text="vp engineering. we build with go and rust.", full_description=True)
    # More of your key skills, a higher score; a full description that names none of them scores 0…
    assert skills(described) > skills(one) > skills(none) == 0
    # …but a title-only alert says too little to tell: its title can't name six key skills, so only whether
    # the resume shows the ones it does name counts. Without key skills only the resume part counts.
    assert skills(job()) is None
    cpp = job(title="Head of Engineering (C++)")
    assert scoring.factors(cpp, CAND, SKILLED, resume(text="c++ for 20 years")).get("skills") == 100
    assert skills(described, PROFILE) == 25  # the resume shows AWS, not Java, Kafka or Spring Boot
    # Whole words: "java" isn't in "javascript" and "c++" isn't "c".
    assert scoring.profile_skill_hits(job(text="javascript and c developers"), SKILLED) == []
    assert scoring.profile_skill_hits(job(title="Head of Engineering (C++)"), SKILLED) == [("C++", 1.0)]


def test_the_job_page_lists_the_skills_asked_for_that_the_resume_lacks():
    described = job(text="vp engineering. we run devsecops on kubernetes and aws.", full_description=True)
    have, missing = scoring.skill_split(described, resume())
    assert (have, missing) == (["AWS", "Kubernetes"], ["DevSecOps"])


def test_key_skills_lift_the_score_and_are_named_in_the_reason():
    described = job(
        text="vp engineering. we build with java, kafka and spring boot on aws.", full_description=True
    )
    # The Skills weight the profile editor suggests once key skills are added (default is 5).
    weights = {**DEFAULT_WEIGHTS, "skills": 15, "exp": 5}
    plain = scoring.score_job(
        described, CAND, [ProfileInput(**{**PROFILE.__dict__, "weights": weights})], [resume()]
    )
    skilled = scoring.score_job(
        described, CAND, [ProfileInput(**{**SKILLED.__dict__, "weights": weights})], [resume()]
    )
    assert skilled.score > plain.score
    assert skilled.ranking[0].reason.startswith("Asks for 3 of your key skills (Java, Kafka, Spring Boot)")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Principal Engineer, UCX Platform, VP", "ic"),  # a bank's VP is a grade
        ("Staff Software Engineer - Agentic Systems", "ic"),
        ("Principal AI Architect", "ic"),
        ("VP Product Development", "lead"),
        ("Head of Engineering", "lead"),
        ("Engineering Manager", "lead"),
        ("Director, Product Management", "lead"),
        ("Senior Product Manager", None),
    ],
)
def test_the_track_comes_from_the_titles_main_part(title, expected):
    assert taxonomy.track(title) == expected


def test_a_hands_on_role_for_a_leader_is_at_most_good_and_shows_as_a_role_gap():
    leader = Candidate(**{**CAND.__dict__, "track": "lead"})
    ic = job(title="Principal Engineer, UCX Platform, VP", full_description=True)
    v = scoring.score_job(ic, leader, [PROFILE], [resume(similarity=0.7)])
    assert v.band == "good" and v.score < PROFILE.threshold
    assert v.ranking[0].factors["role"] <= scoring.TRACK_ROLE and v.ranking[0].lost["role"] > 0
    # Someone on the hands-on track isn't held back; nor is a leader applying to lead.
    assert scoring.score_job(ic, CAND, [PROFILE], [resume(similarity=0.7)]).band == "strong"
    vp = job(title="VP Engineering", full_description=True)
    assert scoring.score_job(vp, leader, [PROFILE], [resume(similarity=0.7)]).band == "strong"


def test_each_missing_skill_costs_points_until_the_user_has_it():
    asks = job(
        text="vp engineering. aws, kubernetes and microservices; kafka and solution architecture.",
        full_description=True,
    )
    v = scoring.score_job(asks, CAND, [PROFILE], [resume(similarity=0.7)])
    top = v.ranking[0]
    assert top.skills_missing == ["Kafka", "Solution architecture"]
    assert top.lost["missing_skills"] == 2 * scoring.MISSING_SKILL_POINTS and v.score <= 100 - 6
    # "I have this skill" adds them to the profile, which the resume input carries as skills.
    have = resume(similarity=0.7)
    have.skills |= {"kafka", "solution architecture"}
    assert scoring.score_job(asks, CAND, [PROFILE], [have]).score > v.score


def test_a_job_asking_for_fewer_years_loses_a_share_and_another_field_is_capped_at_40():
    # User, 2026-11-11: "experience difference you can reduce the fitment to 10-20%. But the primary skill is
    # missing or if it is a totally different domain, you can put the match to 40%."
    vp = job(
        title="VP Engineering",
        text="vp engineering aws kubernetes microservices genai",
        full_description=True,
    )
    full = scoring.score_job(vp, CAND, [PROFILE], [resume(similarity=0.7)])
    cut = scoring.score_job(replace(vp, years_short=0.2), CAND, [PROFILE], [resume(similarity=0.7)])
    assert cut.score == full.score - round(full.score * 0.2)
    assert cut.ranking[0].lost["years_short"] == round(full.score * 0.2)
    assert scoring.CLASH_CAP == scoring.SPECIALISM_CAP == scoring.INDUSTRY_CAP == 40
    # GE HealthCare's "Senior Director, Software Engineering": embedded knowledge required.
    ge = (
        "lead embedded software teams building firmware for medical devices. experience with rtos, "
        "microcontrollers, device drivers and iec 62304. c/c++."
    )
    assert taxonomy.specialisms(ge, "GE HealthCare") == {"embedded"}
    v = scoring.score_job(
        job(
            title="Senior Director, Software Engineering",
            company="GE HealthCare",
            text=ge,
            full_description=True,
        ),
        CAND,
        [PROFILE],
        [resume(similarity=0.7)],
    )
    assert v.score <= 40
    assert (
        taxonomy.specialisms("embedded analytics in our saas product; engineers embedded in squads.") == set()
    )


def test_regulated_medical_device_software_is_a_field_of_its_own():
    # GE HealthCare's "Senior Director, Software Engineering" scored 92 (user: "embedded knowledge is required").
    ge = (
        "across regulated medical software. 12+ years software engineering and significant regulated-health-"
        "software leadership. apply standards such as iec 62304, iso 14971, iec 82304-1, and aami tir45. "
        "deep software engineering background across cloud, data, embedded, or platform systems."
    )
    assert "medical_devices" in taxonomy.specialisms(ge, "GE HealthCare")
    v = scoring.score_job(
        job(
            title="Senior Director, Software Engineering",
            company="GE HealthCare",
            text=ge,
            full_description=True,
        ),
        CAND,
        [PROFILE],
        [resume(similarity=0.7)],
    )
    assert v.score <= 40
    assert taxonomy.specialisms("a health-tech saas startup; fda guidance awareness is a plus.") == set()
