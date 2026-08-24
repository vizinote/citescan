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
             "error": None, "citations": ["yelp.com", "angi.com"],
             "verbatim": "Les plombiers les mieux notés sont listés sur Yelp. Angi arrive ensuite."},
            {"query": "Where can I buy plumbing online?", "cited": False,
             "error": None, "citations": ["example-competitor.com"],
             "verbatim": "Plusieurs enseignes dominent ce secteur."},
        ] + [{"query": f"q{i}", "cited": i % 4 == 0, "error": None, "citations": [],
              "verbatim": "Réponse type de l'IA."}
             for i in range(13)],
        "competitors": [{"domain": "yelp.com", "count": 6}, {"domain": "angi.com", "count": 3}],
        "competitor_urls": {"yelp.com": "https://yelp.com/plombiers"},
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
        # rapport niveau 2 (t_a857e039)
        "cms": {"cms": "wordpress", "label": "WordPress",
                "instruction": "WordPress détecté : installez l'extension WPCode."},
        "platforms": [{"name": "Yelp", "domain": "yelp.com"}],
        "deliverables": {
            "pourquoi_cites": ["L'IA privilégie les annuaires avec avis clients."],
            "actions_contenu": [
                {"titre": "Prix d'un plombier en 2026 : le guide complet",
                 "angle": "Transparence tarifaire chiffrée par ville."},
            ],
            "faq": [{"q": "Combien coûte un dépannage de plomberie ?",
                     "r": "Comptez entre 80 et 150 € selon l'urgence."}],
            "faq_jsonld": '{\n  "@context": "https://schema.org",\n  "@type": "FAQPage",\n'
                          '  "mainEntity": [{"@type": "Question", "name": "Combien coûte un '
                          'dépannage de plomberie ?", "acceptedAnswer": {"@type": "Answer", '
                          '"text": "Comptez entre 80 et 150 € selon l\'urgence."}}]\n}',
            "roadmap": {"j30": ["Publier la FAQ fournie"], "j60": ["Créer le guide des prix"],
                        "j90": ["S'inscrire sur Yelp"]},
            "roadmap_source": "v4-pro",
            "competitor_pages": [{"domain": "yelp.com", "url": "https://yelp.com/plombiers",
                                  "title": "Yelp plombiers", "headings": "Top 10", "text": "..."}],
            "writer": "deepseek/deepseek-v4-pro-0813",
        },
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


class TestRescan(unittest.TestCase):
    """Re-scan gratuit J+30 (rapport niveau 2, t_a857e039)."""

    def test_rescan_created_with_report(self):
        rep = reports.create_report("https://rescan-example.fr", "fr", sample_audit())
        self.assertIsNotNone(rep.get("rescan_token"))
        rs = reports.get_rescan(rep["rescan_token"])
        self.assertIsNotNone(rs)
        self.assertEqual(rs["parent_token"], rep["token"])
        self.assertEqual(rs["domain"], "https://rescan-example.fr")
        self.assertEqual(rs["status"], "pending")
        self.assertEqual(rs["old_score"], 55)

    def test_rescan_eligible_in_30_days(self):
        import time as _t
        rep = reports.create_report("https://rescan2.fr", "fr", sample_audit())
        rs = reports.get_rescan(rep["rescan_token"])
        created = _t.mktime(_t.strptime(rs["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        eligible = _t.mktime(_t.strptime(rs["eligible_at"], "%Y-%m-%dT%H:%M:%SZ"))
        self.assertAlmostEqual(eligible - created, 30 * 86400, delta=60)

    def test_no_rescan_chain(self):
        rep = reports.create_report("https://rescan3.fr", "fr", sample_audit(),
                                    with_rescan=False)
        self.assertIsNone(rep["rescan_token"])

    def test_report_carries_rescan_url(self):
        rep = reports.create_report("https://rescan4.fr", "fr", sample_audit())
        got = reports.get_report(rep["token"])
        self.assertIn("/rescan/", got["rescan"]["url"])

    def test_rescan_status_flow_and_page(self):
        rep = reports.create_report("https://rescan5.fr", "fr", sample_audit())
        token = rep["rescan_token"]
        # pas encore éligible -> page « disponible à partir du »
        page = reports.render_rescan_page(reports.get_rescan(token))
        self.assertIn("disponible à partir du", page)
        self.assertIn("noindex", page)
        # lancé -> page auto-refresh
        reports.set_rescan_status(token, "running")
        page2 = reports.render_rescan_page(reports.get_rescan(token))
        self.assertIn("refresh", page2)
        # terminé -> delta de score + lien nouveau rapport
        reports.set_rescan_status(token, "done", "newtoken123", score_new := 66)
        rs = reports.get_rescan(token)
        self.assertEqual(rs["status"], "done")
        self.assertEqual(rs["new_score"], 66)
        page3 = reports.render_rescan_page(rs)
        self.assertIn("/rapports/newtoken123", page3)
        self.assertIn("55/100", page3)  # ancien score
        self.assertIn("66/100", page3)  # nouveau score

    def test_rescan_page_en(self):
        rep = reports.create_report("https://rescan6.com", "en", sample_audit())
        page = reports.render_rescan_page(reports.get_rescan(rep["rescan_token"]))
        self.assertIn("available from", page)


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
        self.assertIn("Plan d'action complet", self.html)
        self.assertIn("Garantie satisfait ou remboursé 7 jours", self.html)

    def test_score_and_checks(self):
        self.assertIn("55", self.html)  # score total
        self.assertIn("Bots IA dans robots.txt", self.html)
        self.assertIn("bloqué", self.html)  # PerplexityBot blocked
        self.assertIn("Ajouter des données structurées JSON-LD.", self.html)

    def test_citations_section(self):
        self.assertIn("4 réponse(s) sur", self.html)
        self.assertIn("yelp.com", self.html)
        self.assertIn("✓ oui", self.html)
        self.assertIn("✗ non", self.html)

    def test_niveau2_sections(self):
        """Rapport niveau 2 (t_a857e039) : verbatims, top 3, roadmap, FAQ,
        JSON-LD, plateformes, CMS, re-scan J+30."""
        self.assertIn("Vos 3 actions prioritaires", self.html)
        self.assertIn("Feuille de route 30 / 60 / 90 jours", self.html)
        self.assertIn("Les 30 premiers jours", self.html)
        self.assertIn("Jours 30 à 60", self.html)
        self.assertIn("Jours 60 à 90", self.html)
        self.assertIn("Publier la FAQ fournie", self.html)
        # verbatims réels de l'IA
        self.assertIn("Ce que l'IA répond vraiment", self.html)
        self.assertIn("Les plombiers les mieux notés sont listés sur Yelp", self.html)
        self.assertIn("Pourquoi vos concurrents sont cités", self.html)
        # 3 contenus titre + angle
        self.assertIn("Prix d&#39;un plombier en 2026", self.html)
        self.assertIn("Transparence tarifaire chiffrée par ville.", self.html)
        # FAQ prête à publier + JSON-LD valide
        self.assertIn("Votre FAQ prête à publier", self.html)
        self.assertIn("Combien coûte un dépannage de plomberie ?", self.html)
        self.assertIn("FAQPage", self.html)
        self.assertIn("application/ld+json", self.html)
        # instruction CMS
        self.assertIn("WPCode", self.html)
        # plateformes / annuaires
        self.assertIn("Plateformes et annuaires", self.html)
        self.assertIn("Yelp", self.html)
        # re-scan J+30
        self.assertIn("/rescan/", self.html)
        self.assertIn("Mesurez vos progrès dans 30 jours", self.html)

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
        self.assertIn("Full action plan", self.html)
        self.assertIn("7-day money-back guarantee", self.html)
        self.assertIn("4 answer(s) out of", self.html)
        self.assertIn("✓ yes", self.html)

    def test_niveau2_sections_en(self):
        self.assertIn("Your top 3 priority actions", self.html)
        self.assertIn("30 / 60 / 90-day roadmap", self.html)
        self.assertIn("What the AI actually answers", self.html)
        self.assertIn("Your ready-to-publish FAQ", self.html)
        self.assertIn("FAQPage", self.html)
        self.assertIn("Measure your progress in 30 days", self.html)

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
