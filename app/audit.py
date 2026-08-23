"""CiteScan — paid audit pipeline (carte 3.3).

Pipeline:
 1) deep technical audit (robots AI bots, extractability, JSON-LD, E-E-A-T) — 100% local, free
 2) 15 buyer-intent queries to Perplexity Sonar (~$0.15/audit) — citation detection
 3) scoring + prioritized action plan (FR/EN)

Degraded mode without PERPLEXITY_API_KEY: technical audit only, citation section
explicitly marked 'unavailable' — never a silent failure.
"""
import asyncio
import json
import os
import re
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "").strip()
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"
N_QUERIES = 15

AI_BOTS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot",
           "Amazonbot", "Bytespider", "OAI-SearchBot", "ChatGPT-User", "Applebot-Extended"]

# ---------------------------------------------------------------- templates

QUERY_TEMPLATES = {
    "fr": [
        "Quel est le meilleur {kw} pour une petite entreprise ?",
        "Où acheter {kw} en ligne en France ?",
        "{kw} : avis et comparatif {year}",
        "Quels sont les meilleurs sites de {kw} ?",
        "Comment choisir un bon {kw} ?",
        "{kw} pas cher : quelles sont les meilleures options ?",
        "Quel professionnel contacter pour {kw} ?",
        "Top sites recommandés pour {kw}",
        "{kw} : quelles entreprises sont fiables ?",
        "Meilleure alternative pour {kw} en France",
        "Qui sont les leaders du marché de {kw} ?",
        "{kw} : comparatif des prix et services",
        "Où trouver un bon prestataire {kw} ?",
        "Quels sites sont cités comme référence en {kw} ?",
        "Recommandations d'experts pour {kw}",
    ],
    "en": [
        "What is the best {kw} for a small business?",
        "Where can I buy {kw} online?",
        "{kw}: reviews and comparison {year}",
        "What are the best {kw} websites?",
        "How to choose a good {kw}?",
        "Affordable {kw}: what are the best options?",
        "Which professional should I contact for {kw}?",
        "Top recommended sites for {kw}",
        "{kw}: which companies are trustworthy?",
        "Best alternative for {kw}",
        "Who are the market leaders in {kw}?",
        "{kw}: price and service comparison",
        "Where to find a good {kw} provider?",
        "Which sites are cited as references in {kw}?",
        "Expert recommendations for {kw}",
    ],
}

# ---------------------------------------------------------------- technical audit

def _robot_bot_status(robots_text: str, bot: str) -> str:
    """Return 'blocked' / 'allowed' / 'absent' for a bot in robots.txt."""
    lines = [l.strip() for l in robots_text.splitlines()]
    current_agents = []
    bot_seen = False
    blocked = False
    star_blocked = False
    in_star = False
    disallows = []
    star_disallows = []
    for line in lines:
        low = line.lower()
        if low.startswith("user-agent:"):
            agent = low.split(":", 1)[1].strip()
            current_agents = [agent]
            in_star = agent == "*"
            if bot.lower() in agent or agent in bot.lower():
                bot_seen = True
        elif low.startswith("disallow:"):
            val = low.split(":", 1)[1].strip()
            if val == "/":
                if bot.lower() in (current_agents[0] if current_agents else "") or (
                        current_agents and current_agents[0] in bot.lower()):
                    blocked = True
                elif in_star:
                    star_blocked = True
    if blocked:
        return "blocked"
    if star_blocked and not bot_seen:
        return "blocked"
    return "allowed" if bot_seen else "absent"


def technical_audit(html: str, robots_text: "str | None", final_url: str) -> dict:
    """Deep technical audit. Returns checks with points (total 100) + details."""
    soup = BeautifulSoup(html, "html.parser")
    checks = {}

    # 1. robots.txt — AI bots (30 pts)
    if robots_text is None:
        checks["robots"] = {
            "status": "warn", "points": 15,
            "detail": "robots.txt not found — AI bots default to allowed",
            "bots": {},
        }
    else:
        bots = {b: _robot_bot_status(robots_text, b) for b in AI_BOTS}
        blocked = [b for b, s in bots.items() if s == "blocked"]
        if blocked:
            pts = 0 if len(blocked) >= 3 else 10
            status = "fail" if len(blocked) >= 3 else "warn"
            detail = f"robots.txt blocks: {', '.join(blocked)}"
        else:
            pts, status, detail = 30, "pass", "all major AI bots allowed"
        checks["robots"] = {"status": status, "points": pts, "detail": detail, "bots": bots}

    # 2. Extractability (30 pts)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    words = len(text.split())
    headings = len(soup.find_all(["h1", "h2", "h3"]))
    if words >= 300 and headings >= 1:
        checks["extract"] = {"status": "pass", "points": 30,
                             "detail": f"{words} words extractable without JS, {headings} headings"}
    elif words >= 100:
        checks["extract"] = {"status": "warn", "points": 20,
                             "detail": f"only {words} words extractable without JS"}
    else:
        checks["extract"] = {"status": "fail", "points": 5,
                             "detail": f"thin content ({words} words) — likely requires JS rendering"}

    # 3. JSON-LD (20 pts) — parsed BEFORE script decompose below
    soup_raw = BeautifulSoup(html, "html.parser")
    jsonld_types = []
    jsonld_valid = 0
    jsonld_invalid = 0
    for s in soup_raw.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
            items = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and "@graph" in data:
                items = data["@graph"]
            for item in items:
                if isinstance(item, dict) and "@type" in item:
                    t = item["@type"]
                    jsonld_types.extend(t if isinstance(t, list) else [t])
            jsonld_valid += 1
        except json.JSONDecodeError:
            jsonld_invalid += 1
    if jsonld_valid:
        types_str = ", ".join(sorted(set(jsonld_types))) or "untyped"
        checks["jsonld"] = {"status": "pass", "points": 20,
                            "detail": f"valid JSON-LD: {types_str}",
                            "types": sorted(set(jsonld_types))}
    elif jsonld_invalid:
        checks["jsonld"] = {"status": "fail", "points": 5,
                            "detail": "JSON-LD present but invalid (parse error)"}
    else:
        checks["jsonld"] = {"status": "warn", "points": 5, "detail": "no JSON-LD structured data"}

    # 4. E-E-A-T (20 pts)
    signals, missing = [], []
    soup2 = BeautifulSoup(html, "html.parser")
    if soup2.find("a", href=lambda h: h and any(k in h.lower() for k in
                  ("about", "apropos", "a-propos", "mentions", "legal", "qui-sommes"))):
        signals.append("about/legal page")
    else:
        missing.append("no about/legal page")
    if soup2.find("time") or re.search(r"\b(20[12]\d)[/-]", html):
        signals.append("dates present")
    else:
        missing.append("no publication dates")
    if soup2.find("meta", attrs={"name": "author"}) or re.search(r'"author"', html):
        signals.append("identified author")
    else:
        missing.append("no identified author")
    https_ok = final_url.startswith("https")
    if not https_ok:
        missing.append("no HTTPS")
    if signals and https_ok:
        pts, status = 20, "pass"
    elif https_ok:
        pts, status = 10, "warn"
    else:
        pts, status = 0, "fail"
    checks["eeat"] = {"status": status, "points": pts,
                      "detail": "; ".join(signals + missing) or "HTTPS only",
                      "signals": signals, "missing": missing}

    total = sum(c["points"] for c in checks.values())
    return {"score": min(total, 100), "checks": checks, "word_count": words}


# ---------------------------------------------------------------- keyword + queries

def extract_keyword(html: str, domain: str) -> str:
    """Best-effort sector/offer keyword from H1 or title.

    Prefers H1 (cleaner), skips generic one/two-word openers, avoids
    stopping at internal dashes when the remainder is meaningful.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = (soup.title.string if soup.title and soup.title.string else "").strip()
    src = (h1.get_text(strip=True) if h1 else "") or title or domain
    # split on strong separators only; keep internal hyphens (e.g. "micro-SaaS")
    src = re.split(r"[|–—·:]", src)[0].strip()
    words = [w for w in re.split(r"\s+", src) if len(w) > 2]
    # drop leading generic words that pollute queries ("Des micro" etc.)
    GENERIC = {"des", "les", "the", "vos", "votre", "your", "pour", "and"}
    while words and words[0].lower().rstrip("-").lower() in GENERIC:
        words.pop(0)
    # cut at the first connector/tail word — everything after it is slogan,
    # not sector ("micro-outils à partir de 39 EUR pour..." -> "micro-outils")
    STOP = {"partir", "pour", "par", "dans", "sur", "avec", "qui", "que",
            "from", "for", "with", "that", "your", "votre", "vos", "notre"}
    cut = next((i for i, w in enumerate(words) if w.lower().strip("-").lower() in STOP),
               len(words))
    words = words[:max(cut, 1)][:5]
    kw = " ".join(words).strip(" .,:;!")
    # avoid useless short fragments like "Des micro" — require >= 8 chars
    if len(kw) < 8 and title:
        alt = re.split(r"[|–—·:]", title)[0].strip()
        aw = [w for w in re.split(r"\s+", alt) if len(w) > 2][:6]
        while aw and aw[0].lower().rstrip("-").lower() in GENERIC:
            aw.pop(0)
        acut = next((i for i, w in enumerate(aw) if w.lower().strip("-").lower() in STOP),
                    len(aw))
        kw = " ".join(aw[:max(acut, 1)][:5]).strip(" .,:;!") or kw
    return kw[:80] or "this type of business"


def build_queries(keyword: str, lang: str) -> list:
    year = time.strftime("%Y")
    lang = lang if lang in QUERY_TEMPLATES else "en"
    return [t.format(kw=keyword, year=year) for t in QUERY_TEMPLATES[lang]][:N_QUERIES]


# ---------------------------------------------------------------- perplexity

async def _sonar_query(client: httpx.AsyncClient, query: str, retries: int = 3) -> dict:
    """One Perplexity Sonar call with 429 retry/backoff."""
    delay = 8.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(PERPLEXITY_URL, json={
                "model": PERPLEXITY_MODEL,
                "messages": [{"role": "user", "content": query}],
                "search_context_size": "low",
                "return_citations": True,
            }, headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"query": query, "ok": False, "citations": [],
                        "error": f"HTTP {r.status_code}"}
            data = r.json()
            return {"query": query, "ok": True, "citations": data.get("citations", []) or [],
                    "error": None}
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"query": query, "ok": False, "citations": [], "error": str(e)[:200]}


def _host_of(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


async def citation_audit(domain: str, keyword: str, lang: str) -> dict:
    """15 Sonar queries; per query: client cited? competitors cited?"""
    if not PERPLEXITY_API_KEY:
        return {"status": "unavailable",
                "reason": "PERPLEXITY_API_KEY not set — degraded mode (technical audit only)",
                "queries": [], "cited_count": 0, "total": 0, "competitors": []}

    queries = build_queries(keyword, lang)
    target = _host_of(domain)
    timeout = httpx.Timeout(45.0)
    # sequential calls (small pause) to stay under Sonar RPM limits; gather() fired
    # 15 concurrent requests and reliably triggered HTTP 429 on 10+ queries.
    results = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for q in queries:
            results.append(await _sonar_query(client, q))
            await asyncio.sleep(1.5)

    per_query = []
    cited_count = 0
    ok_count = 0
    comp_counter = {}
    for res in results:
        if not res["ok"]:
            per_query.append({"query": res["query"], "cited": False,
                              "error": res["error"], "citations": []})
            continue
        ok_count += 1
        hosts = [_host_of(c) for c in res["citations"]]
        cited = any(target and target == h for h in hosts)
        if cited:
            cited_count += 1
        comps = sorted({h for h in hosts if h and h != target})
        for h in comps:
            comp_counter[h] = comp_counter.get(h, 0) + 1
        per_query.append({"query": res["query"], "cited": cited,
                          "error": None, "citations": comps[:5]})

    competitors = [{"domain": d, "count": c} for d, c in
                   sorted(comp_counter.items(), key=lambda x: -x[1])][:10]
    status = "ok" if ok_count == len(queries) else ("partial" if ok_count else "failed")
    return {"status": status, "queries_ok": ok_count, "total": len(queries),
            "cited_count": cited_count, "queries": per_query,
            "competitors": competitors}


# ---------------------------------------------------------------- scoring + action plan

def compute_score(technical: dict, citations: dict) -> dict:
    """Technical 40% + citations 60% (when available)."""
    tech_score = technical["score"]  # /100
    if citations.get("status") in ("ok", "partial") and citations.get("total"):
        cite_score = round(100 * citations["cited_count"] / citations["total"])
        total = round(0.4 * tech_score + 0.6 * cite_score)
        return {"total": total, "technical": tech_score, "citation": cite_score,
                "mode": "full"}
    return {"total": tech_score, "technical": tech_score, "citation": None,
            "mode": "degraded"}


ACTION_LIBRARY = {
    "robots_blocked": {
        "impact": 10, "effort": 1,
        "fr": "Débloquer les bots IA dans robots.txt (GPTBot, ClaudeBot, PerplexityBot) : retirer les règles 'Disallow: /' qui les ciblent.",
        "en": "Unblock AI bots in robots.txt (GPTBot, ClaudeBot, PerplexityBot): remove the 'Disallow: /' rules targeting them.",
    },
    "no_jsonld": {
        "impact": 8, "effort": 3,
        "fr": "Ajouter des données structurées JSON-LD (Organization + FAQ + Product/Service) sur les pages clés.",
        "en": "Add JSON-LD structured data (Organization + FAQ + Product/Service) on key pages.",
    },
    "thin_content": {
        "impact": 8, "effort": 6,
        "fr": "Épaissir le contenu textuel accessible sans JavaScript : les IA citent les pages riches en texte extractible.",
        "en": "Thicken text content accessible without JavaScript: AIs cite pages rich in extractable text.",
    },
    "no_about": {
        "impact": 6, "effort": 2,
        "fr": "Créer/renforcer une page À propos avec auteur identifié et mentions légales (signaux E-E-A-T).",
        "en": "Create/strengthen an About page with an identified author and legal notices (E-E-A-T signals).",
    },
    "no_dates": {
        "impact": 5, "effort": 2,
        "fr": "Afficher des dates de publication/mise à jour visibles (balises <time> ou JSON-LD datePublished).",
        "en": "Show visible publication/update dates (<time> tags or JSON-LD datePublished).",
    },
    "not_cited": {
        "impact": 10, "effort": 7,
        "fr": "Le site n'est cité sur aucune requête : créer du contenu de référence (guides, comparatifs, FAQ) qui cite des sources reconnues, puis le faire référencer par des sites déjà cités par les IA.",
        "en": "Site cited on no query: create reference content (guides, comparisons, FAQ) citing recognized sources, then get referenced by sites already cited by AIs.",
    },
    "competitors_cited": {
        "impact": 9, "effort": 5,
        "fr": "Des concurrents sont cités à votre place : analyser leurs pages citées et produire un contenu plus complet et plus factuel sur les mêmes sujets.",
        "en": "Competitors are cited instead of you: analyze their cited pages and produce more comprehensive, factual content on the same topics.",
    },
    "partially_cited": {
        "impact": 6, "effort": 4,
        "fr": "Le site est cité sur certaines requêtes seulement : renforcer les pages proches des requêtes non citées.",
        "en": "Site cited on some queries only: strengthen pages close to the non-cited queries.",
    },
}


def build_action_plan(technical: dict, citations: dict, lang: str) -> list:
    lang = lang if lang in ("fr", "en") else "en"
    actions = []
    checks = technical["checks"]

    if checks["robots"]["status"] == "fail":
        actions.append("robots_blocked")
    if checks["jsonld"]["points"] < 20:
        actions.append("no_jsonld")
    if checks["extract"]["points"] < 30:
        actions.append("thin_content")
    eeat_missing = " ".join(checks["eeat"].get("missing", []))
    if "about" in eeat_missing:
        actions.append("no_about")
    if "dates" in eeat_missing:
        actions.append("no_dates")

    if citations.get("status") in ("ok", "partial"):
        cited = citations["cited_count"]
        total = citations["total"]
        if cited == 0:
            actions.append("not_cited")
            if citations.get("competitors"):
                actions.append("competitors_cited")
        elif cited < total / 2:
            actions.append("partially_cited")
            if citations.get("competitors"):
                actions.append("competitors_cited")

    plan = []
    for key in actions:
        a = ACTION_LIBRARY[key]
        plan.append({"action": a[lang], "impact": a["impact"], "effort": a["effort"],
                     "priority_score": round(a["impact"] / max(a["effort"], 1), 1)})
    plan.sort(key=lambda x: -x["priority_score"])
    for i, item in enumerate(plan, 1):
        item["rank"] = i
    return plan[:10]


# ---------------------------------------------------------------- orchestration

async def run_paid_audit(url: str, lang: str = "en") -> dict:
    """Full paid-audit pipeline. Never raises; degraded sections are explicit."""
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    domain = f"https://{parsed.netloc.lower()}"

    timeout = httpx.Timeout(15.0)
    html, robots_text, final_url = "", None, domain
    fetch_error = None
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout,
                                 headers={"User-Agent": "CiteScan-Audit/1.0"}) as client:
        try:
            r = await client.get(domain)
            html, final_url = r.text, str(r.url)
        except Exception as e:
            fetch_error = str(e)[:200]
        try:
            rr = await client.get(f"{domain}/robots.txt")
            if rr.status_code == 200:
                robots_text = rr.text
        except Exception:
            pass

    if fetch_error:
        technical = {"score": 0, "word_count": 0, "checks": {},
                     "error": f"site unreachable: {fetch_error}"}
    else:
        technical = technical_audit(html, robots_text, final_url)

    keyword = extract_keyword(html, domain) if html else domain
    citations = await citation_audit(domain, keyword, lang)
    score = compute_score(technical, citations)
    plan = build_action_plan(technical, citations, lang) if not fetch_error else []

    return {
        "domain": domain,
        "lang": lang,
        "keyword": keyword,
        "score": score,
        "technical": technical,
        "citations": citations,
        "action_plan": plan,
        "mode": score["mode"],
        "perplexity_available": bool(PERPLEXITY_API_KEY),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
