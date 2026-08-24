"""Tests recette 2026-08-24 (carte correctifs post-recette Franck).

Couvre :
- /api/scan ne renvoie JAMAIS de 500 (domaine nu, URL invalide, site injoignable)
- normalisation des domaines nus ("brozapi.com" -> https)
- details techniques localises FR/EN dans l'audit payant
- plan d'action detecte via codes machine (pas via le wording anglais)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from fastapi.testclient import TestClient  # noqa: E402
import audit  # noqa: E402
import main  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


# --- normalize_domain ---
check("nu -> https", main.normalize_domain("brozapi.com") == "https://brozapi.com")
check("path stripped", main.normalize_domain("https://example.fr/a/b?x=1") == "https://example.fr")
check("http kept", main.normalize_domain("http://example.com") == "http://example.com")
check("spaces trimmed", main.normalize_domain("  example.com ") == "https://example.com")
for bad in ("", "   ", "%%%", "http://", "nodot"):
    try:
        main.normalize_domain(bad)
        check(f"invalid rejected: {bad!r}", False, "no ValueError")
    except ValueError:
        check(f"invalid rejected: {bad!r}", True)

# --- /api/scan robustness (jamais de 500) ---
client = TestClient(main.app, raise_server_exceptions=False)

r = client.get("/api/scan", params={"url": "%%%"})
check("invalide -> 400 pas 500", r.status_code == 400, f"got {r.status_code}")

# domaine nu sur un TLD .invalid : echec DNS rapide, ne doit pas lever d'IndexError
r = client.get("/api/scan", params={"url": "inaccessible-zzz.invalid"})
check("site injoignable -> pas de 500", r.status_code in (200, 502, 429),
      f"got {r.status_code}")  # 429 toleré : rate-limit si la suite tourne 2x dans l'heure
if r.status_code == 200:
    body = r.json()
    check("findings presentes meme en echec", len(body.get("findings", [])) == 3)
    check("pas de texte vide", all(f.get("text") for f in body["findings"]))

# --- run_scan : aucune liste vide ne fait planter ---
res = asyncio.run(main.run_scan("https://inaccessible-zzz.invalid", main.SCAN_TEXTS["en"]))
check("run_scan injoignable OK", len(res["findings"]) == 3 and
      all(f["text"] for f in res["findings"]))
res_fr = asyncio.run(main.run_scan("https://inaccessible-zzz.invalid", main.SCAN_TEXTS["fr"]))
check("run_scan FR localise", res_fr["findings"][1]["text"] == "site inaccessible",
      res_fr["findings"][1]["text"])

# --- audit payant : details localises ---
html_fr = """<html><head><title>Boulangerie Martin</title></head>
<body><h1>Boulangerie artisanale</h1>""" + "<p>mot " * 350 + "</p></body></html>"
t_fr = audit.technical_audit(html_fr, None, "https://example.fr", lang="fr")
check("FR: robots detail", "introuvable" in t_fr["checks"]["robots"]["detail"],
      t_fr["checks"]["robots"]["detail"])
check("FR: extract detail actionnable", "cité" in t_fr["checks"]["extract"]["detail"],
      t_fr["checks"]["extract"]["detail"])
check("FR: extract sans compteur de mots brut",
      "mots extractibles" not in t_fr["checks"]["extract"]["detail"] and
      not any(ch.isdigit() for ch in t_fr["checks"]["extract"]["detail"]),
      t_fr["checks"]["extract"]["detail"])
check("FR: jsonld detail", "aucune donnée" in t_fr["checks"]["jsonld"]["detail"])
check("FR: eeat missing FR", any("à propos" in m for m in t_fr["checks"]["eeat"]["missing"]))
check("FR: missing_codes presents",
      "about" in t_fr["checks"]["eeat"]["missing_codes"] and
      "dates" in t_fr["checks"]["eeat"]["missing_codes"])
check("FR: aucun anglais residuel", "without JS" not in str(t_fr) and
      "not found —" not in str(t_fr))

t_en = audit.technical_audit(html_fr, None, "https://example.fr", lang="en")
check("EN: robots detail", "not found" in t_en["checks"]["robots"]["detail"])

# --- plan d'action via codes machine (wording FR) ---
plan_fr = audit.build_action_plan(t_fr, {"status": "unavailable"}, "fr")
check("plan FR detecte no_about/no_dates via codes",
      any("À propos" in a["action"] for a in plan_fr) and
      any("dates" in a["action"] for a in plan_fr), [a["action"][:40] for a in plan_fr])
check("plan FR impeccable (pas d'anglais)",
      all(" the " not in a["action"] and "JavaScript:" not in a["action"] for a in plan_fr))

# --- system prompt Sonar localise ---
check("Sonar system FR", "français" in audit._SONAR_SYSTEM["fr"])
check("Sonar system EN", "English" in audit._SONAR_SYSTEM["en"])

# --- redacteur V4 pro : parsing + fallback ---
good = '{"synthese": "Votre site est solide techniquement mais invisible.", "actions": [{"action": "Ajouter du JSON-LD.", "impact": 8, "effort": 3}]}'
p = audit._parse_writer_output(good)
check("writer: parse JSON propre", p is not None and p["synthese"] and
      p["actions"][0]["rank"] == 1 and p["actions"][0]["priority_score"] == round(8/3, 1))
fenced = "```json\n" + good + "\n```"
check("writer: parse bloc ```json", audit._parse_writer_output(fenced) is not None)
check("writer: rejet JSON invalide", audit._parse_writer_output("not json") is None)
check("writer: rejet sans actions",
      audit._parse_writer_output('{"synthese": "ok", "actions": []}') is None)
check("writer: rejet sans synthese",
      audit._parse_writer_output('{"actions": [{"action": "x", "impact": 5, "effort": 5}]}') is None)

# sans cle OpenRouter : jamais d'appel reseau, fallback explicite
_old_key = audit.OPENROUTER_API_KEY
audit.OPENROUTER_API_KEY = ""
check("writer: None sans cle",
      asyncio.run(audit.write_client_report({"score": {}, "technical": {}, "citations": {}}, "fr")) is None)
audit.OPENROUTER_API_KEY = _old_key

# --- prompt writer multi-moteurs (t_74e5bb97) : la narrative V4 pro compare ---
# les moteurs au lieu de raconter « Perplexity » en dur.
def _audit_stub(citations):
    return {"domain": "https://x.fr", "keyword": "plombier",
            "score": {"total": 55, "technical": 70, "citation": 27},
            "technical": {"checks": {"robots": {"detail": "bots ok"}}},
            "action_plan": [{"action": "Ajouter du JSON-LD.", "impact": 8, "effort": 3}],
            "citations": citations}

# mono-moteur historique (pas de clé "engines") : libellé Perplexity conservé
p_mono = audit._writer_user_prompt(_audit_stub(
    {"status": "ok", "cited_count": 4, "total": 15, "queries": [],
     "competitors": [{"domain": "yelp.com", "count": 2}]}), "fr")
check("writer mono FR : réponses de Perplexity (rétrocompat)",
      "cité dans 4/15 réponses de Perplexity" in p_mono
      and "×" not in p_mono and "{cite_context}" not in p_mono)

# mono-moteur non-Perplexity : plus de « Perplexity » en dur
p_chatgpt = audit._writer_user_prompt(_audit_stub(
    {"status": "ok", "cited_count": 2, "total": 15, "queries": [], "competitors": [],
     "engines_run": ["chatgpt"],
     "engines": {"chatgpt": {"cited_count": 2, "total": 15}}}), "fr")
check("writer mono ChatGPT : libellé dynamique",
      "réponses de ChatGPT" in p_chatgpt and "réponses de Perplexity" not in p_chatgpt)

# multi-moteurs FR : mesures requête × moteur + détail par moteur + écarts
_multi_cit = {
    "status": "partial", "cited_count": 1, "total": 6, "queries": [],
    "competitors": [{"domain": "concurrent.fr", "count": 3}],
    "engines_run": ["perplexity", "gemini", "claude"],
    "engines": {
        "perplexity": {"cited_count": 1, "total": 2, "engine_label": "Perplexity"},
        "gemini": {"cited_count": 0, "total": 2, "engine_label": "Gemini"},
        "claude": {"cited_count": 0, "total": 2, "engine_label": "Claude"}},
    "matrix": [
        {"query": "meilleur logiciel X ?",
         "by_engine": {"perplexity": "yes", "gemini": "no", "claude": "error"}},
        {"query": "acheter X en ligne ?",
         "by_engine": {"perplexity": "no", "gemini": "no", "claude": "error"}}]}
p_multi = audit._writer_user_prompt(_audit_stub(_multi_cit), "fr")
check("writer multi FR : mesures requête × moteur + 2 questions",
      "cité dans 1/6 mesures requête × moteur" in p_multi
      and "2 questions d'intention d'achat posées à Perplexity, Gemini et Claude" in p_multi)
check("writer multi FR : détail par moteur",
      "Perplexity 1/2, Gemini 0/2, Claude 0/2" in p_multi)
check("writer multi FR : écart cité dans le prompt",
      "cité par Perplexity mais pas par Gemini" in p_multi)
check("writer multi FR : hint comparaison dans la consigne synthèse",
      "comparaison entre moteurs" in p_multi)
check("writer multi FR : plus de « réponses de Perplexity » en dur",
      "réponses de Perplexity" not in p_multi)

p_multi_en = audit._writer_user_prompt(_audit_stub(_multi_cit), "en")
check("writer multi EN : query × engine measurements",
      "cited in 1/6 query × engine measurements" in p_multi_en
      and "asked to Perplexity, Gemini and Claude" in p_multi_en
      and "cited by Perplexity but not by Gemini" in p_multi_en
      and "cross-engine comparison" in p_multi_en)

# multi sans écart : mention explicite « les moteurs s'accordent »
_same = dict(_multi_cit, matrix=[
    {"query": "q1", "by_engine": {"perplexity": "yes", "gemini": "yes", "claude": "error"}}])
p_same = audit._writer_user_prompt(_audit_stub(_same), "fr")
check("writer multi sans écart : accord explicite",
      "aucun (les moteurs s'accordent)" in p_same)

# prompts deliverables : plus de « Perplexity » en dur dans l'en-tête verbatims
check("deliverables FR : verbatims multi-IA génériques",
      "les IA répondent réellement" in audit._DELIVERABLES_USER["fr"]
      and "Perplexity répond" not in audit._DELIVERABLES_USER["fr"])
check("deliverables EN : verbatims multi-IA génériques",
      "AI engines actually answer" in audit._DELIVERABLES_USER["en"]
      and "Perplexity actually answers" not in audit._DELIVERABLES_USER["en"])

print(f"\nRECETTE: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
