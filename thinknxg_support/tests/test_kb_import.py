"""Importer, rebranding, publishing and knowledge-base visibility. The source site is faked."""
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from thinknxg_support.integrations import knowledge
from thinknxg_support.integrations.kb_import import importer, rebrand

ARTICLES = {
    "a1": {"name": "a1", "title": "Getting started with ERPNext", "modified": "2026-01-01",
           "content": "<p>ERPNext is built on the Frappe Framework.</p><pre>bench get-app erpnext</pre>"},
    "a2": {"name": "a2", "title": "Frappe Cloud backups",
           "content": '<p>Frappe Cloud keeps daily backups. See <a href="https://frappe.cloud/docs">docs</a>.</p>'},
}


def fake_get(self, path, params=None, raw=False):
    if path.endswith("get_categories"):
        return [{"name": "c1", "category_name": "Frappe Basics"}]
    if path.endswith("get_category_articles"):
        return [{"name": k} for k in ARTICLES]
    if path.endswith("get_article"):
        return dict(ARTICLES[params["name"]])
    raise importer.SourceError("unexpected " + path)


class TestRebrand(IntegrationTestCase):
    def setUp(self):
        self.c = rebrand.compile_rules([(f, t, 1) for f, t in rebrand.DEFAULT_RULES])

    def test_longest_first_and_code_untouched(self):
        out, n = rebrand.rebrand_html("<p>Frappe Framework and ERPNext</p><code>frappe.get_doc</code><pre>ERPNext</pre>", self.c)
        self.assertIn("thinkNXG Framework and thinkNXG ERP", out)
        self.assertIn("<code>frappe.get_doc</code>", out)
        self.assertIn("<pre>ERPNext</pre>", out)
        self.assertEqual(n, 2)

    def test_urls_emails_paths_kept(self):
        out, _n = rebrand.rebrand_text("Mail hello@frappe.io, open https://frappe.io/ERPNext or /apps/frappe/Frappe", self.c)
        self.assertIn("hello@frappe.io", out)
        self.assertIn("https://frappe.io/ERPNext", out)
        self.assertIn("/apps/frappe/Frappe", out)

    def test_href_kept_title_rebranded(self):
        out, _n = rebrand.rebrand_html('<a href="https://erpnext.com" title="ERPNext">Frappe HR</a>', self.c)
        self.assertIn('href="https://erpnext.com"', out)
        self.assertIn('title="thinkNXG ERP"', out)
        self.assertIn(">thinkNXG HR<", out)

    def test_flags(self):
        self.assertTrue(rebrand.review_flags(ARTICLES["a2"]["content"]))


class TestLinkRules(IntegrationTestCase):
    def setUp(self):
        self.rules = rebrand.compile_link_rules([
            ("Website", "docs.frappe.io/erpnext", "https://docs.thinknxg.com/thinknxgerp", 1),
            ("Website", "frappe.io", "https://thinknxg.com", 0),
            ("E-mail", "frappe.io", "thinknxg.com", 0)])

    def test_links_text_and_email(self):
        html = ('<p><a href="https://docs.frappe.io/erpnext/stock#a">x</a> see docs.frappe.io/erpnext/buying. '
                'Mail <a href="mailto:hi@frappe.io">hi@frappe.io</a>, visit https://frappe.io/pricing.</p>')
        out, n = rebrand.apply_link_rules(html, self.rules)
        self.assertIn('href="https://docs.thinknxg.com/thinknxgerp/stock#a"', out)
        self.assertIn("see docs.thinknxg.com/thinknxgerp/buying.", out)
        self.assertIn('href="mailto:hi@thinknxg.com"', out)
        self.assertIn("visit https://thinknxg.com.", out)
        self.assertEqual(n, 5)

    def test_code_images_attribution_and_source_untouched(self):
        html = ('<pre>curl https://frappe.io/api</pre><img src="https://frappe.io/a.png">'
                '<a href="https://support.frappe.io/help/articles/1">s</a>'
                '<p class="tx-attribution"><small>https://docs.frappe.io/erpnext/x</small></p>')
        out, n = rebrand.apply_link_rules(html, self.rules, {"support.frappe.io"})
        self.assertEqual(n, 0)
        self.assertEqual(out.count("frappe.io"), 4)

    def test_prefix_on_path_boundary(self):
        self.assertIsNone(rebrand.rewrite_address("https://docs.frappe.io/erpnextish", self.rules[:1]))

    def test_validation(self):
        self.assertTrue(rebrand.validate_link_rule("Website", "frappe.io", "", 1))
        self.assertTrue(rebrand.validate_link_rule("Website", "frappe.io", "http://x.com", 1))
        self.assertIsNone(rebrand.validate_link_rule("Website", "frappe.io", "", 0))


class TestImporter(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        for dt in ("Support Article Import", "Support Knowledge Article"):
            frappe.db.delete(dt)
        if frappe.db.exists("Support Knowledge Source", "Test Source"):
            frappe.delete_doc("Support Knowledge Source", "Test Source", force=True)
        self.src = frappe.get_doc({
            "doctype": "Support Knowledge Source", "source_name": "Test Source", "source_type": "Frappe Helpdesk",
            "base_url": "https://help.example.com", "target": "thinkDesk Knowledge Base", "download_images": 0,
            "rules": [{"find": f, "replace_with": r, "match_case": 1, "enabled": 1} for f, r in rebrand.DEFAULT_RULES],
        }).insert()
        importer.PAUSE = 0

    def _run(self):
        with patch.object(importer.Client, "get", fake_get):
            return importer.run("Test Source")

    def test_proposals_not_published(self):
        self._run()
        rows = frappe.get_all("Support Article Import", filters={"source": "Test Source"},
                              fields=["proposed_title", "status", "category_name"])
        self.assertEqual(len(rows), 2)
        titles = {r.proposed_title for r in rows}
        self.assertIn("Getting started with thinkNXG ERP", titles)
        self.assertIn("thinkNXG Cloud backups", titles)
        self.assertTrue(all(r.status in ("Proposed", "Needs Review") for r in rows))
        self.assertEqual({r.category_name for r in rows}, {"thinkNXG Basics"})
        self.assertFalse(frappe.db.count("Support Knowledge Article"))

    def test_publish_needs_licence_then_attributes(self):
        self._run()
        name = frappe.db.get_value("Support Article Import", {"source_id": "a1"})
        self.assertRaises(frappe.ValidationError, importer.publish_one, name)
        self.src.reload()
        self.src.licence_confirmed = 1
        self.src.save()
        art = importer.publish_one(name)
        doc = frappe.get_doc("Support Knowledge Article", art)
        self.assertEqual(doc.status, "Published")
        self.assertIn("tx-attribution", doc.content)
        self.assertIn("CC BY-SA 4.0", doc.content)
        self.assertIn("bench get-app erpnext", doc.content)

    def test_relink_published(self):
        self._run()
        self.src.reload()
        self.src.licence_confirmed = 1
        self.src.save()
        name = frappe.db.get_value("Support Article Import", {"source_id": "a2"})
        art = importer.publish_one(name)
        self.assertIn("https://frappe.cloud/docs", frappe.db.get_value("Support Knowledge Article", art, "content"))
        self.src.reload()
        self.src.append("link_rules", {"kind": "Website", "find": "frappe.cloud", "replace_with": "https://cloud.thinknxg.com",
                                       "keep_path": 1, "enabled": 1})
        self.src.save()
        importer.relink_published("Test Source")
        content = frappe.db.get_value("Support Knowledge Article", art, "content")
        self.assertIn("https://cloud.thinknxg.com/docs", content)
        self.assertIn("tx-attribution", content)

    def test_source_change_does_not_overwrite(self):
        self._run()
        self.src.reload()
        self.src.licence_confirmed = 1
        self.src.save()
        name = frappe.db.get_value("Support Article Import", {"source_id": "a1"})
        art = importer.publish_one(name)
        ARTICLES["a1"]["content"] += "<p>New paragraph</p>"
        try:
            self._run()
        finally:
            ARTICLES["a1"]["content"] = ARTICLES["a1"]["content"].replace("<p>New paragraph</p>", "")
        self.assertEqual(frappe.db.get_value("Support Article Import", name, "status"), "Source Changed")
        self.assertNotIn("New paragraph", frappe.db.get_value("Support Knowledge Article", art, "content"))

    def test_attribution_required(self):
        self.src.attribution_template = "Thanks"
        self.assertRaises(frappe.ValidationError, self.src.save)


class TestKnowledgeVisibility(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.delete("Support Knowledge Article")
        frappe.db.delete("Support Article Feedback")
        if not frappe.db.exists("Support Knowledge Category", "General"):
            frappe.get_doc({"doctype": "Support Knowledge Category", "category_name": "General"}).insert()
        for title, status, aud in (("Public one", "Published", "Everyone"), ("Customers only", "Published", "Customers"),
                                   ("Draft one", "Draft", "Everyone")):
            frappe.get_doc({"doctype": "Support Knowledge Article", "title": title, "status": status, "audience": aud,
                            "category": "General", "content": f"<p>{title} body</p>"}).insert()

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_guest_sees_public_only(self):
        frappe.set_user("Guest")
        titles = {a["title"] for a in knowledge.search_articles()}
        self.assertEqual(titles, {"Public one"})

    def test_customer_audience(self):
        titles = {a["title"] for a in knowledge.search_articles(audience="Customers")}
        self.assertEqual(titles, {"Public one", "Customers only"})

    def test_draft_and_customer_article_hidden_from_guest(self):
        frappe.set_user("Guest")
        hidden = frappe.db.get_value("Support Knowledge Article", {"title": "Customers only"})
        self.assertRaises(frappe.DoesNotExistError, knowledge.get_article, hidden)
        draft = frappe.db.get_value("Support Knowledge Article", {"title": "Draft one"})
        self.assertRaises(frappe.DoesNotExistError, knowledge.get_article, draft)

    def test_sidebar_groups_by_category_and_audience(self):
        frappe.set_user("Guest")
        groups = knowledge.sidebar(audience="Everyone")
        titles = {a["title"] for g in groups for a in g["articles"]}
        self.assertEqual(titles, {"Public one"})
        self.assertEqual(groups[0]["label"], "General")
        frappe.set_user("Administrator")
        titles = {a["title"] for g in knowledge.sidebar(audience="Customers") for a in g["articles"]}
        self.assertEqual(titles, {"Public one", "Customers only"})

    def test_related_excludes_self_and_hidden(self):
        public = frappe.db.get_value("Support Knowledge Article", {"title": "Public one"})
        frappe.set_user("Guest")
        self.assertEqual(knowledge.related(public, audience="Everyone"), [])
        frappe.set_user("Administrator")
        rel = knowledge.related(public, audience="Customers")
        self.assertEqual([r["title"] for r in rel], ["Customers only"])

    def test_feedback_one_vote_per_reader(self):
        public = frappe.db.get_value("Support Knowledge Article", {"title": "Public one"})
        knowledge.record_feedback(public, "Helpful")
        knowledge.record_feedback(public, "Not Helpful", "Missing a screenshot")
        rows = frappe.get_all("Support Article Feedback", filters={"article": public}, fields=["vote", "comment"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].vote, "Not Helpful")
        self.assertEqual(knowledge.my_vote(public), "Not Helpful")
        self.assertEqual(frappe.db.get_value("Support Knowledge Article", public, "not_helpful_votes"), 1)

    def test_feedback_needs_a_readable_article(self):
        draft = frappe.db.get_value("Support Knowledge Article", {"title": "Draft one"})
        frappe.set_user("Guest")
        self.assertRaises(frappe.DoesNotExistError, knowledge.record_feedback, draft, "Helpful")
        self.assertRaises(frappe.ValidationError, knowledge.record_feedback, "x", "Maybe")

    def test_assistant_indexes_native_articles(self):
        from thinknxg_support.integrations.ai import retrieval

        names = {(r[1], r[4]) for r in retrieval.sources() if r[0] == "Support Knowledge Article"}
        self.assertEqual(len(names), 2)
        self.assertIn("Customers", {a for _n, a in names})
