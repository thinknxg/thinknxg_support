"""1.11: uploaded documents, website crawling and multilingual answers (no network: HTTP and DNS are faked)."""
import io
import re
import zipfile
from unittest.mock import patch
from urllib.parse import urlparse

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
            "analyze_messages": 0, "summary_on_handoff": 0, "strict_no_result": 0, "priority_articles": "Normal",
            "priority_snippets": "Normal"})
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

    # ---------------------------------------------------------------- 1.16: multi-source knowledge base
    def test_a_documentation_address_keeps_the_crawl_under_it(self):
        SITE_PAGES["https://help.example.com/pricing"] = page("Pricing", "Our plans start at ten rials per month for teams.")
        SITE_PAGES["https://help.example.com/help"] = page("Help centre", "Welcome to the help centre of Example Trading LLC.",
                                                           links=["/help/returns", "/pricing", "/helpless"])
        SITE_PAGES["https://help.example.com/sitemap.xml"] = (200, {}, b"<urlset><url><loc>https://help.example.com/pricing</loc></url></urlset>")
        self.assertEqual(crawler.start_scope("https://thinknxg.com/thinknxgerp"), "/thinknxgerp")
        self.assertEqual(crawler.start_scope("https://thinknxg.com/thinknxgerp/index.html"), "/thinknxgerp")
        self.assertIsNone(crawler.start_scope("https://thinknxg.com/"))
        crawler.crawl("Example Help")
        self.assertNotIn("https://help.example.com/pricing", self.requested)
        self.assertNotIn("https://help.example.com/helpless", self.requested)  # /helpless is not under /help
        self.assertIn("https://help.example.com/help/returns", self._pages())
        self.site.reload()
        self.site.stay_under_start = 0
        self.site.save()
        crawler.crawl("Example Help")
        self.assertIn("https://help.example.com/pricing", self._pages())

    def test_single_page_source(self):
        self.site.reload()
        self.site.follow_links = 0
        self.site.save()
        crawler.crawl("Example Help")
        self.assertEqual(set(self._pages()), {"https://help.example.com/help"})
        self.assertNotIn("https://help.example.com/sitemap.xml", self.requested)

    def test_pages_that_fail_are_listed(self):
        SITE_PAGES["https://help.example.com/help"] = page("Help centre", "Welcome to the help centre of Example Trading LLC.",
                                                           links=["/help/returns", "/help/broken"])
        SITE_PAGES["https://help.example.com/help/broken"] = (500, {"content-type": "text/html"}, b"oops")
        crawler.crawl("Example Help")
        site = frappe.get_doc(SITE, "Example Help")
        self.assertEqual(site.crawl_state, "Completed with Errors")
        self.assertEqual(site.error_count, 1)
        self.assertIn("https://help.example.com/help/broken: HTTP 500", site.crawl_log)
        SITE_PAGES.pop("https://help.example.com/help/broken")
        SITE_PAGES["https://help.example.com/help"] = page("Help centre", "Welcome to the help centre of Example Trading LLC.",
                                                           links=["/help/returns"])
        crawler.crawl("Example Help")
        site.reload()
        self.assertEqual((site.crawl_state, site.error_count, site.crawl_log), ("Completed", 0, None))
        SITE_PAGES.clear()
        crawler.crawl("Example Help")
        self.assertEqual(frappe.db.get_value(SITE, "Example Help", "crawl_state"), "Failed")

    def test_preferred_source_comes_first_and_sources_can_be_switched_off(self):
        crawler.crawl("Example Help")
        frappe.db.delete("Support Knowledge Snippet", {"question": "Returns"})
        frappe.get_doc({"doctype": "Support Knowledge Snippet", "question": "Returns", "audience": "Everyone",
                        "answer": "Returns are accepted within 30 days with the receipt."}).insert()
        web = "https://help.example.com/help/returns"
        q = "returns accepted 30 days receipt"

        def first():
            return retrieval.search(q, "Everyone")[0]

        self.site.reload()
        self.site.priority = "High"
        self.site.save()
        self.assertEqual(first()["route"], web)
        self.site.priority = "Low"
        self.site.save()
        self.assertEqual(first()["doctype"], "Support Knowledge Snippet")
        self.assertIn(web, [h["route"] for h in retrieval.search(q, "Everyone")], "both sources still answer")
        # priority only orders real matches: an unrelated question still finds nothing
        self.site.priority = "High"
        self.site.save()
        self.assertEqual(retrieval.search("zebra quantum lighthouse", "Everyone"), [])
        rows = {r["label"]: r for r in retrieval.overview()}
        self.assertEqual((rows["Example Help"]["type"], rows["Example Help"]["state"], rows["Example Help"]["items"]),
                         ("Website", "Active", 4))
        self.assertGreater(rows["Example Help"]["passages"], 0)
        self.assertIn("Knowledge snippets", rows)
        self.site.enabled = 0  # one source off: the others keep answering
        self.site.save()
        hits = retrieval.search(q, "Everyone")
        self.assertNotIn(web, [h["route"] for h in hits])
        self.assertEqual(hits[0]["doctype"], "Support Knowledge Snippet")
        self.assertEqual({r["label"]: r for r in retrieval.overview()}["Example Help"]["state"], "Off")
        frappe.db.delete("Support Knowledge Snippet", {"question": "Returns"})
        frappe.db.delete(CHUNK, {"source_doctype": "Support Knowledge Snippet", "title": "Returns"})

    def test_robots_can_block_the_whole_site(self):
        SITE_PAGES["https://help.example.com/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /\n")
        crawler.crawl("Example Help")
        self.assertEqual(self._pages(), {})
        self.assertEqual([u for u in self.requested if urlparse(u).path.startswith("/help")], [])


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


class TestNothingFound(AIBase):
    """1.16: nothing in any source -> an agent, and (strict) not a single generative AI call."""

    def setUp(self):
        super().setUp()
        frappe.db.set_single_value("Support AI Settings", {
            "enable_ai": 1, "only_answer_from_kb": 1, "strict_no_result": 1, "summary_on_handoff": 1, "enable_copilot": 1,
            "max_ai_replies": 15, "min_relevance": 0.3,
            "no_answer_message": "I couldn't find that in our help articles, so I'm passing you to a member of our team."})
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        frappe.db.set_single_value("Support Portal Settings", {"enable_live_chat": 1, "allow_guest_chat": 1,
                                                              "guest_chat_rate_limit": 1000})
        frappe.cache.delete_keys("thinknxg_support:rl:")

    def _chat(self, text):
        as_user("Guest")
        with patch("thinknxg_support.integrations.ai.engine.respond"):
            r = live_chat.start_guest(text, name="Salim", email="salim.nothing@example.com")
        as_user("Administrator")
        return frappe.get_doc("Support Conversation Link", r["conversation"])

    def _last_outbound(self, conv):
        rows = frappe.get_all("Support Portal Message", filters={"conversation": conv.name, "direction": "Outbound"},
                              fields=["content"], order_by="creation desc", limit=1)
        return rows[0].content if rows else ""

    def test_no_generative_call_when_nothing_is_found(self):
        q = "أين يمكنني شراء تذاكر القطار إلى القمر؟"
        conv = self._chat(q)
        fake = FakeAI("Where can I buy train tickets to the moon?", "x", "y", "z")
        with patch.object(providers, "complete", side_effect=fake):
            engine.answer(conv, q)
        self.assertEqual(fake.calls, [], "no translation, no answer, no summary")
        conv.reload()
        self.assertEqual(conv.handling, "Queued")
        self.assertIn("passing you to a member of our team", self._last_outbound(conv))
        self.assertTrue(frappe.db.exists("Support AI Usage Log", {"conversation": conv.name, "status": "Skipped"}))

    def test_strict_can_be_switched_off(self):
        frappe.db.set_single_value("Support AI Settings", "strict_no_result", 0)
        frappe.clear_document_cache("Support AI Settings", "Support AI Settings")
        q = "أين يمكنني شراء تذاكر القطار إلى المريخ؟"
        conv = self._chat(q)
        fake = FakeAI("Where can I buy train tickets to Mars?", "تم تحويلك إلى فريقنا.", "summary", "more")
        with patch.object(providers, "complete", side_effect=fake):
            engine.answer(conv, q)
        self.assertGreaterEqual(len(fake.calls), 1, "the question is translated to search across languages")
        conv.reload()
        self.assertEqual(conv.handling, "Queued")

    def test_website_answers_cite_the_page(self):
        used = [{"title": "Returns", "route": "https://help.example.com/help/returns"},
                {"title": "Manual", "route": None}]
        conv = self._chat("How do returns work?")
        links = engine._source_links(conv, used)
        self.assertEqual(links[0], {"title": "Returns", "url": "https://help.example.com/help/returns"})
        self.assertIsNone(links[1]["url"])  # uploaded files are private: named, not linked
