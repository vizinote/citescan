"""Recette t_a351f0cd : POST /api/report avec fixture (0 cout) puis GET de la
page rapport — verification du rendu conditionnel « Aller plus loin »."""
import json
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="citescan-recette-")
os.environ["CITESCAN_DB"] = os.path.join(_tmp, "recette.db")
os.environ["CITESCAN_INTERNAL_TOKEN"] = "recette-token"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)
H = {"X-Internal-Token": "recette-token"}

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


BASE_AUDIT = {
    "domain": "https://fixture-recette.fr", "lang": "fr",
    "keyword": "plombier chauffagiste",
    "score": {"total": 55, "technical": 70, "citation": 27, "mode": "full"},
    "technical": {"score": 70, "word_count": 842, "checks": {}},
    "citations": {"status": "ok", "queries_ok": 15, "total": 15,
                  "cited_count": 4, "queries": [], "competitors": []},
    "action_plan": [{"action": "Ajouter du JSON-LD.", "impact": 8, "effort": 3,
                     "priority_score": 2.7, "rank": 1}],
    "cms": {"cms": "unknown", "label": "-", "instruction": ""},
    "platforms": [], "deliverables": {}, "mode": "full",
    "generated_at": "2026-08-24T20:00:00Z",
}

ECO_NONE = {"chat_widgets": [],
            "accessibility": {"images_total": 2, "images_missing_alt": 0,
                              "html_lang": True, "weak": False}}
ECO_BOTH = {"chat_widgets": [{"key": "tidio", "label": "Tidio"}],
            "accessibility": {"images_total": 6, "images_missing_alt": 5,
                              "html_lang": False, "weak": True}}


def make_report(lang, eco):
    audit = dict(BASE_AUDIT)
    audit["lang"] = lang
    audit["ecosystem"] = eco
    r = client.post("/api/report", headers=H,
                    content=json.dumps({"lang": lang, "audit": audit}))
    assert r.status_code == 200, f"POST /api/report -> {r.status_code}: {r.text[:200]}"
    token = r.json()["url_html"].rsplit("/", 1)[-1]
    page = client.get(f"/rapports/{token}")
    assert page.status_code == 200
    return page.text


# Cas aucun signal -> aucune section
html = make_report("fr", ECO_NONE)
check("recette: aucun signal -> pas de section FR",
      "Aller plus loin" not in html and "badgeia.brozapi.com" not in html
      and "accessicheck.brozapi.com" not in html)

# Cas les deux signaux -> les deux mentions
html = make_report("fr", ECO_BOTH)
check("recette: section « Aller plus loin » affichée FR", "Aller plus loin" in html)
check("recette: BadgeIA mentionné (Tidio détecté)",
      "Tidio" in html and "https://badgeia.brozapi.com/" in html and "39 €" in html)
check("recette: AccessiCheck mentionné (a11y faible)",
      "https://accessicheck.brozapi.com/" in html and "dès 29 €" in html
      and "5 image(s) sans texte alternatif" in html)
check("recette: une seule occurrence de chaque lien",
      html.count("badgeia.brozapi.com") == 1
      and html.count("accessicheck.brozapi.com") == 1)

html_en = make_report("en", ECO_BOTH)
check("recette: section « Going further » affichée EN",
      "Going further" in html_en and "€39" in html_en and "from €29" in html_en)

# token requis
r = client.post("/api/report", content=json.dumps({"lang": "fr", "audit": BASE_AUDIT}))
check("recette: POST sans token -> 403", r.status_code == 403)

print(f"\nRECETTE UPSELL: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
