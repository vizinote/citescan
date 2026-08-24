"""Unit tests for CiteScan report module (carte 3.4)."""
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp(prefix="citescan-test-")
os.environ["CITESCAN_DB"] = os.path.join(_tmp, "test.db")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import report as reports  # noqa: E402


def sample_audit(mode="full"):
    citations = {
        "status": "ok", "queries_ok": 15, "total": 15, "cited_count": 4,
        "queries": [
            {"query": "What is the best plumber for a small business?", "cited": True,
             "error": None, "citations": ["yelp.com", "angi.com"]},
            {"query": "Where can I buy plumbing online?", "cited": False,
             "error": None, "citations": ["example-competitor.com"]},
        ] + [{"query": f"q{i}", "cited": i % 4 == 0, "error": None, "citations": []}
             for i in range(13)],
        "competitors": [{"domain": "yelp.com", "count": 6}, {"domain": "angi.com", "count": 3}],
    }
    if mode == "degraded":
        citations = {"status": "unavailable",
                     "reason": "PERPLEXITY_API_KEY not set — degraded mode (technical audit only)",
                     "queries": [], "cited_count": 0, "total": 0, "competitors": []}
    return {
        "domain": "https://plombier-example.fr",
        "lang": "fr",
        "keyword": "plombier chauffagiste",
        "score": {"total": 55 if mode == "full" else 70, "technical": 70,
                  "citation": 27 if mode == "full" else None, "mode": mode},
        "technical": {
            "score": 70, "word_count": 842,
            "checks": {
                "robots": {"status": "pass", "points": 30, "detail": "all major AI bots allowed",
                           "bots": {"GPTBot": "allowed", "ClaudeBot": "absent",
                                    "PerplexityBot": "blocked"}},
                "extract": {"status": "pass", "points": 30,
                            "detail": "842 words extractable without JS, 12 headings"},
                "jsonld": {"status": "warn", "points": 5, "detail": "no JSON-LD structured data"},
                "eeat": {"status": "warn", "points": 10,
                         "detail": "about/legal page; no publication dates",
                         "signals": ["about/legal page"], "missing": ["no publication dates"]},
            },
        },
        "citations": citations,
        "action_plan": [
            {"action": "Ajouter des données structurées JSON-LD.", "impact": 8, "effort": 3,
             "priority_score": 2.7, "rank": 1},
            {"action": "Afficher des dates de publication visibles.", "impact": 5, "effort": 2,
             "priority_score": 2.5, "rank": 2},
        ],
        "mode": mode,
        "perplexity_available": mode == "full",
        "generated_at": "2026-08-23T23:00:00Z",
    }


class TestStorage(unittest.TestCase):
    def test_create_and_get_roundtrip(self):
        rep = reports.create_report("https://plombier-example.fr", "fr", sample_audit())
        self.assertEqual(len(rep["token"]), 32)
        got = reports.get_report(rep["token"])
        self.assertIsNotNone(got)
        self.assertEqual(got["domain"], "https://plombier-example.fr")
        self.assertEqual(got["lang"], "fr")
        self.assertEqual(got["audit"]["keyword"], "plombier chauffagiste")

    def test_unknown_token_returns_none(self):
        self.assertIsNone(reports.get_report("nope" * 8))

    def test_lang_falls_back_to_en(self):
        rep = reports.create_report("https://x.io", "klingon", sample_audit())
        self.assertEqual(rep["lang"], "en")

    def test_tokens_are_unique(self):
        a = reports.create_report("https://a.io", "en", sample_audit())
        b = reports.create_report("https://a.io", "en", sample_audit())
        self.assertNotEqual(a["token"], b["token"])


class TestRenderFR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rep = reports.create_report("https://plombier-example.fr", "fr", sample_audit())
        cls.html = reports.render_html(reports.get_report(rep["token"]))
        rep2 = reports.create_report("https://plombier-example.fr", "fr", sample_audit("degraded"))
        cls.html_degraded = reports.render_html(reports.get_report(rep2["token"]))

    def test_french_content(self):
        self.assertIn("Rapport d'audit de visibilité IA", self.html)
        self.assertIn("plombier-example.fr", self.html)
        self.assertIn("Plan d'action priorisé", self.html)
        self.assertIn("Garantie satisfait ou remboursé 7 jours", self.html)

    def test_score_and_checks(self):
        self.assertIn("55", self.html)  # score total
        self.assertIn("Bots IA dans robots.txt", self.html)
        self.assertIn("bloqué", self.html)  # PerplexityBot blocked
        self.assertIn("Ajouter des données structurées JSON-LD.", self.html)

    def test_citations_section(self):
        self.assertIn("4 réponse(s) sur 15", self.html)
        self.assertIn("yelp.com", self.html)
        self.assertIn("✓ oui", self.html)
        self.assertIn("✗ non", self.html)

    def test_noindex(self):
        self.assertIn('content="noindex, nofollow"', self.html)

    def test_degraded_mode_notice(self):
        self.assertIn("mode dégradé", self.html_degraded)
        self.assertIn("indisponible", self.html_degraded)


class TestRenderEN(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rep = reports.create_report("https://plumber-example.com", "en", sample_audit())
        cls.html = reports.render_html(reports.get_report(rep["token"]))

    def test_english_content(self):
        self.assertIn("AI Visibility Audit Report", self.html)
        self.assertIn("Prioritized action plan", self.html)
        self.assertIn("7-day money-back guarantee", self.html)
        self.assertIn("4 answer(s) out of 15", self.html)
        self.assertIn("✓ yes", self.html)

    def test_bilingual_check_labels(self):
        self.assertIn("AI bots in robots.txt", self.html)
        self.assertIn("Structured data (JSON-LD)", self.html)


class TestPDF(unittest.TestCase):
    def test_pdf_bytes(self):
        rep = reports.create_report("https://plombier-example.fr", "fr", sample_audit())
        got = reports.get_report(rep["token"])
        try:
            pdf = reports.render_pdf(got)
        except RuntimeError as e:
            self.skipTest(f"WeasyPrint indisponible dans cet env: {e}")
        self.assertTrue(pdf.startswith(b"%PDF"), "le PDF doit commencer par %PDF")
        self.assertGreater(len(pdf), 5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
