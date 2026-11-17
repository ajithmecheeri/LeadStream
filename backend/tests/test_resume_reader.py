"""Reading text out of uploads, and resume facts out of text (the rule-based reader)."""

from datetime import date

import pytest

from app.modules.documents.extract import UnreadableDocument, kind_of, text_of
from app.modules.documents.reader import read
from tests import samples

pytestmark = pytest.mark.nodb

TODAY = date(2026, 11, 1)
ASCII = samples.RESUME.replace("—", "-").replace("–", "-").replace("•", "|")


@pytest.mark.parametrize(
    ("name", "build", "kind"),
    [
        ("cv.docx", samples.docx, "docx"),
        ("cv.odt", samples.odt, "odt"),
        ("cv.rtf", samples.rtf, "rtf"),
        ("cv.pdf", samples.pdf, "pdf"),
        ("cv.txt", lambda t: t.encode(), "txt"),
    ],
)
def test_every_format_gives_the_same_lines(name, build, kind):
    # Plain ASCII: the hand-built RTF and PDF use a Latin-1 font, so dashes and bullets are simplified.
    data = build(ASCII)
    assert kind_of(name, data) == kind
    text = text_of(kind, data)
    assert "PRIYA NAIR" in text
    assert "VP, Engineering | Example Fintech Pvt Ltd - Bengaluru" in text
    assert "Jan 2021 - Present" in text
    assert read(text, TODAY).current_title == "VP, Engineering"


def test_kind_comes_from_the_contents_not_the_name():
    assert kind_of("resume.txt", samples.docx(samples.RESUME)) == "docx"
    assert kind_of("resume.docx", samples.pdf(samples.RESUME)) == "pdf"


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "Old Word"),
        ("photo.jpg", b"\xff\xd8\xff\xe0" + bytes(range(256)), "Only PDF"),
        ("broken.docx", b"PK\x03\x04 not really a zip", "damaged"),
    ],
)
def test_unreadable_files_are_explained(name, data, message):
    with pytest.raises(UnreadableDocument, match=message):
        text_of(kind_of(name, data), data)


def test_almost_empty_documents_are_refused():
    with pytest.raises(UnreadableDocument, match="Hardly any text"):
        text_of("txt", b"Priya Nair\nResume")


def test_reads_contact_details_headline_and_summary():
    f = read(samples.RESUME, TODAY)
    assert f.name == "Priya Nair"
    assert f.headline == "VP, Engineering | Cloud And AI Platforms"
    assert f.email == "priya.nair@example.com"
    assert f.phone == "+91 90000 00001"
    assert f.linkedin_url == "https://www.linkedin.com/in/priya-nair-example"
    assert f.location == "Bengaluru, India"
    assert f.summary.startswith("Engineering leader with 21+ years")
    assert f.years_experience == 21  # stated, not computed from the dates


def test_reads_roles_newest_first_with_dates():
    f = read(samples.RESUME, TODAY)
    assert [(r.title, r.company, r.start, r.end) for r in f.roles] == [
        ("VP, Engineering", "Example Fintech Pvt Ltd", "Jan 2021", "Present"),
        ("Director, Engineering", "Sample Retail Tech", "Mar 2015", "Dec 2020"),
        ("Senior Software Engineer", "Demo Systems", "Jun 2004", "Feb 2015"),
    ]
    assert f.current_title == "VP, Engineering"


def test_reads_skills_from_lists_grids_and_labelled_lines():
    skills = read(samples.RESUME, TODAY).skills
    for s in (
        "Product Development",
        "Kubernetes",
        "Generative AI",
        "LLMs",
        "RAG",
        "AWS",
        "Azure",
        "Java",
        "Terraform",
    ):
        assert s in skills, s
    assert not [s for s in skills if s.lower().startswith(("languages", "cloud & devops"))]


def test_domains_and_education():
    f = read(samples.RESUME, TODAY)
    assert {"banking", "retail"} <= set(f.domains)
    assert f.education[0].startswith("B.Tech, Computer Science")


def test_years_fall_back_to_the_earliest_role():
    f = read(samples.RESUME.replace("21+ years", "many years"), TODAY)
    assert f.years_experience == 22  # Jun 2004 to 2026


def test_header_in_a_table_and_headings_glued_to_text():
    """Two layouts seen in real resumes: name and contacts in a table, and 'EDUCATION' glued to a line."""
    data = samples.docx(
        samples.RESUME.replace("Machine Learning\nEDUCATION", "Machine LearningEDUCATION"), header_table=True
    )
    f = read(text_of("docx", data), TODAY)
    assert (f.name, f.location) == ("Priya Nair", "Bengaluru, India")
    assert f.headline == "VP, Engineering | Cloud And AI Platforms"
    assert f.education and f.education[0].startswith("B.Tech")


def test_roles_after_a_subheading_inside_experience_are_kept():
    text = samples.RESUME.replace(
        "Director, Engineering |", "Key Achievements:\nCut cloud cost by half.\nDirector, Engineering |"
    )
    assert len(read(text, TODAY).roles) == 3
