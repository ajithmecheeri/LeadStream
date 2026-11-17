"""Skills by meaning: key skills matched to a job's wording, and the skills a job asks for."""

import pytest

from app.modules.matching import skills as sk
from app.modules.matching import taxonomy as tx

pytestmark = pytest.mark.nodb


@pytest.mark.parametrize(
    ("skill", "text", "strength"),
    [
        ("Java", "we build in java and kotlin", 1.0),
        ("Java", "javascript front end", 0.0),  # whole words only
        ("C++", "modern c++ and rust", 1.0),
        # A part of the phrase, a spelling, or a narrower term is a full match.
        ("Cloud and infrastructure management", "experience with aws at scale", 1.0),
        ("AI & GenAI", "shipping llm features to customers", 1.0),
        ("Security and compliance", "own the devsecops pipeline", 1.0),
        ("Presales and solution consulting", "support pre-sales with customers", 1.0),
        ("Budgeting & Financials", "owns a p&l of $50m", 1.0),
        # Only a part's main word: a related match.
        ("Enterprise Architecture", "define the architecture of our platform", sk.RELATED),
        ("AI-driven software product development", "an ai roadmap", sk.RELATED),
        # Generic words alone never match.
        ("People and Talent Management", "we value our people", 0.0),
        ("Data-driven decision-making", "a data-driven culture", 0.0),
        ("Data-driven decision-making", "data-driven decision-making at every level", 1.0),
    ],
)
def test_key_skills_match_by_meaning(skill, text, strength):
    assert sk.match(text, skill) == strength


def test_a_job_asks_for_listed_skills_vocabulary_terms_and_key_skills_it_names():
    text = "vp engineering. lead devsecops, kubernetes (k8s) and generative ai. own the p&l."
    asked = sk.asked_for(text, ["GenAI", "Kubernetes"], ["Security and compliance", "Team Leadership"])
    # Listed first as worded; spellings of one skill appear once; a key skill joins when the job names it.
    assert asked == ["GenAI", "Kubernetes", "DevSecOps", "P&L", "Security and compliance"]
    # Naming DevSecOps isn't asking for DevOps.
    assert "DevOps" not in asked


def test_site_reliability_practices_are_skills_a_job_asks_for():
    # From a Director, Site Reliability Engineering listing (2026-11-04: nothing showed as missing).
    text = (
        "lead post-incident reviews, drive root-cause analysis. participate in on-call rotations. finops. "
        "infrastructure as a code (terraform). change and release management. a multi-cloud environment."
    )
    asked = sk.asked_for(text, [], [])
    for skill in [
        "Incident management",
        "FinOps",
        "Multi-cloud",
        "Infrastructure as code",
        "Release management",
    ]:
        assert skill in asked
    assert asked.count("Incident management") == 1  # one skill, however many of its spellings the job uses
    assert sk.shows("ran incident response and slos for the platform", set(), "Incident management")


def test_a_director_of_engineering_listing_names_its_languages_and_cloud_skills():
    # From Capital One's Director - Software Engineering listing (user feedback 2026-11-11).
    text = (
        "composing powerful, safe and explainable ai capabilities\n"
        "bachelor's degree in computer science or a related quantitative field (statistics, economics, "
        "operations research, analytics, mathematics, engineering)\n"
        "enterprise architecture and design patterns\n"
        "cloud computing (aws, microsoft azure, google cloud)\n"
        "data architecture\n"
        "web technologies (javascript, typescript and spa frameworks)\n"
        "designing and building distributed hpc and ml systems\n"
        "coding in commonly used languages like go, java, javascript/typescript, python, rust, c#, scala\n"
        "experience with database and database management systems\n"
        "experience with networking protocols. lead a full-stack team.\n"
        "go to market with partners."
    )
    asked = sk.asked_for(text, [], [])
    for skill in [
        "AWS",
        "Azure",
        "GCP",
        "JavaScript",
        "TypeScript",
        "Single-page apps",
        "HPC",
        "Golang",
        "Java",
        "Python",
        "Rust",
        "C#",
        "Scala",
        "Databases",
        "Networking protocols",
        "Full-stack",
        "Data architecture",
        "Design patterns",
        "Enterprise architecture",
    ]:
        assert skill in asked, skill
    # "safe and explainable" isn't SAFe, and the subjects of a degree aren't skills.
    assert "SAFe" not in asked and "Analytics" not in asked
    assert "Golang" not in sk.asked_for("go to market with partners.", [], [])
    assert "SAFe" in sk.asked_for("agile and safe ceremonies; scaled agile framework", [], [])


def test_words_every_engineering_listing_uses_dont_match_a_key_skill():
    # From Caxton's Head of Trading Systems and Software Engineering listing (user feedback 2026-11-13).
    text = (
        "builds applications and services supporting trading, compliance and operations. "
        "own the technical direction. unit and integration testing, refactoring, ci/cd pipelines. "
        "production reliability in trading systems. tradeweb and other trading platforms."
    )
    for skill in [
        "AI/LLM Integration & Deployment",
        "AI Tool Integration",
        "Microservices & Full-Stack Systems",
        "PCI Compliance",
        "Budgeting & P&L Ownership",
    ]:
        assert sk.match(text, skill) == 0, skill
    assert sk.match("deploying llm features", "AI/LLM Integration & Deployment") == sk.RELATED
    assert sk.match("we run microservices", "Microservices & Full-Stack Systems") == 1.0
    assert sk.match("pci dss audits", "PCI Compliance") == 1.0


def test_a_trading_systems_job_asks_for_its_trading_skills():
    # From Caxton's Head of Trading Systems and Software Engineering listing (user feedback 2026-11-14).
    text = (
        "head our trading technology and software engineering team. the team develops our in-house order "
        "management system and manages fix connectivity to all trading venues. detailed knowledge of the "
        "order-to-trade lifecycle. knowledge of real-time market data feeds and bloomberg apis such as sapi, "
        "b-pipe and desktop api. a global trading and investment firm."
    )
    asked = sk.asked_for(text, [], [])
    for skill in [
        "Trading systems",
        "FIX protocol",
        "Order management systems",
        "Trade lifecycle",
        "Market data",
        "Bloomberg API",
    ]:
        assert skill in asked, skill
    assert asked.count("Trading systems") == 1
    # A fix to a bug isn't the FIX protocol, and trading alone isn't a trading system.
    assert "FIX protocol" not in sk.asked_for("ship the fix quickly. a trading company.", [], [])
    assert "Trading systems" not in sk.asked_for("we sell to trading companies", [], [])
    assert sk.shows("built fix engine connectivity to brokers", set(), "FIX protocol")


def test_legal_boilerplate_is_not_part_of_the_job():
    text = (
        "Lead the SRE organisation on AWS.\n"
        "Okta is an Equal Opportunity Employer.\n"
        "Okta may use Automated Employment Decision Tools (AEDT), as defined by New York City Local Law 144, "
        "that use artificial intelligence, machine learning, or other automated processes."
    )
    kept = tx.without_boilerplate(text).lower()
    assert "lead the sre organisation" in kept
    assert "Machine learning" not in sk.asked_for(kept, [], [])
    assert sk.match(kept, "AI & GenAI") == 0


def test_a_resume_shows_a_skill_only_fully():
    resume = "led devops and ci/cd for a kubernetes platform on aws"
    assert sk.shows(resume, set(), "Kubernetes")
    assert sk.shows(resume, set(), "k8s")
    assert not sk.shows(resume, set(), "DevSecOps")  # DevOps isn't DevSecOps
    assert sk.shows(resume, {"devsecops"}, "DevSecOps")  # "I have this skill" on the job page
    # The user's own broad key skill is checked by meaning, like when matching it to a job.
    assert not sk.shows(resume, set(), "Infrastructure management")
    assert sk.shows(resume, set(), "Infrastructure management", by_meaning=True)


def test_a_tool_on_the_profile_or_resume_shows_its_practice():
    # 2026-11-12: Terraform on the profile, yet a PwC job listed "Infrastructure as code" as missing.
    assert sk.shows("", {"terraform"}, "Infrastructure as code")
    assert sk.shows("provisioned aws with cloudformation templates", set(), "IaC")
    assert not sk.shows("ran kubernetes clusters", {"docker"}, "Infrastructure as code")
