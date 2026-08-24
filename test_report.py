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

    def test_annexe_vulgarisee_fr(self):
        """Annexe lisible TPE (t_7c78a520) : encart de lecture + une phrase
        simple par contrôle + légende du tableau des bots."""
        self.assertIn("Comment lire cette annexe", self.html)
        self.assertIn("robots.txt est le fichier qui autorise ou non les robots des IA",
                      self.html)
        self.assertIn("Les IA lisent le texte brut de votre page", self.html)
        self.assertIn("Le JSON-LD est une étiquette invisible", self.html)
        self.assertIn("Les IA préfèrent citer des sites crédibles", self.html)
        self.assertIn("autorisé » = il peut", self.html)  # légende tableau bots
        # présent aussi en mode dégradé
        self.assertIn("Comment lire cette annexe", self.html_degraded)


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

    def test_annexe_vulgarisee_en(self):
        """Plain-language appendix (t_7c78a520): how-to box + one plain sentence
        per check + bots table legend."""
        self.assertIn("How to read this appendix", self.html)
        self.assertIn("robots.txt is the file that allows or blocks AI crawlers", self.html)
        self.assertIn("AIs read the raw text of your page", self.html)
        self.assertIn("JSON-LD is an invisible label", self.html)
        self.assertIn("AIs prefer citing credible sites", self.html)
        self.assertIn('"allowed" = it can read your site', self.html)  # bots legend


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


# ---------------------------------------------------------------- anti-trou
# Recette t_72143dd9 : aucune phrase du rapport (ou de l'email de livraison)
# ne doit contenir de trou laissé par une variable de gabarit non injectée.

import re  # noqa: E402


def _text(html_page):
    """Gèle le texte rendu : tags -> newline, entités décodées."""
    t = re.sub(r"<script.*?</script>", " ", html_page, flags=re.S)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    import html as _h
    return _h.unescape(t)


def assert_no_hole(testcase, raw_html, label):
    """Vérifie qu'AUCUNE phrase du document rendu ne contient de trou."""
    # 1. restes de gabarit Jinja non rendus
    testcase.assertNotRegex(raw_html, r"\{\{|\{%", f"{label}: gabarit Jinja non rendu")
    # 2. balise <strong> vide (variable injectée vide)
    testcase.assertNotRegex(raw_html, r"<strong>\s*</strong>",
                            f"{label}: <strong> vide")
    # 3. 'None' injecté par une variable Python None
    testcase.assertNotRegex(raw_html, r">\s*None\s*<", f"{label}: 'None' injecté")
    text = _text(raw_html)
    # 4. double espace avant une ponctuation (marque d'un trou)
    testcase.assertIsNone(
        re.search(r"\S  +[,:.;!?]", text),
        f"{label}: double espace avant ponctuation")
    # 5. la phrase re-scan DU GABARIT doit finir par une date, pas par un trou.
    #    Cibler les phrases exactes du gabarit (t_74e5bb97) : un verbatim IA
    #    peut contenir « à partir du 1er septembre » en prose légitime.
    for m in re.finditer(
            r"(actif à partir du|disponible à partir du|becomes active on|available from)"
            r"\s*\n?\s*([^\n<]*)", text):
        suite = m.group(2).strip()
        testcase.assertTrue(
            re.match(r"(\d{4}-\d{2}-\d{2}|J\+30|day 30)", suite),
            f"{label}: date de re-scan absente après « {m.group(1)} » (trouvé: {suite!r})")
    # 6. la phrase d'intro des verbatims doit contenir les compteurs
    for m in re.finditer(r"(Nous avons posé|We asked)([^\n]*\n?[^\n]*)", text):
        phrase = m.group(0)
        testcase.assertRegex(phrase, r"\d+",
                             f"{label}: compteurs absents de l'intro verbatims")


class TestNoHoles(unittest.TestCase):
    """Non-régression t_72143dd9 : gel du texte rendu, zéro trou toléré."""

    def _render(self, lang, mode="full", tamper=None):
        rep = reports.create_report(f"https://hole-{mode}.{lang}", lang,
                                    sample_audit(mode))
        got = reports.get_report(rep["token"])
        if tamper:
            tamper(got)
        return reports.render_html(got)

    def test_no_hole_fr_full(self):
        assert_no_hole(self, self._render("fr"), "rapport FR")

    def test_no_hole_en_full(self):
        assert_no_hole(self, self._render("en"), "rapport EN")

    def test_no_hole_fr_degraded(self):
        assert_no_hole(self, self._render("fr", "degraded"), "rapport FR dégradé")

    def test_no_hole_en_degraded(self):
        assert_no_hole(self, self._render("en", "degraded"), "rapport EN dégradé")

    def test_rescan_date_fallback_when_eligible_at_missing(self):
        """Si eligible_at est vide en DB, la date J+30 est recalculée — jamais de trou."""
        def tamper(rep):
            rep["rescan"]["eligible_at"] = ""
        html_page = self._render("fr", tamper=tamper)
        self.assertNotRegex(html_page, r"à partir du\s*<strong>\s*</strong>")
        m = re.search(r"à partir du\s*<strong>([^<]+)</strong>", html_page)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"\d{4}-\d{2}-\d{2}",
                         "le fallback doit recalculer la date J+30")

    def test_counters_none_safe(self):
        """cited_count/total=None dans l'audit -> 0 rendu, jamais 'None'."""
        def tamper(rep):
            rep["audit"]["citations"]["cited_count"] = None
            rep["audit"]["citations"]["total"] = None
        html_page = self._render("fr", tamper=tamper)
        self.assertNotIn("None", _text(html_page))
        self.assertIn("0 réponse(s) sur\n  0", html_page)

    def test_no_hole_rescan_pages(self):
        rep = reports.create_report("https://hole-rescan.fr", "fr", sample_audit())
        for status in ("pending", "running"):
            reports.set_rescan_status(rep["rescan_token"], status)
            page = reports.render_rescan_page(reports.get_rescan(rep["rescan_token"]))
            assert_no_hole(self, page, f"page rescan {status}")
            self.assertNotRegex(_text(page), r"à partir du\s*[.:]?\s*$")

    def test_no_hole_delivery_email(self):
        """L'email de livraison (source canonique deployment/) ne contient aucun trou,
        même quand rescan_date est None (fallback J+30 / day 30)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "deliveries",
            os.path.join(os.path.dirname(__file__),
                         "deployment", "citescan-deliveries.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for lang, marker in (("fr", "J+30"), ("en", "day 30")):
            _s, text, html_mail = mod.email_body(
                "https://plombier-example.fr", lang,
                "https://citescan.brozapi.com/rapports/xxx", 55, "full",
                top_actions=["Ajouter des dates de publication."],
                url_rescan="https://citescan.brozapi.com/rescan/yyy",
                rescan_date=None)
            self.assertIn(marker, text, f"email {lang}: fallback date absent")
            for doc, lbl in ((text, f"email texte {lang}"),
                             (html_mail, f"email html {lang}")):
                self.assertNotRegex(doc, r"\{\{|\{%")
                self.assertIsNone(re.search(r"\S  +[,:.;!?]", _text(doc)),
                                  f"{lbl}: double espace avant ponctuation")
                self.assertNotRegex(doc, r"à partir du\s*[:.]?\s*$",
                                    f"{lbl}: trou après 'à partir du'")


# ---------------------------------------------------------------- multi-moteurs (t_9864864c)

def sample_audit_multi():
    """Audit 4 moteurs : claude en panne (résultats partiels), chatgpt demandé
    mais sans clé au moment de l'audit (engines_missing)."""
    a = sample_audit()
    queries_p = [
        {"query": "Quel est le meilleur logiciel X ?", "cited": True,
         "error": None, "citations": ["concurrent.fr"],
         "verbatim": "Perplexity cite le site en premier."},
        {"query": "Où acheter X en ligne ?", "cited": False,
         "error": None, "citations": ["concurrent.fr"],
         "verbatim": "Perplexity cite surtout les annuaires."},
    ]
    queries_g = [
        {"query": "Quel est le meilleur logiciel X ?", "cited": False,
         "error": None, "citations": ["annuaire.fr"],
         "verbatim": "Gemini privilégie les comparatifs."},
        {"query": "Où acheter X en ligne ?", "cited": False,
         "error": None, "citations": [],
         "verbatim": "Gemini ne cite pas ce site."},
    ]
    queries_c_fail = [
        {"query": q["query"], "cited": False, "error": "HTTP 500",
         "citations": [], "verbatim": ""} for q in queries_p
    ]
    a["citations"] = {
        "status": "partial", "queries_ok": 4, "total": 6, "cited_count": 1,
        "queries": [
            {"query": "Quel est le meilleur logiciel X ?", "cited": True,
             "error": None, "citations": ["concurrent.fr"],
             "verbatim": "Perplexity cite le site en premier.",
             "by_engine": {"perplexity": "yes", "gemini": "no", "claude": "error"}},
            {"query": "Où acheter X en ligne ?", "cited": False, "error": None,
             "citations": ["concurrent.fr"],
             "verbatim": "Perplexity cite surtout les annuaires.",
             "by_engine": {"perplexity": "no", "gemini": "no", "claude": "error"}},
        ],
        "competitors": [{"domain": "concurrent.fr", "count": 3}],
        "competitor_urls": {"concurrent.fr": "https://concurrent.fr/x"},
        "cost_usd": 0.02,
        "engine": "multi:perplexity,gemini,claude",
        "engines_run": ["perplexity", "gemini", "claude"],
        "engines_missing": ["chatgpt"],
        "matrix": [
            {"query": "Quel est le meilleur logiciel X ?",
             "by_engine": {"perplexity": "yes", "gemini": "no", "claude": "error"}},
            {"query": "Où acheter X en ligne ?",
             "by_engine": {"perplexity": "no", "gemini": "no", "claude": "error"}},
        ],
        "engines": {
            "perplexity": {"status": "ok", "queries_ok": 2, "total": 2,
                           "cited_count": 1, "queries": queries_p,
                           "competitors": [{"domain": "concurrent.fr", "count": 2}],
                           "competitor_urls": {}, "cost_usd": 0.01,
                           "engine": "perplexity", "engine_label": "Perplexity"},
            "gemini": {"status": "ok", "queries_ok": 2, "total": 2,
                       "cited_count": 0, "queries": queries_g,
                       "competitors": [{"domain": "annuaire.fr", "count": 1}],
                       "competitor_urls": {}, "cost_usd": 0.01,
                       "engine": "gemini", "engine_label": "Gemini"},
            "claude": {"status": "failed", "queries_ok": 0, "total": 2,
                       "cited_count": 0, "queries": queries_c_fail,
                       "competitors": [], "competitor_urls": {}, "cost_usd": 0.0,
                       "engine": "claude", "engine_label": "Claude"},
        },
    }
    a["engines"] = ["perplexity", "gemini", "claude"]
    return a


class TestRenderMultiEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rep = reports.create_report("https://plombier-example.fr", "fr",
                                    sample_audit_multi())
        cls.html = reports.render_html(reports.get_report(rep["token"]))
        rep2 = reports.create_report("https://plumber-example.com", "en",
                                     sample_audit_multi())
        cls.html_en = reports.render_html(reports.get_report(rep2["token"]))

    def test_matrix_fr(self):
        self.assertIn("Visibilité par moteur d'IA", self.html)
        self.assertIn("<th>Perplexity</th>", self.html)
        self.assertIn("<th>Gemini</th>", self.html)
        self.assertIn("<th>Claude</th>", self.html)
        self.assertIn("mesures requête × moteur", self.html)

    def test_gaps_fr(self):
        self.assertIn("Écarts entre moteurs", self.html)
        self.assertIn("cité par Perplexity mais pas par Gemini", self.html)

    def test_per_engine_verbatims_fr(self):
        self.assertIn("Ce que chaque IA répond vraiment (verbatims par moteur)", self.html)
        self.assertIn("Perplexity — votre site cité dans 1 réponse(s) sur 2", self.html)
        self.assertIn("Perplexity cite le site en premier.", self.html)
        self.assertIn("Gemini privilégie les comparatifs.", self.html)

    def test_no_source_cited_explicit_fr(self):
        # D2 (t_148128db) : quand aucune source n'est extraite, la ligne
        # « Cités à votre place » ne disparaît pas silencieusement — le client
        # lit explicitement qu'aucune source n'a été citée.
        self.assertIn("Aucune source citée dans cette réponse.", self.html)
        self.assertIn("No source cited in this answer.", self.html_en)

    def test_unavailable_notice_fr(self):
        # claude en panne + chatgpt sans clé -> les deux mentionnés
        self.assertIn("indisponible(s) lors de", self.html)
        self.assertIn("ChatGPT", self.html)
        self.assertIn("Claude était indisponible lors de l'audit", self.html)

    def test_multi_en(self):
        self.assertIn("Visibility by AI engine", self.html_en)
        self.assertIn("Differences between engines", self.html_en)
        self.assertIn("cited by Perplexity but not by Gemini", self.html_en)
        self.assertIn("verbatims by engine", self.html_en)
        self.assertIn("query × engine measurements", self.html_en)

    def test_legacy_single_engine_unchanged(self):
        rep = reports.create_report("https://plombier-example.fr", "fr", sample_audit())
        html = reports.render_html(reports.get_report(rep["token"]))
        self.assertIn("Ce que l'IA répond vraiment (verbatims)", html)
        self.assertNotIn("Visibilité par moteur d'IA", html)
        self.assertIn("Détail des 15 requêtes testées", html)

    def test_no_hole_multi_fr(self):
        assert_no_hole(self, self.html, "rapport multi FR")

    def test_no_hole_multi_en(self):
        assert_no_hole(self, self.html_en, "rapport multi EN")

    def test_verbatim_with_apartir_du_is_not_a_hole(self):
        """Recette live t_74e5bb97 : un verbatim IA contenant « à partir du
        1er septembre 2026 » (prose légitime) ne doit PAS être pris pour un
        trou de variable — le contrôle date cible les phrases du gabarit."""
        def tamper(rep):
            rep["audit"]["citations"]["engines"]["perplexity"]["queries"][0][
                "verbatim"] = ("La facturation électronique devient obligatoire "
                               "à partir du 1er septembre 2026 pour les TPE.")
        rep = reports.create_report("https://verbatim-apartir.fr", "fr",
                                    sample_audit_multi())
        got = reports.get_report(rep["token"])
        tamper(got)
        html_page = reports.render_html(got)
        self.assertIn("à partir du 1er septembre 2026", html_page)
        assert_no_hole(self, html_page, "rapport multi FR verbatim « à partir du »")


# ---------------------------------------------------------------- passerelle « Aller plus loin » (t_a351f0cd)
# Section commerciale CONDITIONNELLE et honnête : jamais sans signal réel.

def _audit_with_ecosystem(eco):
    a = sample_audit()
    if eco is not None:
        a["ecosystem"] = eco
    return a


ECO_NONE = {"chat_widgets": [],
            "accessibility": {"images_total": 2, "images_missing_alt": 0,
                              "html_lang": True, "weak": False}}
ECO_CHATBOT = {"chat_widgets": [{"key": "intercom", "label": "Intercom"}],
               "accessibility": {"images_total": 2, "images_missing_alt": 0,
                                 "html_lang": True, "weak": False}}
ECO_A11Y = {"chat_widgets": [],
            "accessibility": {"images_total": 5, "images_missing_alt": 4,
                              "html_lang": True, "weak": True}}
ECO_BOTH = {"chat_widgets": [{"key": "crisp", "label": "Crisp"}],
            "accessibility": {"images_total": 5, "images_missing_alt": 3,
                              "html_lang": False, "weak": True}}


def _render_fr_en(audit_dict):
    rep = reports.create_report("https://plombier-example.fr", "fr", audit_dict)
    html_fr = reports.render_html(reports.get_report(rep["token"]))
    rep = reports.create_report("https://plumber-example.com", "en", audit_dict)
    html_en = reports.render_html(reports.get_report(rep["token"]))
    return html_fr, html_en


class TestUpsell(unittest.TestCase):
    def test_no_signal_no_section(self):
        # Cas 1 : aucun signal -> la section ne s'affiche PAS du tout
        for eco in (None, ECO_NONE):  # None = rapports déjà en base (legacy)
            html_fr, html_en = _render_fr_en(_audit_with_ecosystem(eco))
            for html in (html_fr, html_en):
                self.assertNotIn("Aller plus loin", html)
                self.assertNotIn("Going further", html)
                self.assertNotIn("badgeia.brozapi.com", html)
                self.assertNotIn("accessicheck.brozapi.com", html)

    def test_chatbot_only_shows_badgeia(self):
        # Cas 2 : widget IA détecté -> BadgeIA seul, jamais AccessiCheck
        html_fr, html_en = _render_fr_en(_audit_with_ecosystem(ECO_CHATBOT))
        self.assertIn("Aller plus loin", html_fr)
        self.assertIn("Intercom", html_fr)
        self.assertIn("39 €", html_fr)
        self.assertIn("https://badgeia.brozapi.com/", html_fr)
        self.assertIn("article 50", html_fr)
        self.assertNotIn("accessicheck.brozapi.com", html_fr)
        self.assertIn("Going further", html_en)
        self.assertIn("€39", html_en)
        self.assertIn("Article 50", html_en)
        self.assertNotIn("accessicheck.brozapi.com", html_en)

    def test_weak_a11y_only_shows_accessicheck(self):
        # Cas 3 : signaux d'accessibilité faibles -> AccessiCheck seul
        html_fr, html_en = _render_fr_en(_audit_with_ecosystem(ECO_A11Y))
        self.assertIn("Aller plus loin", html_fr)
        self.assertIn("dès 29 €", html_fr)
        self.assertIn("https://accessicheck.brozapi.com/", html_fr)
        self.assertIn("4 image(s) sans texte alternatif", html_fr)
        self.assertNotIn("badgeia.brozapi.com", html_fr)
        self.assertIn("from €29", html_en)
        self.assertIn("4 image(s) without alternative text", html_en)
        self.assertNotIn("badgeia.brozapi.com", html_en)

    def test_both_signals_show_both(self):
        # Cas 4 : les deux signaux réels -> les deux mentions (jamais sinon)
        html_fr, _ = _render_fr_en(_audit_with_ecosystem(ECO_BOTH))
        self.assertIn("Crisp", html_fr)
        self.assertIn("https://badgeia.brozapi.com/", html_fr)
        self.assertIn("https://accessicheck.brozapi.com/", html_fr)
        self.assertIn("3 image(s) sans texte alternatif", html_fr)
        self.assertIn("attribut de langue absent", html_fr)
        # une seule occurrence de chaque (pas de matraquage)
        self.assertEqual(html_fr.count("badgeia.brozapi.com"), 1)
        self.assertEqual(html_fr.count("accessicheck.brozapi.com"), 1)

    def test_generic_widget_localized(self):
        eco = {"chat_widgets": [{"key": "chatbot_generic", "label": None}],
               "accessibility": {"images_total": 0, "images_missing_alt": 0,
                                 "html_lang": True, "weak": False}}
        html_fr, html_en = _render_fr_en(_audit_with_ecosystem(eco))
        self.assertIn("un widget de chat", html_fr)
        self.assertIn("a chat widget", html_en)

    def test_no_hole_upsell_fr(self):
        html_fr, _ = _render_fr_en(_audit_with_ecosystem(ECO_BOTH))
        assert_no_hole(self, html_fr, "rapport FR + passerelle")

    def test_no_hole_upsell_en(self):
        _, html_en = _render_fr_en(_audit_with_ecosystem(ECO_BOTH))
        assert_no_hole(self, html_en, "rapport EN + passerelle")


if __name__ == "__main__":
    unittest.main(verbosity=2)
