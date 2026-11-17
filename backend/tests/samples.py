"""Fictional resumes and cover letters, and builders for the file formats the library reads.

Nothing here is a real person's document: tests never use real resumes (those stay in TestFiles/raw/).
"""

import io
import zipfile
from xml.sax.saxutils import escape

RESUME = """PRIYA NAIR
VP, ENGINEERING | CLOUD AND AI PLATFORMS
+91 90000 00001 • priya.nair@example.com • linkedin.com/in/priya-nair-example • Bengaluru, India
PROFESSIONAL SUMMARY
Engineering leader with 21+ years building cloud-native SaaS platforms for banking and retail clients.
Led GenAI and LLM product features, AWS and Azure migrations, and teams of 80 engineers.
CORE COMPETENCIES
Product Development | Microservices | Kubernetes
Generative AI (LLMs, RAG) | AWS / Azure | Agile Delivery
PROFESSIONAL EXPERIENCE
VP, Engineering | Example Fintech Pvt Ltd — Bengaluru\tJan 2021 – Present
Built an AI platform on AWS with LLM-based document processing for lending.
Director, Engineering | Sample Retail Tech — Bengaluru\tMar 2015 – Dec 2020
Ran order fulfillment and click & collect platforms on Azure microservices.
Senior Software Engineer | Demo Systems\tJun 2004 – Feb 2015
Built Java and .NET services for a wealth management client.
TECHNICAL SKILLS
Languages: Java, Python, Go, TypeScript
Cloud & DevOps: AWS, Azure, Docker, Kubernetes, Terraform
AI: LLMs, RAG, Machine Learning
EDUCATION
B.Tech, Computer Science\t2000 – 2004
Example Institute of Technology, Kochi
"""

# A variation that leans on delivery and finance, with no AI or cloud.
RESUME_DELIVERY = """PRIYA NAIR
PROGRAM DIRECTOR
priya.nair@example.com • Bengaluru, India
SUMMARY
Delivery and programme leader with 21 years running large transformation programmes for banks.
EXPERIENCE
Program Director | Example Bank\tJan 2016 – Present
Ran regulatory reporting and finance transformation programmes with budgets of 40 crore.
Project Manager | Demo Consulting\tJun 2004 – Dec 2015
Managed delivery of core banking upgrades.
SKILLS
Programme management, Budgeting, Stakeholder management, PMP, Vendor management
"""

COVER_LETTER = (
    "Dear Hiring Manager,\n\nI lead engineering teams that build cloud and AI platforms for banks and "
    "retailers. Over 21 years I have grown teams to 80 engineers and shipped LLM features to production. "
    "I would welcome the chance to talk about the role.\n\nRegards,\nPriya"
)
COVER_LETTER_DELIVERY = (
    "Dear Hiring Manager,\n\nI run large delivery programmes for banks: regulatory reporting, finance "
    "transformation and core banking upgrades, on time and on budget, with teams across three countries. "
    "I would be glad to discuss the programme role.\n\nRegards,\nPriya"
)


def docx(text: str, header_table: bool = False) -> bytes:
    """A minimal Word document: one paragraph per line, tabs kept. Optionally the first three lines sit in
    a one-cell table, the way some templates lay out the name and contact details."""
    lines = text.splitlines()

    def par(line: str) -> str:
        runs = "<w:r><w:tab/></w:r>".join(
            f'<w:r><w:t xml:space="preserve">{escape(part)}</w:t></w:r>' for part in line.split("\t")
        )
        return f"<w:p>{runs}</w:p>"

    body = ""
    if header_table:
        cell = "".join(par(ln) for ln in lines[:3])
        body += f"<w:tbl><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"
        lines = lines[3:]
    body += "".join(par(ln) for ln in lines)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def odt(text: str) -> bytes:
    pars = "".join(f"<text:p>{escape(ln)}</text:p>" for ln in text.splitlines())
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
        f"<office:body><office:text>{pars}</office:text></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", xml)
    return buf.getvalue()


def rtf(text: str) -> bytes:
    body = "\\par\n".join(
        ln.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") for ln in text.splitlines()
    )
    return ("{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Arial;}}\\f0\\fs22\n" + body + "\\par\n}").encode(
        "latin-1", "replace"
    )


def pdf(text: str) -> bytes:
    """A one-page PDF with the text as plain lines (Helvetica), built by hand with a correct xref table."""
    lines = [ln.encode("latin-1", "replace").decode("latin-1") for ln in text.splitlines()]
    ops = ["BT", "/F1 9 Tf", "11 TL", "40 800 Td"]
    for ln in lines:
        safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\t", "    ")
        ops.append(f"({safe}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()
