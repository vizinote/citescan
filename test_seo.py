"""Tests SEO carte 3.5 — sitemap.xml, robots.txt, cle IndexNow (offline)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from fastapi.testclient import TestClient  # noqa: E402
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


client = TestClient(main.app)

# --- sitemap.xml ---
r = client.get("/sitemap.xml")
check("sitemap 200", r.status_code == 200)
check("sitemap content-type xml", "xml" in r.headers.get("content-type", ""))
check("sitemap liste /", "https://citescan.brozapi.com/" in r.text)
check("sitemap liste /fr/", "https://citescan.brozapi.com/fr/" in r.text)
check("sitemap exclut /rapports/", "/rapports/" not in r.text)

# --- robots.txt ---
r = client.get("/robots.txt")
check("robots 200", r.status_code == 200)
check("robots disallow rapports", "Disallow: /rapports/" in r.text)
check("robots reference sitemap", "Sitemap: https://citescan.brozapi.com/sitemap.xml" in r.text)

# --- cle IndexNow ---
r = client.get(f"/{main.INDEXNOW_KEY}.txt")
check("indexnow key 200", r.status_code == 200)
check("indexnow key corps = cle", r.text.strip() == main.INDEXNOW_KEY)
check("indexnow key connue brozapi",
      main.INDEXNOW_KEY == "a9e8fc609645365e02a9b0e2703de984")

# --- blog + pages sectorielles (t_af45f0e5) ---
r = client.get("/blog/")
check("hub blog 200", r.status_code == 200)
check("hub blog FR", 'lang="fr"' in r.text)
r = client.get("/secteurs/")
check("hub secteurs 200", r.status_code == 200)
check("hub secteurs FR", 'lang="fr"' in r.text)
SECTOR_SLUGS = (
    "restaurant", "avocat",
    # t_8ca3cb5f — 23 pages sectorielles (lots 1-4)
    "artisan", "e-commerce", "agence-immobiliere", "freelance", "coach-consultant", "hotel",
    "medecin-sante", "dentiste", "veterinaire", "salle-de-sport", "coiffeur-beaute", "garage-automobile",
    "expert-comptable", "notaire", "architecte", "courtier-assurance", "agence-web", "photographe",
    "commerce-local", "plombier-chauffagiste", "electricien", "association", "mairie-collectivite",
)
for slug in SECTOR_SLUGS:
    r = client.get(f"/secteurs/{slug}.html")
    check(f"page secteur {slug} 200", r.status_code == 200)
    check(f"page secteur {slug} canonical",
          f"https://citescan.brozapi.com/secteurs/{slug}.html" in r.text)
    check(f"page secteur {slug} CTA scan", 'class="cta-block"' in r.text and 'href="/fr/"' in r.text)
    check(f"page secteur {slug} encart honnetete", 'class="box"' in r.text and "Honnêteté" in r.text)
    check(f"page secteur {slug} footer croise", "badgeia.brozapi.com" in r.text
          and "accessicheck.brozapi.com" in r.text)
    check(f"page secteur {slug} JSON-LD Article", '"@type":"Article"' in r.text)
r = client.get("/sitemap.xml")
check("sitemap liste hub secteurs", "https://citescan.brozapi.com/secteurs/" in r.text)
missing = [s for s in SECTOR_SLUGS if f"/secteurs/{s}.html" not in r.text]
check("sitemap liste les 25 pages secteurs", not missing, f"manquants: {missing}")
# Securite : pas de traversee de chemin, gabarit non public, index non reservi
r = client.get("/secteurs/..%2F..%2Fapp%2Fmain.py")
check("secteurs pas de path traversal", r.status_code in (400, 404))
r = client.get("/blog/_template.html")
check("gabarit blog non public", r.status_code == 404)
r = client.get("/blog/index.html")
check("blog index non reservi en double", r.status_code == 404)
r = client.get("/secteurs/inexistant.html")
check("secteur inconnu 404", r.status_code == 404)
r = client.get("/sitemap.xml")
check("sitemap exclut le gabarit _template", "_template" not in r.text)

print(f"\n{PASS} PASS, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
