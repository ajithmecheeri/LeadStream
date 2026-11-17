"""Plain text from an uploaded resume or cover letter: PDF, DOCX, ODT, RTF, TXT or Markdown.

Paragraphs become lines; table cells and tabs become " | " and tabs, so "Title | Company<TAB>Apr 2022 –
Present" survives for the resume reader. Nothing here runs macros or follows links.
"""

import io
import re
import zipfile
from xml.etree import ElementTree

KINDS = ("pdf", "docx", "odt", "rtf", "txt", "md")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class UnreadableDocument(ValueError):
    pass


def kind_of(filename: str, data: bytes) -> str:
    """The file's kind from its contents (falling back to the name); raises if it's not one we read."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile as e:
            raise UnreadableDocument("The file is damaged") from e
        if "word/document.xml" in names:
            return "docx"
        if "content.xml" in names:
            return "odt"
        raise UnreadableDocument("Only PDF, Word (.docx), OpenDocument (.odt), RTF and text files are read")
    if data.lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if ext == "doc":
        raise UnreadableDocument("Old Word (.doc) files aren't read: save it as .docx or PDF and upload that")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise UnreadableDocument(
            "Only PDF, Word (.docx), OpenDocument (.odt), RTF and text files are read"
        ) from e
    return "md" if ext == "md" else "txt"


def text_of(kind: str, data: bytes) -> str:
    try:
        raw = {"pdf": _pdf, "docx": _docx, "odt": _odt, "rtf": _rtf}.get(kind, _plain)(data)
    except UnreadableDocument:
        raise
    except Exception as e:
        raise UnreadableDocument("The file couldn't be read. Try saving it again as PDF or .docx") from e
    text = _tidy(raw)
    if len(text) < 100:
        raise UnreadableDocument(
            "Hardly any text was found. If it's a scanned PDF, upload the Word version instead"
        )
    return text


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [re.sub(r"[   ]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def _plain(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _docx(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    root = ElementTree.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    lines: list[str] = []
    for block in body if body is not None else []:
        if block.tag == f"{_W}p":
            lines.append(_docx_par(block))
        elif block.tag == f"{_W}tbl":
            # A row of one-line cells stays one line ("Title | Apr 2022 – Present", a grid of skills); a
            # cell with several paragraphs (a header block: name, title, contacts) keeps its lines.
            for row in block.iter(f"{_W}tr"):
                cells = [[_docx_par(p).strip() for p in cell.iter(f"{_W}p")] for cell in row.iter(f"{_W}tc")]
                cells = [[t for t in c if t] for c in cells]
                if all(len(c) <= 1 for c in cells):
                    lines.append(" | ".join(c[0] for c in cells if c))
                else:
                    lines += [t for c in cells for t in c]
    return "\n".join(lines)


def _docx_par(p) -> str:
    parts: list[str] = []
    for el in p.iter():
        if el.tag == f"{_W}t" and el.text:
            parts.append(el.text)
        elif el.tag == f"{_W}tab":
            parts.append("\t")
        elif el.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)


def _odt(data: bytes) -> str:
    root = ElementTree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("content.xml"))
    lines: list[str] = []
    for el in root.iter():
        if el.tag in (f"{_TEXT}p", f"{_TEXT}h"):
            lines.append(_odt_text(el))
    return "\n".join(lines)


def _odt_text(el) -> str:
    parts = [el.text or ""]
    for child in el:
        if child.tag == f"{_TEXT}tab":
            parts.append("\t")
        elif child.tag == f"{_TEXT}line-break":
            parts.append("\n")
        elif child.tag == f"{_TEXT}s":
            parts.append(" ")
        else:
            parts.append(_odt_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _rtf(data: bytes) -> str:
    from striprtf.striprtf import rtf_to_text

    return rtf_to_text(data.decode("latin-1"))
