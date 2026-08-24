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
check("FR: extract detail", "extractibles" in t_fr["checks"]["extract"]["detail"])
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

print(f"\nRECETTE: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
