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

print(f"\n{PASS} PASS, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
