"""Requirements read by section (user feedback 2026-11-16): must-haves score, preferred items don't, and a PhD the
job requires that no resume shows caps the score. The wording is from the Nuralx "CTO - AI Security" job."""

import pytest

from app.modules.matching import requirements as rq
from app.modules.matching import scoring
from tests.test_scoring import CAND, PROFILE, job, resume

pytestmark = pytest.mark.nodb

NURALX = """Job description
Position is for an MNC Client.

Key Responsibilities
- Define and own the AI Security technology and research roadmap.
- Act as Chief Architect for AI Security platforms including scanners and policy engines.

Preferred candidate profile
- PhD from Premier institutes

- Deep expertise in Large Language Models, foundation models, fine-tuning, LoRA/adapters, and RAG-based architectures.
- Strong understanding of model internals including weight-space analysis, activation behaviour, and interpretability.
- AI security and forensics experience covering model fingerprinting, backdoor detection and supply-chain risk.
- Hands-on knowledge of model unlearning techniques, verification methods and privacy assurance.

Leadership & Personal Attributes
- Recognised technical authority with strong analytical and problem-solving skills.

Role: IT & Information Security - Other
Industry Type: IT Services & Consulting
Education
Doctorate: Ph.D/Doctorate in Any Specialization
Key Skills
Skills highlighted with '' are preferred keyskills
Artificial intelligence security
"""


def test_sections_decide_must_haves():
    r = rq.read(NURALX)
    assert [i.text[:25] for i in r.must] == [
        "PhD from Premier institut",
        "Deep expertise in Large L",
        "Strong understanding of m",
        "AI security and forensics",
        "Hands-on knowledge of mod",
        "Doctorate: Ph.D/Doctorate",
    ]
    assert {i.section for i in r.must} == {"Preferred candidate profile", "Education"}
    assert r.preferred == [] and r.degree == (3, "PhD")


def test_preferred_sections_and_lines_are_preferred_only():
    r = rq.read(
        "Requirements:\n* 15+ years leading engineering teams\n* Kubernetes is a plus\n\n"
        "Nice to have\n- Experience with Rust\n\nAbout the role\nYou must have led a cloud migration.\n"
        "We use Python daily."
    )
    assert [i.text for i in r.must] == [
        "15+ years leading engineering teams",
        "You must have led a cloud migration.",
    ]
    assert [i.text for i in r.preferred] == ["Kubernetes is a plus", "Experience with Rust"]


def test_words_that_look_like_degrees_are_not_degrees():
    assert rq.degree_in("You must be able to lead") is None
    assert rq.degree_in("Certified Scrum Master required") is None
    assert rq.degree_in("Master's degree in Computer Science") == (2, "Master's")
    assert rq.degree_in("Ph.D in machine learning") == (3, "PhD")


def test_must_haves_and_a_required_phd_bring_the_score_down():
    leader = resume(text="vp engineering aws azure kubernetes llm genai rag architecture roadmap b.tech")
    reqs = rq.read(NURALX)
    plain = job("CTO - AI Security", text=NURALX.lower(), full_description=True)
    checked = scoring.replace(plain, must=reqs.must, preferred=reqs.preferred)
    before = scoring.score_job(plain, CAND, [PROFILE], [leader])
    after = scoring.score_job(checked, CAND, [PROFILE], [leader])

    top = after.ranking[0]
    assert after.score <= scoring.DEGREE_CAP < before.score
    assert top.lost.get("must_have")
    assert after.gaps[-2:] == ["Asks for a PhD", "3 must-haves not shown"]
    statuses = {c.text[:20]: c.status for c in top.must}
    assert statuses["PhD from Premier ins"] == rq.MISSING
    assert (
        statuses["Deep expertise in La"] == rq.PARTLY
    )  # LLMs and RAG shown; fine-tuning, foundation models not
    assert "Model forensics" in next(c for c in top.must if c.text.startswith("AI security")).missing


def test_a_phd_on_the_resume_meets_it():
    phd = resume(text="vp engineering ph.d. computer science llm genai rag")
    item = rq.Item("PhD from Premier institutes", rq.MUST, None)
    assert rq.check(item, phd.text, phd.skills, []).status == rq.MET


def test_preferred_skills_are_not_counted_as_missing():
    text = "Requirements\n- AWS and Kubernetes\nPreferred skills\n- Rust\n- Kafka"
    reqs = rq.read(text)
    body = text.lower()
    for item in reqs.preferred:
        body = body.replace(item.text.lower(), " ")
    j = job(text=body, full_description=True, must=reqs.must, preferred=reqs.preferred)
    top = scoring.score_job(j, CAND, [PROFILE], [resume()]).ranking[0]
    assert "Rust" not in top.skills_missing and "Kafka" not in top.skills_missing
    assert [(c.text, c.status) for c in top.preferred] == [("Rust", rq.MISSING), ("Kafka", rq.MISSING)]
    assert [c.status for c in top.must] == [rq.MET]


def test_a_required_phd_caps_an_otherwise_strong_match():
    text = "vp engineering\nEducation\nDoctorate: Ph.D/Doctorate in Any Specialization"
    reqs = rq.read(text)
    leader = resume(text="vp engineering aws llm genai rag b.tech")
    strong = job(text="vp engineering", full_description=True)
    capped = scoring.score_job(scoring.replace(strong, must=reqs.must), CAND, [PROFILE], [leader])
    assert scoring.score_job(strong, CAND, [PROFILE], [leader]).score > scoring.DEGREE_CAP
    assert capped.score == scoring.DEGREE_CAP and capped.ranking[0].lost.get("degree")
    assert capped.gaps[-1] == "Asks for a PhD"


def test_on_equal_scores_the_resume_showing_more_comes_first():
    text = "Education\nDoctorate: Ph.D/Doctorate in Any Specialization\nRequirements\n- RAG and fine-tuning"
    reqs = rq.read(text)
    j = job(text="vp engineering rag fine-tuning", full_description=True, must=reqs.must)
    thin = resume(id="thin", text="vp engineering aws llm genai")
    rich = resume(id="rich", text="vp engineering aws llm genai rag fine-tuning")
    ranking = scoring.score_job(j, CAND, [PROFILE], [thin, rich]).ranking
    assert ranking[0].score == ranking[1].score == scoring.DEGREE_CAP
    assert ranking[0].resume_id == "rich"
