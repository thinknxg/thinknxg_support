"""1.11: text from uploaded knowledge documents (PDF, Word, Excel, CSV, text, Markdown, HTML).

Only standard libraries and packages Frappe already ships (pypdf, openpyxl, BeautifulSoup) are used. Archives are
size-checked before they are opened (Word and Excel files are zip archives), XML with a DOCTYPE is refused, and the
text kept is capped. Scanned PDFs have no text layer; they fail with a clear message (no OCR yet).
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.etree import ElementTree as ET

import frappe
from frappe import _
from frappe.utils import now_datetime

DOC = "Support Knowledge Document"
TYPES = {"pdf", "docx", "xlsx", "csv", "txt", "md", "html", "htm"}
MAX_BYTES = 25 * 1024 * 1024
MAX_UNZIPPED = 150 * 1024 * 1024
MAX_CHARS = 400_000
MAX_ROWS = 20_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ExtractError(Exception):
    """The file cannot be turned into text; the message is shown to the administrator."""


def ext_of(file_url: str | None) -> str:
    name = (file_url or "").split("?", 1)[0].rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


def extract(content: bytes, ext: str) -> tuple[str, int]:
    """(text, pages or sheets). Raises ExtractError."""
    if len(content) > MAX_BYTES:
        raise ExtractError(_("The file is larger than 25 MB."))
    fn = {"pdf": _pdf, "docx": _docx, "xlsx": _xlsx, "csv": _csv, "html": _html, "htm": _html,
          "txt": _plain, "md": _plain}.get(ext)
    if not fn:
        raise ExtractError(_("Unsupported file type: .{0}").format(ext))
    text, pages = fn(content)
    text = re.sub(r"[ \t ]+", " ", text or "")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ExtractError(_("No text was found in the file."))
    return text[:MAX_CHARS], pages


def _pdf(content):
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractError(_("The PDF is password protected. Upload a copy without a password."))
        pages = [(p.extract_text() or "") for p in reader.pages[:3000]]
    except ExtractError:
        raise
    except Exception:
        raise ExtractError(_("This is not a readable PDF."))
    if not "".join(pages).strip():
        raise ExtractError(_("This PDF has no text layer (it looks scanned). Text recognition (OCR) is not supported "
                             "yet: upload a PDF with selectable text, or a Word file."))
    return "\n\n".join(pages), len(reader.pages)


def _zip(content) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ExtractError(_("The file is damaged or not in the format its name says."))
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise ExtractError(_("The file expands to more than 150 MB, so it was not read."))
    return zf


def _xml(data: bytes):
    if b"<!DOCTYPE" in data[:4096].upper():
        raise ExtractError(_("The file contains a document type declaration, which is not accepted."))
    return ET.fromstring(data)


def _para(p) -> str:
    out = []
    for el in p.iter():
        if el.tag == W + "t":
            out.append(el.text or "")
        elif el.tag == W + "tab":
            out.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def _docx(content):
    zf = _zip(content)
    try:
        root = _xml(zf.read("word/document.xml"))
    except KeyError:
        raise ExtractError(_("This is not a Word (.docx) document. Old .doc files: save them as .docx first."))
    body = root.find(W + "body")
    lines = []
    for el in (body if body is not None else []):
        if el.tag == W + "p":
            lines.append(_para(el))
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells = [" ".join(_para(p) for p in tc.iter(W + "p")).strip() for tc in tr.findall(W + "tc")]
                lines.append(" | ".join(c for c in cells if c))
    return "\n".join(lines), 0


def _xlsx(content):
    _zip(content)  # size check before openpyxl expands it
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise ExtractError(_("This is not a readable Excel (.xlsx) file."))
    lines, rows = [], 0
    for ws in wb.worksheets:
        lines.append(f"\n{ws.title}")
        for row in ws.iter_rows(values_only=True):
            vals = [str(v).strip() for v in row if v not in (None, "")]
            if vals:
                lines.append(" | ".join(vals))
                rows += 1
            if rows >= MAX_ROWS:
                break
    sheets = len(wb.worksheets)
    wb.close()
    return "\n".join(lines), sheets


def _csv(content):
    reader = csv.reader(io.StringIO(decode(content)))
    lines = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            break
        vals = [v.strip() for v in row if v.strip()]
        if vals:
            lines.append(" | ".join(vals))
    return "\n".join(lines), 0


def html_text(html) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for bad in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        bad.decompose()
    return soup.get_text("\n")


def _html(content):
    return html_text(content), 0


def _plain(content):
    return decode(content), 0


# ------------------------------------------------------------------ files
def _file_name(file_url: str) -> str | None:
    rows = frappe.get_all("File", filters={"file_url": file_url}, order_by="creation desc", limit=1, pluck="name")
    return rows[0] if rows else None


def make_private(doc):
    """Knowledge documents are staff material: a file uploaded as public is moved to private files."""
    if not doc.file or doc.file.startswith("/private/"):
        return
    name = _file_name(doc.file)
    if not name:
        return
    f = frappe.get_doc("File", name)
    if not f.is_private:
        f.is_private = 1
        f.save(ignore_permissions=True)
        doc.db_set("file", f.file_url, update_modified=False)


def process(name: str):
    """Background job: read the file, keep its text, and (re)index it."""
    from thinknxg_support.integrations.ai import retrieval

    doc = frappe.get_doc(DOC, name)
    doc.db_set({"status": "Processing", "error": None}, update_modified=False)
    frappe.db.commit()
    values = {"processed_on": now_datetime()}
    try:
        fname = _file_name(doc.file)
        if not fname:
            raise ExtractError(_("The attached file is missing. Attach it again."))
        from thinknxg_support.utils import file_bytes

        content = file_bytes(frappe.get_doc("File", fname))
        text, pages = extract(content, ext_of(doc.file))
        values.update({"status": "Ready", "extracted_text": text, "pages": pages, "characters": len(text),
                       "error": None})
    except ExtractError as e:
        values.update({"status": "Failed", "error": str(e), "extracted_text": None, "characters": 0})
    except Exception:
        frappe.log_error(title="thinkNXG Support: knowledge document could not be read")
        values.update({"status": "Failed", "error": _("The file could not be read."), "extracted_text": None,
                       "characters": 0})
    doc.db_set(values, update_modified=False)
    retrieval.index_source(DOC, name)  # Ready: indexed; Failed: its passages are removed
    frappe.db.commit()
