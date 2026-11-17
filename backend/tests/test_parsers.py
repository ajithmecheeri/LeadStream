"""Alert email parsers, checked against real (sanitised) emails in tests/fixtures/emails.

Each `<name>.eml` has a hand-written `<name>.expected.json`: the jobs a person reading the email would
list. Only the fields named in the expected file are compared.
"""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.modules.catalog.parsers import parse_email
from app.modules.catalog.parsers.normalize import fingerprint, split_location, strip_query
from app.modules.catalog.parsers.registry import load

pytestmark = pytest.mark.nodb

EMAILS = Path(__file__).parent / "fixtures" / "emails"
SAMPLES = sorted(EMAILS.glob("*.eml"))
# The test user's own address, listed on Mail setup: the AI assistant samples come from it.
OWN = frozenset({"candidate@example.com"})
PORTALS = ("linkedin", "naukri", "naukri_rdx")


def test_every_sample_has_an_expected_parse():
    assert SAMPLES
    missing = [p.name for p in SAMPLES if not p.with_suffix(".expected.json").exists()]
    assert not missing, f"add an .expected.json for {missing}"


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_golden(path: Path):
    expected = json.loads(path.with_suffix(".expected.json").read_text())
    result = parse_email(path.read_bytes(), OWN)

    assert result is not None
    assert result.parser == expected["parser"]
    assert result.alert_name == expected["alert_name"]
    assert result.warnings == []
    got = [asdict(c) for c in result.cards]
    assert len(got) == len(expected["cards"])
    for card, want in zip(got, expected["cards"], strict=True):
        card["skills"], card["card_lines"] = list(card["skills"]), list(card["card_lines"])
        assert {k: card[k] for k in want} == want


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.stem)
def test_public_links_carry_no_tokens(path: Path):
    for card in parse_email(path.read_bytes(), OWN).cards:
        if card.canonical_url:
            assert "?" not in card.canonical_url and "#" not in card.canonical_url
            assert card.canonical_url.startswith("https://www." if card.source in PORTALS else "https://")


def test_linkedin_urls_use_the_job_id():
    result = parse_email((EMAILS / "linkedin-alert-vice-president-bangalore-2026-10-29.eml").read_bytes())
    assert result.cards[0].canonical_url == "https://www.linkedin.com/jobs/view/4484420848/"
    assert result.cards[2].card_lines == ("2 connections",)
    assert result.cards[3].card_lines == ("Actively recruiting", "Easy Apply")
    assert result.cards[2].details == {}  # nothing about the recipient goes in the public details


def test_linkedin_falls_back_to_plain_text():
    original = load((EMAILS / "linkedin-alert-vice-president-bangalore-2026-10-29.eml").read_bytes())
    msg = EmailMessage()
    for key in ("From", "Subject", "X-LinkedIn-Template"):
        msg[key] = original[key]
    msg.set_content(original.get_body(("plain",)).get_content())

    result = parse_email(msg.as_bytes())

    assert [c.source_job_id for c in result.cards] == [
        "4484420848",
        "4484441744",
        "4484103275",
        "4483841832",
        "4482272812",
        "4482543710",
    ]
    assert result.cards[0].company == "Commonwealth Bank"
    assert result.warnings == ["no job cards in HTML; used the plain-text part"]


def test_recruiter_invite_keeps_description_and_private_apply_link():
    card = parse_email((EMAILS / "naukri-recruiter-invite-vp-ai-2026-09-18.eml").read_bytes()).cards[0]
    assert card.description.startswith("Roles and Responsibilities :\n- Design and develop")
    assert card.description.count("\n- ") == 7  # 4 responsibilities + 3 requirements
    assert "applyBroadcastMail" in card.apply_url and "mid=180926021094" in card.apply_url


def _email(sender: str, subject: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["Subject"] = sender, subject
    msg.set_content(body)
    return msg.as_bytes()


@pytest.mark.parametrize(
    "sender,subject",
    [
        ("Someone <someone@gmail.com>", "Fwd: Commonwealth Bank Chief Engineer"),  # forwarded by hand
        ("LinkedIn <messages-noreply@linkedin.com>", "You have a new message"),  # not a job alert
        ("Naukri <info@naukri.com>", "Your OTP is 123456"),  # account mail must never be parsed
    ],
)
def test_unrecognised_emails_are_not_parsed(sender, subject):
    assert parse_email(_email(sender, subject, "hello")) is None


ASSISTANT = EMAILS / "ai-assistant-chatgpt-leadership-bengaluru-2026-11-08.eml"


def test_an_assistant_job_list_keeps_its_facts_as_details():
    result = parse_email(ASSISTANT.read_bytes(), OWN)
    sap, _, jpmc, *_ = result.cards
    assert sap.posted_at == datetime(2026, 11, 5, tzinfo=UTC)  # "about 3 days ago" on the 8 Nov alert
    assert jpmc.posted_at == datetime(2026, 11, 4, tzinfo=UTC)
    assert jpmc.details["apply by"] == "18 Nov 2026"
    assert jpmc.details["reference"] == "210801618"
    assert jpmc.details["summary"].startswith("Lead target-state architecture")
    assert jpmc.details["summary"].endswith("large-scale Spark are preferred.")  # wrapped lines joined
    assert jpmc.description is None  # the assistant's summary isn't the employer's description
    assert jpmc.apply_url == jpmc.canonical_url
    assert len({c.source_job_id for c in result.cards}) == 5


def test_an_assistant_job_list_is_read_only_from_the_users_own_address():
    raw = ASSISTANT.read_bytes()
    assert parse_email(raw) is None
    assert parse_email(raw, frozenset({"someone@example.com"})) is None


def test_an_assistant_job_list_in_another_layout():
    body = (
        "Here are today's roles.\n\n"
        "1. Title: Vice President, Platform Engineering\n"
        "   Company: Acme Cloud\n"
        "   Location: Pune (Remote)\n"
        "   Experience: 18-22 years\n"
        "   Apply link: https://boards.example.com/acme/jobs/123?utm_source=chatgpt&gh_jid=123\n\n"
        "2. GROUP PRODUCT MANAGER - GENAI\n"
        "   Employer: Beta Labs\n"
        "   Location: Bengaluru; on-site\n\n"
        "Regards\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    vp, gpm = result.cards
    assert (vp.title, vp.company, vp.location, vp.work_model, vp.experience) == (
        "Vice President, Platform Engineering",
        "Acme Cloud",
        "Pune",
        "Remote",
        "18-22 years",
    )
    assert vp.canonical_url == "https://boards.example.com/acme/jobs/123?gh_jid=123"  # tracking dropped
    assert (gpm.title, gpm.location, gpm.work_model, gpm.canonical_url) == (
        "Group Product Manager - GenAI",
        "Bengaluru",
        "On-site",
        None,
    )


def test_an_assistant_job_list_with_paired_labels():
    # The layout of 2026-11-11: "Location/work arrangement", "Source/date", "Apply/listing" (the titles took in
    # the whole entry), and a second link under "Official role details".
    body = (
        "3) Acme Data — Senior Director, Product Management, Agents\n"
        "Location/work arrangement: Bengaluru or Hyderabad; full-time, remote.\n"
        "Source/date: Acme official careers site; posted 1 day ago.\n"
        "Experience: 10+ years product management, including 5+ years leading AI/ML\n"
        "or advanced analytics products.\n"
        "Summary: Global AI product-management strategy.\n"
        "Apply:\n"
        "https://www.google.com/url?q=https://careers.example.com/jobs?jid%3D175108&source=gmail&sa=E\n"
        "Official role details:\n"
        "https://careers.example.com/details/175108\n\n"
        "4) Beta Labs — Director of Engineering\n"
        "Location/work setup: Bengaluru, Jayanagar; hybrid/on-site.\n"
        "Source/listing age: LinkedIn; listed approximately 13 hours ago.\n"
        "Apply/listing:\n"
        "https://jobs.example.com/beta/7\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    acme, beta = result.cards
    assert (acme.title, acme.company, acme.work_model, acme.experience) == (
        "Senior Director, Product Management, Agents",
        "Acme Data",
        "Remote",
        "10+ years",
    )
    assert acme.apply_url == "https://careers.example.com/jobs?jid=175108"
    assert acme.posted_at is not None and "official_page" not in acme.details
    # Labels never seen before, paired with a known first word, are still labels.
    assert (beta.title, beta.company, beta.location) == (
        "Director of Engineering",
        "Beta Labs",
        "Bengaluru, Jayanagar",
    )
    assert beta.apply_url == "https://jobs.example.com/beta/7" and beta.posted_at is not None


def test_an_assistant_job_list_keeps_every_link_under_official_application_or_an_unknown_label():
    # 2026-11-11 evening: "Official application:" (lowercase mid-line, so not read as a label) left three jobs
    # without a link, and the job page without an Apply button.
    body = (
        "1) Acme Works — Director - Delivery Data & AI\n"
        "Location/work model: Bangalore, India; hybrid.\n"
        "Experience: 20+ years.\n"
        "Scope: Delivery Director within the India Delivery Center.\n"
        "Official application:\n"
        "https://www.google.com/url?q=https://www.example.com/careers/jobs/8376818&source=gmail&sa=E\n\n"
        "2) Beta Systems — Engineering Director\n"
        "Requisition: R0150236.\n"
        "Where to apply:\n"
        "https://careers.example.org/engineering-director/job/R0150236\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    acme, beta = result.cards
    assert acme.apply_url == "https://www.example.com/careers/jobs/8376818"
    assert (acme.title, acme.work_model) == ("Director - Delivery Data & AI", "Hybrid")
    assert beta.apply_url == "https://careers.example.org/engineering-director/job/R0150236"


def test_an_assistant_role_line_is_the_title_when_short_and_the_summary_when_it_describes_the_job():
    # 2026-11-11: "Role: Leads the global … function …" became the job's title.
    body = (
        "1) Employer: Acme Bank\n"
        "Role: Head of Platform Engineering\n"
        "Apply: https://careers.example.com/1\n\n"
        "2) Acme Bank — Head, Regulatory Reporting Technology\n"
        "Role: Leads the global Regulatory Reporting Technology function and its strategy, architecture,\n"
        "lifecycle and risk management. Scope includes reporting platforms.\n"
        "Official application:\n"
        "https://careers.example.com/2\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    short, prose = result.cards
    assert (short.title, short.company) == ("Head of Platform Engineering", "Acme Bank")
    assert (prose.title, prose.company) == ("Head, Regulatory Reporting Technology", "Acme Bank")
    assert prose.details["summary"].startswith("Leads the global Regulatory Reporting Technology function")


def test_an_assistant_heading_keeps_a_wrapped_title_and_leaves_a_sentence_under_it_as_a_note():
    # 2026-11-13: "LinkedIn is now showing the role as newly listed …" under the heading became part of the title.
    body = (
        "1) Acme — Senior Director, Distinguished Engineer – SDLC and Autonomous\n"
        "Development, DevCMO Tech\n"
        "Location: Bengaluru\n"
        "Application: https://careers.example.com/1\n\n"
        "2) Acme — Director Product Management, Enterprise Data Strategy\n"
        "LinkedIn is now showing the role as newly listed about 1 hour before this\n"
        "scan. This is the same requisition, not a second vacancy.\n"
        "Location: Bengaluru / remote\n"
        "Employer application:\n"
        "https://careers.example.com/2\n\n"
        "3) Acme — Vice President,\n"
        "engineering platforms\n"
        "Application: https://careers.example.com/3\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    wrapped, noted, cut = result.cards
    assert (
        wrapped.title
        == "Senior Director, Distinguished Engineer – SDLC and Autonomous Development, DevCMO Tech"
    )
    assert noted.title == "Director Product Management, Enterprise Data Strategy"
    assert noted.details["note"].startswith("LinkedIn is now showing the role as newly listed")
    assert (noted.location, noted.work_model, noted.apply_url) == (
        "Bengaluru",
        "Remote",
        "https://careers.example.com/2",
    )
    assert cut.title.lower() == "vice president, engineering platforms"


def test_an_assistant_work_arrangement_in_doubt_is_left_unknown():
    body = (
        "1) Acme — Director, Engineering\n"
        "Location: Bengaluru\n"
        "Work arrangement: Not reliably confirmed. Public job trackers conflict between remote and on-site.\n"
        "Application: https://careers.example.com/1\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    assert result.cards[0].work_model is None


def test_an_assistant_job_list_with_bold_titles_and_labels_in_one_paragraph():
    # The layout of 2026-11-09 afternoon: a bold "Company — Title" over two lines, then labels running on.
    body = (
        "Broad discovery report.\n\n"
        "   1. *Acme India — Executive Director, Product Management, SBU\n"
        "   Connectivity*\n"
        "   Source/age: LinkedIn public listing says 1 week; another index says 17\n"
        "   days (age discrepancy). Location/work mode: Bengaluru; hybrid reported by a\n"
        "   public index. Experience: 20+ years; 10+ years leading global teams. Scope:\n"
        "   portfolio-level product management.\n"
        "   Apply/view: LinkedIn public listing\n"
        "   <https://www.google.com/url?q=https://boards.example.com/acme/jobs/42&source=gmail&sa=E>.\n"
        "   2. *Beta Labs — Director, AI Engineering*\n"
        "   Source/posted: ZipRecruiter lists 1 November 2026. Location/work mode:\n"
        "   Bengaluru, hybrid (at least 3 office days/week). Experience: 15+ years.\n"
        "   View/apply: Beta Labs application <https://jobs.example.com/beta/7>\n"
        "   .\n\n"
        "Omitted: roles already reported.\n"
    )
    result = parse_email(
        _email("Tester <tester@gmail.com>", "Job alert", body), frozenset({"tester@gmail.com"})
    )
    acme, beta = result.cards
    assert (acme.title, acme.company, acme.location, acme.work_model, acme.experience) == (
        "Executive Director, Product Management, SBU Connectivity",
        "Acme India",
        "Bengaluru",
        "Hybrid",
        "20+ years",
    )
    assert acme.apply_url == "https://boards.example.com/acme/jobs/42"
    assert acme.details["summary"] == "portfolio-level product management."
    assert acme.details["posting"]["conflict"] is True  # 1 week vs 17 days
    assert (beta.title, beta.company, beta.location, beta.work_model) == (
        "Director, AI Engineering",
        "Beta Labs",
        "Bengaluru",
        "Hybrid",
    )
    assert beta.posted_at.date().isoformat() == "2026-11-01"
    assert beta.apply_url == "https://jobs.example.com/beta/7"


def test_own_mail_without_a_job_list_stays_unparsed():
    body = "1) Buy milk\n2) Call the bank: tomorrow\n"
    assert (
        parse_email(_email("Tester <tester@gmail.com>", "To do", body), frozenset({"tester@gmail.com"}))
        is None
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Bengaluru East (Hybrid)", ("Bengaluru East", "Hybrid")),
        ("Bangalore Urban (On-site)", ("Bangalore Urban", "On-site")),
        ("Hybrid - Bengaluru", ("Bengaluru", "Hybrid")),
        ("Pune(Kharadi)", ("Pune(Kharadi)", None)),
    ],
)
def test_split_location(value, expected):
    assert split_location(value) == expected


def test_fingerprint_ignores_case_punctuation_and_company_suffixes():
    a = fingerprint("Visa Consolidated Support Services India Pvt. Ltd.", "Director, Finance", "Bengaluru")
    b = fingerprint("visa consolidated support services india", "DIRECTOR FINANCE", "bengaluru")
    assert a == b
    assert a != fingerprint("Visa Consolidated Support Services India", "Director, Finance", "Pune")
    assert fingerprint(None, "VP-AI Senior Leader", "Mumbai") is None


def test_strip_query():
    assert strip_query("https://www.naukri.com/jd/job-listings-x-1?uid=1&xid=2#top") == (
        "https://www.naukri.com/jd/job-listings-x-1"
    )


def _hand_forward(name: str, by: str = "Tester <tester@gmail.com>") -> bytes:
    """What Gmail's Forward button makes of an alert: a header block, then the quoted original."""
    original = load((EMAILS / name).read_bytes())
    block = f"---------- Forwarded message ---------\nFrom: {original['From']}\nSubject: {original['Subject']}\n\n"
    msg = EmailMessage()
    msg["From"], msg["Subject"] = by, f"Fwd: {original['Subject']}"
    plain = original.get_body(("plain",))
    msg.set_content(block + (plain.get_content() if plain else ""))
    html = original.get_body(("html",)).get_content()
    quoted = block.replace("\n", "<br>")
    msg.add_alternative(f'<div dir="ltr"><div class="gmail_quote">{quoted}{html}</div></div>', subtype="html")
    return msg.as_bytes()


@pytest.mark.parametrize(
    "name",
    [
        "naukri-alert-recommended-jobs-2026-09-21.eml",
        "linkedin-alert-vice-president-bangalore-2026-10-29.eml",
    ],
)
def test_a_hand_forward_from_a_listed_address_is_read_as_the_original(name):
    original = parse_email((EMAILS / name).read_bytes())
    forwarded = parse_email(_hand_forward(name), frozenset({"tester@gmail.com"}))
    assert [c.source_job_id for c in forwarded.cards] == [c.source_job_id for c in original.cards]
    assert forwarded.parser == original.parser


def test_a_hand_forward_is_not_read_unless_the_sender_is_listed():
    assert parse_email(_hand_forward("naukri-alert-recommended-jobs-2026-09-21.eml")) is None
    assert (
        parse_email(_hand_forward("naukri-alert-recommended-jobs-2026-09-21.eml"), frozenset({"x@gmail.com"}))
        is None
    )


def test_a_hand_forward_of_other_mail_stays_unparsed():
    body = "---------- Forwarded message ---------\nFrom: Bank <alerts@bank.example>\n\nYour statement"
    assert (
        parse_email(_email("tester@gmail.com", "Fwd: statement", body), frozenset({"tester@gmail.com"}))
        is None
    )


def _gmail_forward_of_linkedin() -> bytes:
    """Gmail's own rendering of a forwarded LinkedIn alert (shape of a real forward, 2026-11-03; fictional jobs)."""

    def link(job=None):
        if job:
            return f"<https://www.linkedin.com/comm/jobs/view/{job}/?trk=x&otpToken=secret>"
        return "<https://www.linkedin.com/comm/x>"

    lines = [
        "---------- Forwarded message ---------",
        "From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
        "Subject: Vice President, Product Engineering at Acme Data",
        "To: Tester <tester@gmail.com>",
        "",
        "View jobs in Bengaluru",
        "[image: LinkedIn]",
        link(),
        "[image:",
        "My Network]",
        link(),
        "Your job alert for *vice president product development software, on-site or",
        "hybrid*",
        link(),
        "[image: Acme Data]",
        link(4400000001),
        "Vice President, Product Engineering",
        link(4400000001),
        "",
        "Acme Data · Bengaluru (Hybrid)",
        "",
        "Actively recruiting",
        link(4400000001),
        "[image: Brightpay]",
        link(4400000002),
        "Director of Product, Payments Platform",
        link(4400000002),
        "",
        "Brightpay · Bengaluru (On-site)",
        link(4400000002),
        "[image: Nimbus]",
        link(4400000003),
        "ENGINEERING HEAD L1",
        link(4400000003),
        "",
        "Nimbus · Bengaluru",
        "[image: A Person]",
        "",
        "2 connections",
        link(4400000003),
        "See all jobs",
        link(),
        "------------------------------",
        "This email was intended for Tester",
        link(),
    ]
    msg = EmailMessage()
    msg["From"] = "Tester <tester@gmail.com>"
    msg["Subject"] = "Fwd: Vice President, Product Engineering at Acme Data"
    msg.set_content("\r\n".join(lines))
    html = (
        '<div class="gmail_quote"><table><tr><td>'
        '<a href="https://www.linkedin.com/comm/jobs/view/4400000001/">Vice President, Product Engineering</a>'
        "</td></tr></table></div>"
    )
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_a_gmail_forward_of_a_linkedin_alert_keeps_every_job():
    result = parse_email(_gmail_forward_of_linkedin(), frozenset({"tester@gmail.com"}))
    assert result.parser == "linkedin_digest@1" and result.warnings == []
    assert [(c.source_job_id, c.title, c.company, c.location, c.work_model) for c in result.cards] == [
        ("4400000001", "Vice President, Product Engineering", "Acme Data", "Bengaluru", "Hybrid"),
        ("4400000002", "Director of Product, Payments Platform", "Brightpay", "Bengaluru", "On-site"),
        ("4400000003", "ENGINEERING HEAD L1", "Nimbus", "Bengaluru", None),
    ]
    assert result.cards[0].card_lines == ("Actively recruiting",)
    assert result.cards[2].card_lines == ("2 connections",)
    assert result.cards[0].canonical_url == "https://www.linkedin.com/jobs/view/4400000001/"  # no login token
    assert result.alert_name == "vice president product development software, on-site or hybrid"


def _saved_jobs_reminder() -> bytes:
    """LinkedIn's saved-job reminder (layout of 2026-11-04; fictional jobs and people)."""
    link = "View job: https://www.linkedin.com/comm/jobs/view/{}/?trackingId=abc&refId=xyz"
    lines = [
        "Your saved job at Nimbus is still available.",
        "ENGINEERING HEAD L1",
        "Nimbus",
        "Bengaluru, Karnataka, India",
        "2 connections",
        link.format("4400000011"),
        "---------------------------------------------------------",
        "Apply now",
        "https://www.linkedin.com/comm/jobs/view/4400000011/apply",
        "You have connections at Nimbus",
        "Ask them about the job",
        "Asha Rao",
        "Head of Business Operations",
        "Message https://www.linkedin.com/comm/messaging/compose?recipient=1",
        "Your other saved jobs",
        "Director of Product, Tax Platform",
        "Brightpay",
        "Bengaluru, Karnataka, India (Hybrid)",
        "2 school alumni",
        link.format("4400000012"),
        "---------------------------------------------------------",
        "See all saved jobs https://www.linkedin.com/comm/my-items/saved-jobs/",
    ]
    msg = EmailMessage()
    msg["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    msg["Subject"] = "Tester, apply now to ‘ENGINEERING HEAD L1 at Nimbus’"
    msg["X-LinkedIn-Template"] = "email_jobs_saved_job_reminder_01"
    msg.set_content("\n\n".join(lines))  # LinkedIn's plain text has blank lines between a job's lines
    return msg.as_bytes()


def test_a_linkedin_saved_jobs_reminder_lists_each_saved_job():
    result = parse_email(_saved_jobs_reminder())
    assert result.parser == "linkedin_saved_jobs@1" and result.warnings == []
    assert [(c.source_job_id, c.title, c.company, c.location, c.work_model) for c in result.cards] == [
        ("4400000011", "ENGINEERING HEAD L1", "Nimbus", "Bengaluru, Karnataka, India", None),
        (
            "4400000012",
            "Director of Product, Tax Platform",
            "Brightpay",
            "Bengaluru, Karnataka, India",
            "Hybrid",
        ),
    ]
    assert result.cards[0].card_lines == ("2 connections",)
    assert result.cards[0].canonical_url == "https://www.linkedin.com/jobs/view/4400000011/"  # no tracking


def _recruiter_invite_without_brackets() -> bytes:
    """A Naukri recruiter invite in the layout of 2026-11-04: the subject has no [brackets] round the city and
    the employer shows with its rating (fictional employer)."""
    icon = '<img src="https://static.naukimg.com/s/4/123/i/{}.png"> {}<br>'
    html = (
        "<table><tr><td>Tester, you're invited to apply to this job</td></tr>"
        '<tr><td><img src="https://img.naukimg.com/logo_images/194354.gif"> Nimbus Tech'
        ' <img src="https://static.naukimg.com/s/4/123/i/star.png"> 3.4 (5100 Reviews)</td></tr>'
        "<tr><td>Exciting job at Nimbus---- SAP GRC / BR&amp;C Technology Architect- Bangalore</td></tr><tr><td>"
        + icon.format("i3_1", "Bengaluru")
        + icon.format("i4_1", "19 - 24 years")
        + icon.format("i4", "35.0 lacs - 65.0 lacs")
        + icon.format("i6", "In office")
        + icon.format("i7", "SAP GRC, SAP Security, SOX")
        + '</td></tr><tr><td><a href="https://www.naukri.com/AL/ResdexRMJMail/alid/x/redirectParam/'
        'applyBroadcastMail?xz=1&mid=041126000001&uId=secret">Apply now</a></td></tr>'
        "<tr><td><strong>Job description</strong></td></tr><tr><td><p>Lead SAP GRC architecture.</p></td></tr>"
        "</table>"
    )
    msg = EmailMessage()
    msg["From"] = "Nimbus Tech <recruiter.x=@naukri.com>"
    msg["Subject"] = (
        "✉️ Job | Exciting job at Nimbus---- SAP GRC / BR&C Technology Architect- Bangalore in Bengaluru"
    )
    msg.set_content("Job invite from recruiter.")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_a_recruiter_invite_without_brackets_in_the_subject_is_read():
    result = parse_email(_recruiter_invite_without_brackets())
    assert result.warnings == []
    card = result.cards[0]
    assert (card.source_job_id, card.title, card.company, card.location) == (
        "041126000001",
        "SAP GRC / BR&C Technology Architect",  # without the recruiter's padding or the repeated city
        "Nimbus Tech",
        "Bengaluru",
    )
    assert card.skills == ("SAP GRC", "SAP Security", "SOX")
    assert card.experience == "19-24 years" and card.work_model == "On-site"
    assert card.description == "Lead SAP GRC architecture."


def test_an_assistant_job_list_records_doubts_about_the_posting():
    raw = (EMAILS / "ai-assistant-chatgpt-leadership-bengaluru-2026-11-09.eml").read_bytes()
    cards = {(c.company, c.title): c for c in parse_email(raw, OWN).cards}
    walmart = cards["Walmart Global Tech", "Senior Director, Technical Program Management"]
    # "posted yesterday" on one site and "23 days ago" on another: the older date, and a conflict.
    assert walmart.posted_at == datetime(2026, 10, 17, tzinfo=UTC)
    assert walmart.details["posting"] == {
        "dates": ["2026-10-17", "2026-11-08"],
        "conflict": True,
        "closes_on": None,
    }
    assert walmart.details["reference"] == "R-2611361"
    ge = cards["GE HealthCare", "Senior Director, Software Engineering"]  # "30+ days ago" vs "5 Nov"
    assert ge.details["posting"]["conflict"] is True
    tredence = cards["Tredence", "Director, Software Engineering (GenAI Products & Accelerators)"]
    assert tredence.details["posting"] == {
        "dates": ["2026-10-19"],
        "conflict": False,
        "closes_on": "2026-11-09",
    }
    exxat = cards["Exxat", "Director, Engineering"]  # under "… DIRECT EMPLOYER ROUTE NOT VERIFIED"
    assert exxat.details["employer page"].startswith("Not found by the assistant")
    assert "posting" not in exxat.details  # one date, three weeks old: age is judged when the job is read
    capital_one = cards["Capital One", "Senior Director, Software Engineering"]
    assert "employer page" not in capital_one.details and "posting" not in capital_one.details


def test_naukri_applied_says_which_job_and_when():
    """Naukri's "You applied for 1 job on 12 Nov" (user feedback 2026-11-15): the applied job and its day; the
    similar jobs are recommendations. The day stays out of the cards (they go to the shared catalog)."""
    from datetime import date

    result = parse_email((EMAILS / "naukri-applied-similar-jobs-2026-11-12.eml").read_bytes())
    assert result.applied == {0: date(2026, 11, 12)}
    assert all(c.details == {} for c in result.cards)
    assert all("dl.naukri.com" not in (c.canonical_url or "") for c in result.cards)


def test_other_mail_from_info_at_naukri_is_not_read():
    msg = EmailMessage()
    msg["From"] = "Naukri <info@naukri.com>"
    msg["Subject"] = "Ajith, Recruiters are noticing your profile"
    msg.set_content("<p>Recruiters viewed your profile</p>", subtype="html")
    assert parse_email(msg.as_bytes()) is None
