"""Tests for app/audit.py — offline unit tests + live pipeline test."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import audit

PASS, FAIL = 0, 0

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")

# --- robots bot status ---
r_block = "User-agent: GPTBot\nDisallow: /\n"
r_star = "User-agent: *\nDisallow: /\n"
r_allow = "User-agent: GPTBot\nAllow: /\n"
r_absent = "User-agent: Googlebot\nDisallow: /private/\n"
check("bot blocked explicit", audit._robot_bot_status(r_block, "GPTBot") == "blocked")
check("bot blocked wildcard", audit._robot_bot_status(r_star, "GPTBot") == "blocked")
check("bot allowed explicit", audit._robot_bot_status(r_allow, "GPTBot") == "allowed")
check("bot absent", audit._robot_bot_status(r_absent, "GPTBot") == "absent")

# --- technical audit ---
html_good = """<html><head><title>Boulangerie Martin - Pain artisanal Paris</title>
<script type="application/ld+json">{"@type":"Organization","name":"Martin"}</script>
<meta name="author" content="Jean Martin"></head>
<body><h1>Boulangerie artisanale</h1><time>2026-01-01</time>
<a href="/a-propos">À propos</a>""" + "<p>mot " * 350 + "</p></body></html>"

t = audit.technical_audit(html_good, r_allow, "https://example.fr")
check("good site score high", t["score"] >= 90, f"got {t['score']}")
check("jsonld parsed", "Organization" in t["checks"]["jsonld"].get("types", []))

t2 = audit.technical_audit("<html><body><p>hi</p></body></html>", r_star, "http://example.fr")
check("bad site score low", t2["score"] < 40, f"got {t2['score']}")
check("blocked robots fail", t2["checks"]["robots"]["status"] == "fail")

t3 = audit.technical_audit(html_good, None, "https://example.fr")
check("no robots.txt = warn 15pts", t3["checks"]["robots"]["status"] == "warn" and t3["checks"]["robots"]["points"] == 15)

# --- keyword + queries ---
kw = audit.extract_keyword(html_good, "example.fr")
check("keyword extracted", len(kw) > 3, kw)
qfr = audit.build_queries("boulangerie artisanale", "fr")
qen = audit.build_queries("artisan bakery", "en")
check("15 FR queries", len(qfr) == 15 and all("boulangerie" in q for q in qfr))
check("15 EN queries", len(qen) == 15 and all("bakery" in q for q in qen))

# --- degraded mode (no key) ---
os.environ.pop("PERPLEXITY_API_KEY", None)
audit.PERPLEXITY_API_KEY = ""
c = asyncio.run(audit.citation_audit("https://example.fr", "test", "en"))
check("degraded explicit", c["status"] == "unavailable" and "PERPLEXITY_API_KEY" in c["reason"])

# --- scoring ---
tech = {"score": 80}
cit = {"status": "ok", "total": 15, "cited_count": 3}
s = audit.compute_score(tech, cit)
check("full score weighted", s["total"] == round(0.4*80 + 0.6*20) and s["mode"] == "full")
s2 = audit.compute_score(tech, {"status": "unavailable"})
check("degraded score = technical", s2["total"] == 80 and s2["mode"] == "degraded")

# --- action plan ---
technical = {"checks": {
    "robots": {"status": "fail", "points": 0},
    "jsonld": {"points": 5},
    "extract": {"points": 5},
    "eeat": {"points": 10, "missing": ["no about/legal page", "no publication dates"]},
}}
plan = audit.build_action_plan(technical, {"status": "ok", "total": 15, "cited_count": 0,
                                           "competitors": [{"domain": "x.fr", "count": 5}]}, "fr")
check("plan non-empty", 3 <= len(plan) <= 10)
check("plan sorted by priority", all(plan[i]["priority_score"] >= plan[i+1]["priority_score"] for i in range(len(plan)-1)))
check("plan in FR", any("robots.txt" in p["action"] for p in plan))
check("robots first (impact10/effort1)", "robots" in plan[0]["action"].lower() or "Débloquer" in plan[0]["action"])

# --- keyword cut at slogan tail (carte 3.3 fix) ---
h1_slogan = """<html><head><title>Brozapi</title></head>
<body><h1>Des micro-outils à partir de 39 € pour mettre votre site en conformité</h1></body></html>"""
check("keyword cuts slogan tail", audit.extract_keyword(h1_slogan, "brozapi.com") == "micro-outils")
h1_en = """<html><head><title>Acme</title></head>
<body><h1>The best project management software for teams</h1></body></html>"""
check("keyword EN cuts at 'for'", audit.extract_keyword(h1_en, "acme.com") == "best project management software")

print(f"\nUNIT: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
