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

# --- detection de secteur V4 pro + garde-fou Sonar (t_ffc46988) ---
sig = audit.extract_page_signals("""<html><head><title>Brozapi — micro-SaaS</title>
<meta name="description" content="Studio de micro-SaaS pour entrepreneurs">
<script type="application/ld+json">{"@type":"Organization","name":"Brozapi"}</script></head>
<body><h1>Des logiciels en ligne pour entrepreneurs</h1><p>BadgeIA est un badge IA.</p></body></html>""")
check("signals: title", sig["title"].startswith("Brozapi"))
check("signals: h1", "logiciels en ligne" in sig["h1"])
check("signals: desc", "micro-SaaS" in sig["desc"])
check("signals: jsonld", "Organization" in sig["jsonld"])
check("signals: text excerpt", "BadgeIA" in sig["text"])

check("clean_sector ok", audit._clean_sector(" « logiciels en ligne pour entrepreneurs » ") ==
      "logiciels en ligne pour entrepreneurs")
check("clean_sector rejette 1 mot", audit._clean_sector("logiciels") == "")
check("clean_sector rejette trop long", audit._clean_sector("un " * 40) == "")
check("parse_json_object propre", audit._parse_json_object('{"secteur": "x y"}') == {"secteur": "x y"})
check("parse_json_object fenced", audit._parse_json_object('```json\n{"a": 1}\n```') == {"a": 1})
check("parse_json_object bruit autour",
      audit._parse_json_object('voici {"a": 1} merci') == {"a": 1})
check("parse_json_object invalide", audit._parse_json_object("nope") is None)

# sans cles API : formulation vide, validation 'unknown', repli heuristique explicite
_old_or, _old_px = audit.OPENROUTER_API_KEY, audit.PERPLEXITY_API_KEY
audit.OPENROUTER_API_KEY = ""
audit.PERPLEXITY_API_KEY = ""
check("formulate_sector sans cle -> []",
      asyncio.run(audit.formulate_sector(sig, "https://brozapi.com", "fr")) == [])
v = asyncio.run(audit.validate_sector("logiciels en ligne", "https://brozapi.com", sig, "fr"))
check("validate_sector sans cle -> unknown", v["status"] == "unknown" and v["hosts"] == [])
d = asyncio.run(audit.detect_sector(h1_slogan, "https://brozapi.com", "fr"))
check("detect_sector repli heuristique explicite",
      d["method"] == "heuristic-fallback" and d["validated"] is None and
      d["keyword"] == "micro-outils", str(d))
audit.OPENROUTER_API_KEY, audit.PERPLEXITY_API_KEY = _old_or, _old_px

# boucle du garde-fou (mocks) : incoherent -> reformulation -> coherent
class _FakeSeq:
    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
    async def __call__(self, sector, domain, signals, lang):
        return self.verdicts.pop(0)

async def _fake_formulate(signals, domain, lang):
    return ["micro-outils", "logiciels en ligne"]

_orig_formulate, _orig_validate = audit.formulate_sector, audit.validate_sector
audit.formulate_sector = _fake_formulate
audit.validate_sector = _FakeSeq([
    {"status": "incoherent", "hosts": ["leroymerlin.fr"], "corrected": "logiciels en ligne pour entrepreneurs"},
    {"status": "coherent", "hosts": ["saas.fr"], "corrected": ""},
])
d2 = asyncio.run(audit.detect_sector(h1_slogan, "https://brozapi.com", "fr"))
check("garde-fou: reformulation puis valide",
      d2["keyword"] == "logiciels en ligne pour entrepreneurs" and
      d2["validated"] is True and d2["attempts"] == 2 and
      d2["method"] == "v4-pro+sonar-guardrail", str(d2))
check("garde-fou: historique conserve", len(d2["history"]) == 2 and
      d2["history"][0]["verdict"] == "incoherent")

audit.validate_sector = _FakeSeq([
    {"status": "incoherent", "hosts": ["a.fr"], "corrected": "x y"},
    {"status": "incoherent", "hosts": ["b.fr"], "corrected": "z w"},
    {"status": "incoherent", "hosts": ["c.fr"], "corrected": ""},
])
d3 = asyncio.run(audit.detect_sector(h1_slogan, "https://brozapi.com", "fr"))
check("garde-fou: max 3 essais puis non valide explicite",
      d3["attempts"] == 3 and d3["validated"] is False and
      d3["method"] == "v4-pro-guardrail-exhausted", str(d3))

audit.validate_sector = _FakeSeq([{"status": "unknown", "hosts": [], "corrected": ""}])
d4 = asyncio.run(audit.detect_sector(h1_slogan, "https://brozapi.com", "fr"))
check("garde-fou indisponible: formulation V4 gardee, marquee non validee",
      d4["keyword"] == "micro-outils" and d4["validated"] is None and
      d4["method"] == "v4-pro-no-guardrail", str(d4))
audit.formulate_sector, audit.validate_sector = _orig_formulate, _orig_validate

# sans cles API, run_paid_audit ne doit jamais planter sur la detection de secteur
_old_or, _old_px = audit.OPENROUTER_API_KEY, audit.PERPLEXITY_API_KEY
audit.OPENROUTER_API_KEY = ""
audit.PERPLEXITY_API_KEY = ""
r = asyncio.run(audit.run_paid_audit("https://inaccessible-zzz.invalid", lang="fr"))
check("run_paid_audit injoignable: secteur explicite",
      r["sector"]["method"] == "no-page-content" and r["keyword"], str(r.get("sector")))
audit.OPENROUTER_API_KEY, audit.PERPLEXITY_API_KEY = _old_or, _old_px

# --- Agent API pipeline (t_b4b6a798) : parsing réponse /v1/agent ---
class _FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload

class _FakeClient:
    """Séquence de réponses + capture du dernier body envoyé."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
    async def post(self, url, json=None, headers=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)

_AGENT_OK = {
    "status": "completed", "model": "perplexity/sonar",
    "output": [
        {"type": "search_results", "queries": ["q1"],
         "results": [{"url": "https://a.fr/x", "title": "A"},
                     {"url": "https://b.fr/y", "title": "B"}]},
        {"type": "message", "role": "assistant", "status": "completed",
         "content": [{"type": "output_text", "text": "Réponse [web:1]",
                      "annotations": [{"url": "https://b.fr/y"},
                                      {"url": "https://c.fr/z"}]}]},
    ],
    "usage": {"cost": {"total_cost": 0.00478}},
}

_fc = _FakeClient([_FakeResp(200, _AGENT_OK)])
audit.PERPLEXITY_API_KEY = "test-key"
res = asyncio.run(audit._agent_query(_fc, "ma requête", lang="fr"))
check("agent-api: ok", res["ok"] is True and res["error"] is None)
check("agent-api: citations = union annotations+search_results, dédupliquées",
      res["citations"] == ["https://a.fr/x", "https://b.fr/y", "https://c.fr/z"],
      str(res["citations"]))
check("agent-api: coût remonté", abs(res["cost"] - 0.00478) < 1e-9)
_sent = _fc.sent[0]
check("agent-api: endpoint /v1/agent", _sent["url"] == audit.PERPLEXITY_AGENT_URL)
check("agent-api: modèle perplexity/sonar",
      _sent["json"]["model"] == "perplexity/sonar")
check("agent-api: grounding web_search activé",
      _sent["json"]["tools"] == [{"type": "web_search"}])
check("agent-api: langue du parcours propagée",
      _sent["json"]["language_preference"] == "fr" and
      "français" in _sent["json"]["instructions"])
check("agent-api: auth bearer",
      _sent["headers"]["Authorization"] == "Bearer test-key")

_fc_err = _FakeClient([_FakeResp(500)])
res_err = asyncio.run(audit._agent_query(_fc_err, "q", retries=0))
check("agent-api: HTTP 500 -> échec explicite",
      res_err["ok"] is False and res_err["citations"] == [] and
      "500" in res_err["error"])

# 429 : retry en honorant Retry-After (sleep neutralisé pour le test)
_sleeps = []
async def _fake_sleep(s):
    _sleeps.append(s)
_orig_sleep = audit.asyncio.sleep
audit.asyncio.sleep = _fake_sleep
try:
    _fc_429 = _FakeClient([_FakeResp(429, headers={"Retry-After": "12"}),
                           _FakeResp(200, _AGENT_OK)])
    res_429 = asyncio.run(audit._agent_query(_fc_429, "q", retries=1))
    check("agent-api: 429 retried puis succès",
          res_429["ok"] is True and len(_fc_429.sent) == 2)
    check("agent-api: Retry-After honoré", _sleeps and _sleeps[0] >= 12.0,
          str(_sleeps))
finally:
    audit.asyncio.sleep = _orig_sleep
audit.PERPLEXITY_API_KEY = ""

print(f"\nUNIT: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
