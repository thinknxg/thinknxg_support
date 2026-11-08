"""1.11: uploaded documents, website crawling and multilingual answers (no network: HTTP and DNS are faked)."""
import io
import re
import zipfile
from unittest.mock import patch

import frappe

from thinknxg_support.integrations import live_chat
from thinknxg_support.integrations.ai import crawler, documents, engine, language, providers, retrieval
from thinknxg_support.tests.utils import BaseTestCase, as_user

DOC = "Support Knowledge Document"
SITE = "Support Knowledge Website"
PAGE = "Support Knowledge Web Page"
CHUNK = "Support Knowledge Chunk"
ENQUEUE_ARGS = ("queue", "enqueue_after_commit", "job_id", "deduplicate", "timeout", "now", "at_front", "job_name",
                "is_async")


def run_now(fn, **kw):
    fn = frappe.get_attr(fn) if isinstance(fn, str) else fn
    return fn(**{k: v for k, v in kw.items() if k not in ENQUEUE_ARGS})


def pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def docx_with(paragraphs, table=None) -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>"
                       for r in table)
        body += f"<w:tbl>{rows}</w:tbl>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


class AIBase(BaseTestCase):
    def setUp(self):
        as_user("Administrator")
        frappe.db.set_single_value("Support AI Settings", {
            "index_documents": 1, "index_websites": 1, "index_snippets": 1, "use_embeddings": 0, "embedding_model": None,
            "min_relevance": 0.1, "top_k": 4, "knowledge_language": "en", "translate_questions": 1,
            "localize_messages": 1, "answer_language": "Customer's language", "model": "fake", "daily_token_budget": 0,
            "analyze_messages": 0, "summary_on_handoff": 0})
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        retrieval.bump_version()
        frappe.cache.delete_keys("thinknxg_support:l10n:")
        self.enq = patch.object(frappe, "enqueue", side_effect=run_now)
        self.enq.start()

    def tearDown(self):
        self.enq.stop()
        as_user("Administrator")


class TestDocuments(AIBase):
    def test_text_from_every_supported_format(self):
        self.assertIn("Refunds take 5 days", documents.extract(pdf_with_text("Refunds take 5 days"), "pdf")[0])
        text = documents.extract(docx_with(["Warranty", "Keep the receipt."], [["Gold", "30 days"]]), "docx")[0]
        self.assertIn("Keep the receipt.", text)
        self.assertIn("Gold | 30 days", text)
        from openpyxl import Workbook

        wb = Workbook()
        wb.active.title = "Prices"
        wb.active.append(["Plan", "Price"])
        wb.active.append(["Gold", 12.5])
        buf = io.BytesIO()
        wb.save(buf)
        text, sheets = documents.extract(buf.getvalue(), "xlsx")
        self.assertIn("Gold | 12.5", text)
        self.assertEqual(sheets, 1)
        self.assertIn("a | b", documents.extract("a,b\n".encode(), "csv")[0])
        self.assertEqual(documents.extract("<p>Hi <script>x()</script>there</p>".encode(), "html")[0].split(), ["Hi", "there"])
        self.assertEqual(documents.extract("مرحبا بك".encode(), "txt")[0], "مرحبا بك")

    def test_unreadable_files_say_why(self):
        from pypdf import PdfWriter

        w = PdfWriter()
        w.add_blank_page(612, 792)
        buf = io.BytesIO()
        w.write(buf)
        with self.assertRaisesRegex(documents.ExtractError, "scanned"):
            documents.extract(buf.getvalue(), "pdf")
        with self.assertRaises(documents.ExtractError):
            documents.extract(b"not a zip", "docx")
        with self.assertRaises(documents.ExtractError):
            documents.extract(b"x", "exe")
        evil = io.BytesIO()
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
        with self.assertRaises(documents.ExtractError):
            documents.extract(evil.getvalue(), "docx")

    def _upload(self, content: bytes, fname: str, **kw):
        f = frappe.get_doc({"doctype": "File", "file_name": fname, "content": content, "is_private": 0}).insert(
            ignore_permissions=True)
        return frappe.get_doc({"doctype": DOC, "title": kw.pop("title", "Warranty handbook"), "file": f.file_url,
                               **kw}).insert()

    def test_upload_is_private_indexed_and_staff_only_by_default(self):
        doc = self._upload(pdf_with_text("Warranty claims need the original receipt and the serial number"),
                           "warranty-handbook.pdf")
        doc.reload()
        self.assertEqual(doc.status, "Ready", doc.error)
        self.assertEqual(doc.audience, "Staff")
        self.assertTrue(doc.file.startswith("/private/files/"))
        self.assertTrue(frappe.db.get_value("File", {"file_url": doc.file}, "is_private"))
        self.assertTrue(frappe.db.count(CHUNK, {"source_doctype": DOC, "source_name": doc.name, "audience": "Staff"}))
        names = lambda aud: [p["name"] for p in retrieval.search("warranty claim receipt serial", aud)]  # noqa: E731
        self.assertNotIn(doc.name, names("Everyone"))
        self.assertNotIn(doc.name, names("Customers"))
        self.assertIn(doc.name, names("Staff"))
        doc.audience = "Everyone"
        doc.save()
        self.assertIn(doc.name, names("Everyone"))
        doc.delete()
        self.assertFalse(frappe.db.count(CHUNK, {"source_doctype": DOC, "source_name": doc.name}))

    def test_failed_file_is_reported_and_not_indexed(self):
        doc = self._upload(b"<script>only();</script>", "empty.html", title="Empty")
        doc.reload()
        self.assertEqual(doc.status, "Failed")
        self.assertTrue(doc.error)
        self.assertFalse(frappe.db.count(CHUNK, {"source_doctype": DOC, "source_name": doc.name}))
        doc.delete()

    def test_only_supported_types_and_staff_permissions(self):
        self.assertRaises(frappe.ValidationError, frappe.get_doc(
            {"doctype": DOC, "title": "Slides", "file": "/private/files/deck.pptx"}).insert)
        self.assertFalse(frappe.has_permission(DOC, "create", user="Guest"))


SITE_PAGES = {}


def page(title, body, extra_head="", links=()):
    a = "".join(f'<a href="{h}">{h}</a>' for h in links)
    return (200, {"content-type": "text/html; charset=utf-8"},
            f"<html lang='en'><head><title>{title}</title>{extra_head}</head><body><nav>Menu Home Login</nav>"
            f"<main><h1>{title}</h1><p>{body}</p>{a}</main><footer>Copyright</footer></body></html>".encode())


def fake_resolve(host):
    return [host] if re.fullmatch(r"[\d.]+", host) else ["93.184.216.34"]


class TestCrawler(AIBase):
    def setUp(self):
        super().setUp()
        self.requested = []
        SITE_PAGES.clear()
        SITE_PAGES.update({
            "https://help.example.com/robots.txt": (200, {"content-type": "text/plain"},
                                                    b"User-agent: *\nDisallow: /private/\n"
                                                    b"Sitemap: https://help.example.com/sitemap.xml\n"),
            "https://help.example.com/sitemap.xml": (200, {"content-type": "application/xml"},
                                                     b"<urlset><url><loc>https://help.example.com/help/faq</loc></url></urlset>"),
            "https://help.example.com/help": page("Help centre", "Welcome to the help centre of Example Trading LLC.", links=[
                "/help/returns", "/help/returns#top", "/private/secret", "https://other.example.org/x", "/help/login",
                "/logo.png", "/help/manual.pdf", "/help/hidden", "/help/moved", "/help/returns?utm_source=mail"]),
            "https://help.example.com/help/returns": page("Returns", "Returns are accepted within 30 days with the receipt."),
            "https://help.example.com/help/faq": page("Opening hours", "We are open Sunday to Thursday, 8am to 5pm."),
            "https://help.example.com/help/hidden": page("Hidden", "This page asks not to be indexed at all, ever.",
                                                         extra_head='<meta name="robots" content="noindex">'),
            "https://help.example.com/help/moved": (302, {"location": "http://127.0.0.1/admin"}, b""),
            "https://help.example.com/help/manual.pdf": (200, {"content-type": "application/pdf"},
                                                         pdf_with_text("Manual: hold the reset button for ten seconds")),
        })
        self.patches = [patch.object(crawler, "_resolve", side_effect=fake_resolve),
                        patch.object(crawler, "_raw_get", side_effect=self._get),
                        patch("thinknxg_support.integrations.ai.crawler.time.sleep")]
        for p in self.patches:
            p.start()
        if frappe.db.exists(SITE, "Example Help"):
            frappe.delete_doc(SITE, "Example Help", force=True)
        self.site = frappe.get_doc({"doctype": SITE, "site_name": "Example Help", "start_url": "https://help.example.com/help",
                                    "exclude_patterns": "*/login*", "max_depth": 2}).insert()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        frappe.delete_doc(SITE, "Example Help", force=True)
        super().tearDown()

    def _get(self, session, url, limit):
        self.requested.append(url)
        return SITE_PAGES.get(url, (404, {"content-type": "text/html"}, b"not found"))

    def _pages(self):
        return {p.url: p for p in frappe.get_all(PAGE, filters={"website": "Example Help"}, fields=["*"])}

    def test_unsafe_addresses_are_refused(self):
        for bad in ("http://localhost/", "http://10.0.0.5/", "http://169.254.169.254/latest", "ftp://example.com/",
                    "http://user:pw@example.com/", "http://intranet.local/"):
            with self.assertRaises(crawler.UnsafeURL, msg=bad):
                crawler.check_url(bad)
        crawler.check_url("https://help.example.com/help")
        self.assertRaises(frappe.ValidationError, frappe.get_doc(
            {"doctype": SITE, "site_name": "Bad", "start_url": "http://192.168.1.10/"}).insert)

    def test_crawl_reads_the_site_within_its_rules(self):
        result = crawler.crawl("Example Help")
        pages = self._pages()
        self.assertEqual(set(pages), {"https://help.example.com/help", "https://help.example.com/help/returns",
                                      "https://help.example.com/help/faq", "https://help.example.com/help/manual.pdf"},
                         result)
        self.assertNotIn("Menu Home Login", pages["https://help.example.com/help/returns"].text)  # page chrome removed
        self.assertIn("ten seconds", pages["https://help.example.com/help/manual.pdf"].text)
        for never in ("https://help.example.com/private/secret", "https://other.example.org/x",
                      "https://help.example.com/help/login", "https://help.example.com/logo.png", "http://127.0.0.1/admin"):
            self.assertNotIn(never, self.requested)
        self.assertEqual(self.requested.count("https://help.example.com/help/returns"), 1)  # fragments, utm: one page
        hits = retrieval.search("returns accepted 30 days receipt", "Everyone")
        self.assertIn("https://help.example.com/help/returns", [h["route"] for h in hits])
        self.assertEqual(frappe.db.get_value(SITE, "Example Help", "page_count"), 4)

    def test_recrawl_updates_changed_removes_gone_and_keeps_exclusions(self):
        crawler.crawl("Example Help")
        pages = self._pages()
        manual = frappe.get_doc(PAGE, pages["https://help.example.com/help/manual.pdf"].name)
        manual.status = "Excluded"
        manual.save()
        self.assertFalse(frappe.db.count(CHUNK, {"source_doctype": PAGE, "source_name": manual.name}))
        SITE_PAGES["https://help.example.com/help/returns"] = page("Returns", "Returns are now accepted within 60 days.")
        SITE_PAGES.pop("https://help.example.com/help/faq")
        SITE_PAGES["https://help.example.com/sitemap.xml"] = (200, {}, b"<urlset></urlset>")
        result = crawler.crawl("Example Help")
        self.assertIn("1 changed", result)
        self.assertIn("1 removed", result)
        pages = self._pages()
        self.assertIn("60 days", pages["https://help.example.com/help/returns"].text)
        self.assertEqual(pages["https://help.example.com/help/faq"].status, "Gone")
        self.assertEqual(pages["https://help.example.com/help/manual.pdf"].status, "Excluded")
        self.assertFalse(frappe.db.count(CHUNK, {"source_doctype": PAGE, "source_name": manual.name}))
        faq = pages["https://help.example.com/help/faq"].name
        self.assertNotIn(faq, [h["name"] for h in retrieval.search("opening hours Sunday Thursday", "Everyone")])

    def test_site_down_removes_nothing(self):
        crawler.crawl("Example Help")
        SITE_PAGES.clear()
        result = crawler.crawl("Example Help")
        self.assertIn("nothing was removed", result)
        self.assertEqual({p.status for p in self._pages().values()}, {"Active"})

    def test_robots_can_block_the_whole_site(self):
        SITE_PAGES["https://help.example.com/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /\n")
        crawler.crawl("Example Help")
        self.assertEqual(self._pages(), {})
        self.assertEqual([u for u in self.requested if "/help" in u], [])


class FakeAI:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, messages, on_delta=None, max_tokens=None, temperature=None):
        self.calls.append(messages[-1]["content"])
        text = self.replies.pop(0) if self.replies else ""
        return {"text": text, "provider": "Fake", "model": "fake", "prompt_tokens": 5, "completion_tokens": 5}


class TestLanguages(AIBase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Support Knowledge Snippet", {"question": "How do I reset my password?"}):
            frappe.get_doc({"doctype": "Support Knowledge Snippet", "question": "How do I reset my password?",
                            "audience": "Everyone", "answer": "Use Forgot password on the sign-in page."}).insert()

    def test_detects_languages_and_stays_quiet_when_unsure(self):
        cases = {"كيف أعيد تعيين كلمة المرور؟": "ar", "How do I reset my password?": "en",
                 "Bonjour, comment suivre ma commande ?": "fr", "मेरा ऑर्डर कहाँ है": "hi", "میرا آرڈر کہاں ہے؟": "ur",
                 "¿Dónde está mi pedido? Necesito ayuda": "es", "Где мой заказ?": "ru", "ok": None, "12345": None}
        for text, code in cases.items():
            self.assertEqual(language.detect(text), code, text)

    def test_arabic_question_finds_english_knowledge(self):
        q = "كيف أعيد تعيين كلمة المرور؟"
        fake = FakeAI("How do I reset my password?")
        with patch.object(providers, "complete", side_effect=fake):
            found = language.search(q, "Everyone")
            again = language.search(q, "Everyone")
        self.assertEqual(found["language"], "ar")
        self.assertEqual(found["translated"], "How do I reset my password?")
        self.assertIn("How do I reset my password?", [p["title"] for p in found["passages"]])
        self.assertEqual([p["id"] for p in found["passages"]][:1], ["S1"])
        self.assertEqual(len(fake.calls), 1, "the translation is cached")
        self.assertEqual(again["translated"], found["translated"])

    def test_no_translation_when_not_needed(self):
        fake = FakeAI()
        with patch.object(providers, "complete", side_effect=fake):
            language.search("How do I reset my password?", "Everyone")  # already the knowledge language
            frappe.db.set_single_value("Support AI Settings", "translate_questions", 0)
            frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
            language.search("كيف أعيد تعيين كلمة المرور؟", "Everyone")
        self.assertEqual(fake.calls, [])

    def test_assistant_is_told_to_answer_in_the_customers_language(self):
        c = engine.cfg()
        self.assertIn("reply in Arabic", engine._system(c, "ar"))
        self.assertIn("language the customer wrote in", engine._system(c))
        frappe.db.set_single_value("Support AI Settings", "answer_language", "Knowledge language")
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        self.assertIn("Reply in English.", engine._system(engine.cfg(), "ar"))

    def _chat(self, text):
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "guest_chat_rate_limit": 1000})
        frappe.cache.delete_keys("thinknxg_support:rl:")
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name="Salim", email="salim@example.com")
        as_user("Administrator")
        return frappe.get_doc("Support Conversation Link", r["conversation"])

    def test_fixed_messages_follow_the_customer(self):
        conv = self._chat("مرحبا، أحتاج مساعدة في طلبي من فضلكم")
        fake = FakeAI("تم تحويل محادثتك إلى فريقنا.")
        with patch.object(providers, "complete", side_effect=fake):
            first = language.localize(conv, "I've passed this to our team.")
            second = language.localize(conv, "I've passed this to our team.")
        self.assertEqual(first, "تم تحويل محادثتك إلى فريقنا.")
        self.assertEqual(second, first)
        self.assertEqual(len(fake.calls), 1)
        english = self._chat("Hello, I need help with my order please")
        with patch.object(providers, "complete", side_effect=FakeAI()) as none:
            self.assertEqual(language.localize(english, "I've passed this to our team."), "I've passed this to our team.")
        self.assertEqual(none.call_count, 0)
