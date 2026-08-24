"""CiteScan — paid audit pipeline (carte 3.3).

Pipeline:
 1) deep technical audit (robots AI bots, extractability, JSON-LD, E-E-A-T) — 100% local, free
 2) 15 buyer-intent queries to Perplexity Agent API (model perplexity/sonar +
    web_search, ~$0.08/audit mesuré) — citation detection
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
# Migration 2026-08-24 (t_b4b6a798) : Sonar Chat Completions est coupé le
# 27/09/2026 -> Agent API (POST /v1/agent). Le modèle perplexity/sonar reste
# le moteur, avec grounding web explicite via l'outil web_search (indispensable :
# on mesure les CITATIONS). Coût mesuré en smoke test : ~0,005 $/requête
# (soit ~0,08 $/audit de 15 requêtes + garde-fou), sous le seuil de 0,30 $.
PERPLEXITY_AGENT_URL = "https://api.perplexity.ai/v1/agent"
PERPLEXITY_AGENT_MODEL = "perplexity/sonar"
N_QUERIES = 15

# Rédaction du rapport client : V4 pro via OpenRouter (exigence Franck 2026-08-24).
# Sonar reste le moteur d'audit (données brutes) ; V4 pro rédige la synthèse et
# le plan d'action livrés au client, dans la langue du parcours.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
WRITER_MODEL = "deepseek/deepseek-v4-pro-0813"

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

# Localized human-readable strings for the paid report (carte recette 2026-08-24:
# details used to be English-only, so FR reports came out FR/EN mixed).
_TXT = {
    "fr": {
        "robots_missing": "robots.txt introuvable — les bots IA sont autorisés par défaut",
        "robots_blocked": "robots.txt bloque : {bots}",
        "robots_ok": "tous les principaux bots IA sont autorisés",
        "extract_pass": "contenu textuel lisible par les IA — quantité suffisante pour être cité",
        "extract_warn": "contenu textuel un peu mince : étoffez le texte visible sans JavaScript pour maximiser vos chances d'être cité",
        "extract_fail": "contenu trop mince — la page semble dépendre de JavaScript ; les IA risquent de ne pas pouvoir lire votre offre",
        "jsonld_pass": "JSON-LD valide : {types}",
        "jsonld_untyped": "sans type",
        "jsonld_invalid": "JSON-LD présent mais invalide (erreur d'analyse)",
        "jsonld_missing": "aucune donnée structurée JSON-LD",
        "sig_about": "page à propos / mentions légales",
        "sig_dates": "dates de publication présentes",
        "sig_author": "auteur identifié",
        "miss_about": "pas de page à propos / mentions légales",
        "miss_dates": "pas de dates de publication",
        "miss_author": "pas d'auteur identifié",
        "miss_https": "pas de HTTPS",
        "eeat_https_only": "HTTPS uniquement",
        "site_unreachable": "site inaccessible : {err}",
    },
    "en": {
        "robots_missing": "robots.txt not found — AI bots default to allowed",
        "robots_blocked": "robots.txt blocks: {bots}",
        "robots_ok": "all major AI bots allowed",
        "extract_pass": "text content readable by AIs — sufficient volume to be cited",
        "extract_warn": "text content is on the thin side: expand the text visible without JavaScript to maximize your chances of being cited",
        "extract_fail": "content too thin — the page seems to depend on JavaScript; AIs may be unable to read your offer",
        "jsonld_pass": "valid JSON-LD: {types}",
        "jsonld_untyped": "untyped",
        "jsonld_invalid": "JSON-LD present but invalid (parse error)",
        "jsonld_missing": "no JSON-LD structured data",
        "sig_about": "about/legal page",
        "sig_dates": "dates present",
        "sig_author": "identified author",
        "miss_about": "no about/legal page",
        "miss_dates": "no publication dates",
        "miss_author": "no identified author",
        "miss_https": "no HTTPS",
        "eeat_https_only": "HTTPS only",
        "site_unreachable": "site unreachable: {err}",
    },
}


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


def technical_audit(html: str, robots_text: "str | None", final_url: str,
                    lang: str = "en") -> dict:
    """Deep technical audit. Returns checks with points (total 100) + details
    in the journey language. Machine codes (signal_codes/missing_codes) are
    kept alongside so scoring logic never depends on wording."""
    T = _TXT[lang if lang in _TXT else "en"]
    soup = BeautifulSoup(html, "html.parser")
    checks = {}

    # 1. robots.txt — AI bots (30 pts)
    if robots_text is None:
        checks["robots"] = {
            "status": "warn", "points": 15,
            "detail": T["robots_missing"],
            "bots": {},
        }
    else:
        bots = {b: _robot_bot_status(robots_text, b) for b in AI_BOTS}
        blocked = [b for b, s in bots.items() if s == "blocked"]
        if blocked:
            pts = 0 if len(blocked) >= 3 else 10
            status = "fail" if len(blocked) >= 3 else "warn"
            detail = T["robots_blocked"].format(bots=", ".join(blocked))
        else:
            pts, status, detail = 30, "pass", T["robots_ok"]
        checks["robots"] = {"status": status, "points": pts, "detail": detail, "bots": bots}

    # 2. Extractability (30 pts)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    words = len(text.split())
    headings = len(soup.find_all(["h1", "h2", "h3"]))
    if words >= 300 and headings >= 1:
        checks["extract"] = {"status": "pass", "points": 30, "detail": T["extract_pass"]}
    elif words >= 100:
        checks["extract"] = {"status": "warn", "points": 20, "detail": T["extract_warn"]}
    else:
        checks["extract"] = {"status": "fail", "points": 5, "detail": T["extract_fail"]}

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
        types_str = ", ".join(sorted(set(jsonld_types))) or T["jsonld_untyped"]
        checks["jsonld"] = {"status": "pass", "points": 20,
                            "detail": T["jsonld_pass"].format(types=types_str),
                            "types": sorted(set(jsonld_types))}
    elif jsonld_invalid:
        checks["jsonld"] = {"status": "fail", "points": 5,
                            "detail": T["jsonld_invalid"]}
    else:
        checks["jsonld"] = {"status": "warn", "points": 5, "detail": T["jsonld_missing"]}

    # 4. E-E-A-T (20 pts)
    signals, missing = [], []
    signal_codes, missing_codes = [], []
    soup2 = BeautifulSoup(html, "html.parser")
    if soup2.find("a", href=lambda h: h and any(k in h.lower() for k in
                  ("about", "apropos", "a-propos", "mentions", "legal", "qui-sommes"))):
        signals.append(T["sig_about"]); signal_codes.append("about")
    else:
        missing.append(T["miss_about"]); missing_codes.append("about")
    if soup2.find("time") or re.search(r"\b(20[12]\d)[/-]", html):
        signals.append(T["sig_dates"]); signal_codes.append("dates")
    else:
        missing.append(T["miss_dates"]); missing_codes.append("dates")
    if soup2.find("meta", attrs={"name": "author"}) or re.search(r'"author"', html):
        signals.append(T["sig_author"]); signal_codes.append("author")
    else:
        missing.append(T["miss_author"]); missing_codes.append("author")
    https_ok = final_url.startswith("https")
    if not https_ok:
        missing.append(T["miss_https"]); missing_codes.append("https")
    if signals and https_ok:
        pts, status = 20, "pass"
    elif https_ok:
        pts, status = 10, "warn"
    else:
        pts, status = 0, "fail"
    checks["eeat"] = {"status": status, "points": pts,
                      "detail": "; ".join(signals + missing) or T["eeat_https_only"],
                      "signals": signals, "missing": missing,
                      "signal_codes": signal_codes, "missing_codes": missing_codes}

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

# Force the answer language (carte recette 2026-08-24: Sonar answered in
# English whatever the journey language, polluting FR reports/citations).
_SONAR_SYSTEM = {
    "fr": "Tu es un assistant de recherche francophone. Réponds exclusivement en "
          "français, de façon factuelle et concise, et privilégie les sources "
          "francophones pertinentes.",
    "en": "You are an English-speaking research assistant. Answer exclusively in "
          "English, factually and concisely, and prefer relevant English-language "
          "sources.",
}


async def _agent_query(client: httpx.AsyncClient, query: str, retries: int = 3,
                       lang: str = "en") -> dict:
    """One Perplexity Agent API call (model perplexity/sonar + web_search) with
    429 retry/backoff (Retry-After honored). Citations = union of the URLs
    cited in the answer annotations and the retrieved search_results sources —
    the answer text itself is not used by the audit pipeline.
    Note: structured output (JSON schema) was evaluated and intentionally NOT
    applied here — citation extraction reads verifiable URLs from
    annotations/search_results, never model-generated text, so a schema would
    only add failure modes without changing the client-facing output."""
    system = _SONAR_SYSTEM.get(lang, _SONAR_SYSTEM["en"])
    delay = 8.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(PERPLEXITY_AGENT_URL, json={
                "model": PERPLEXITY_AGENT_MODEL,
                "input": query,
                "instructions": system,
                "language_preference": lang,
                "tools": [{"type": "web_search"}],
                "max_output_tokens": 1024,
            }, headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                retry_after = r.headers.get("Retry-After")
                wait = delay
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"query": query, "ok": False, "citations": [],
                        "cost": 0.0, "error": f"HTTP {r.status_code}"}
            data = r.json()
            urls = []
            for item in data.get("output", []) or []:
                itype = item.get("type")
                if itype == "search_results":
                    urls += [x.get("url") for x in item.get("results", []) or []
                             if x.get("url")]
                elif itype == "message":
                    for part in item.get("content", []) or []:
                        for ann in part.get("annotations", []) or []:
                            if ann.get("url"):
                                urls.append(ann["url"])
            cost = ((data.get("usage") or {}).get("cost") or {}).get("total_cost") or 0.0
            return {"query": query, "ok": True,
                    "citations": list(dict.fromkeys(urls)),
                    "cost": float(cost), "error": None}
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"query": query, "ok": False, "citations": [],
                    "cost": 0.0, "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# FALLBACK Sonar Chat Completions — CONSERVÉ jusqu'au 27/09/2026 au cas où
# (ancien pipeline, coupé par Perplexity après cette date). Pour réactiver en
# urgence : renommer _sonar_query_legacy -> _agent_query ne suffit PAS (forme
# de réponse différente) ; décommenter ce bloc et le renommer _agent_query.
#
# PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
# PERPLEXITY_MODEL = "sonar"
#
# async def _sonar_query_legacy(client, query, retries=3, lang="en"):
#     system = _SONAR_SYSTEM.get(lang, _SONAR_SYSTEM["en"])
#     delay = 8.0
#     for attempt in range(retries + 1):
#         try:
#             r = await client.post(PERPLEXITY_URL, json={
#                 "model": PERPLEXITY_MODEL,
#                 "messages": [{"role": "system", "content": system},
#                              {"role": "user", "content": query}],
#                 "search_context_size": "low",
#                 "return_citations": True,
#             }, headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}",
#                         "Content-Type": "application/json"})
#             if r.status_code == 429 and attempt < retries:
#                 await asyncio.sleep(delay)
#                 delay *= 2
#                 continue
#             if r.status_code != 200:
#                 return {"query": query, "ok": False, "citations": [],
#                         "cost": 0.0, "error": f"HTTP {r.status_code}"}
#             data = r.json()
#             return {"query": query, "ok": True,
#                     "citations": data.get("citations", []) or [],
#                     "cost": 0.0, "error": None}
#         except Exception as e:
#             if attempt < retries:
#                 await asyncio.sleep(delay)
#                 delay *= 2
#                 continue
#             return {"query": query, "ok": False, "citations": [],
#                     "cost": 0.0, "error": str(e)[:200]}


def _host_of(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


async def citation_audit(domain: str, keyword: str, lang: str) -> dict:
    """15 Sonar queries; per query: client cited? competitors cited?"""
    if not PERPLEXITY_API_KEY:
        reason = ("PERPLEXITY_API_KEY non définie — mode dégradé (audit technique seul)"
                  if lang == "fr" else
                  "PERPLEXITY_API_KEY not set — degraded mode (technical audit only)")
        return {"status": "unavailable", "reason": reason,
                "queries": [], "cited_count": 0, "total": 0, "competitors": []}

    queries = build_queries(keyword, lang)
    target = _host_of(domain)
    timeout = httpx.Timeout(45.0)
    # sequential calls (small pause) to stay under Perplexity RPM limits;
    # gather() fired 15 concurrent requests and reliably triggered HTTP 429.
    results = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for q in queries:
            results.append(await _agent_query(client, q, lang=lang))
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
    cost_usd = round(sum(r.get("cost", 0.0) for r in results), 5)
    return {"status": status, "queries_ok": ok_count, "total": len(queries),
            "cited_count": cited_count, "queries": per_query,
            "competitors": competitors, "cost_usd": cost_usd,
            "engine": "agent-api:perplexity/sonar"}


# ---------------------------------------------------------------- sector detection (V4 pro + Sonar guardrail)
#
# Recette 2026-08-24 (t_ffc46988) : l'heuristique H1 détectait « micro-outils »
# pour brozapi.com (un studio de LOGICIELS) -> les 15 requêtes Sonar parlaient
# bricolage (Leroy Merlin, Bosch, Dremel) et toute la mesure était fausse.
# Désormais :
#   (a) V4 pro formule le secteur à partir du contenu réel de la page, en
#       termes NON AMBIGUS qui s'insèrent dans les gabarits de requêtes ;
#   (b) garde-fou de cohérence : 1 requête Sonar de validation AVANT les 15,
#       V4 pro juge si les domaines cités sont dans le même secteur que le
#       site ; sinon reformulation et nouveau test (max 3 essais) ;
#   (c) le rapport affiche la formulation validée (champ "keyword").

_SECTOR_USER = {
    "fr": """Voici le contenu de la page d'accueil du site {domain} :
Titre : {title}
H1 : {h1}
Meta description : {desc}
Données structurées : {jsonld}
Extrait du texte visible : {text}

Formule le secteur d'activité EXACT de ce site en 3 à 6 mots, en français, de façon NON AMBIGUË :
- jamais un terme polysémique nu : « micro-outils » évoque le bricolage, « solutions » ne veut rien dire ;
  si le site vend des logiciels, dis « logiciels en ligne … » ou « micro-SaaS … », jamais « outils » seul ;
- la formulation doit s'insérer naturellement dans des questions d'intention d'achat comme
  « Quel est le meilleur X pour une petite entreprise ? » ou « Où acheter X en ligne ? » ;
- utilise les termes qu'un acheteur taperait réellement dans un moteur de recherche.
JSON attendu : {{"secteur": "...", "alternatives": ["...", "..."]}}""",
    "en": """Here is the homepage content of the site {domain}:
Title: {title}
H1: {h1}
Meta description: {desc}
Structured data: {jsonld}
Visible text excerpt: {text}

Formulate this site's EXACT business sector in 3 to 6 words, in English, UNAMBIGUOUSLY:
- never a bare polysemous term: "micro-tools" suggests DIY hardware, "solutions" means nothing;
  if the site sells software, say "online software …" or "micro-SaaS …", never "tools" alone;
- the phrasing must fit naturally inside buyer-intent questions like
  "What is the best X for a small business?" or "Where can I buy X online?";
- use the terms a real buyer would type into a search engine.
Expected JSON: {{"secteur": "...", "alternatives": ["...", "..."]}}""",
}

_SECTOR_CHECK_USER = {
    "fr": """Le site {domain} se présente ainsi : {summary}
Secteur candidat : « {sector} ».
En interrogeant un moteur de recherche IA sur ce secteur, les domaines cités sont : {hosts}

Ces domaines sont-ils majoritairement des entreprises du MÊME secteur que le site —
et non d'un secteur homonyme (ex. bricolage/outillage pour un éditeur de logiciels) ?
Ignore les médias généralistes, encyclopédies et réseaux sociaux dans ton jugement.
JSON attendu : {{"coherent": true ou false, "secteur_corrige": "meilleure formulation si incohérent, sinon chaîne vide"}}""",
    "en": """The site {domain} describes itself as: {summary}
Candidate sector: "{sector}".
When querying an AI search engine about this sector, the cited domains are: {hosts}

Are these domains mostly businesses in the SAME sector as the site — and not a
namesake sector (e.g. DIY/hardware for a software publisher)?
Ignore generalist media, encyclopedias and social networks in your judgment.
Expected JSON: {{"coherent": true or false, "secteur_corrige": "better phrasing if incoherent, else empty string"}}""",
}

_SECTOR_VALIDATION_QUERY = {
    "fr": "Quels sont les sites et entreprises de référence dans le secteur suivant : {sector} ?",
    "en": "Which sites and companies are leading references in the following sector: {sector}?",
}


def extract_page_signals(html: str) -> dict:
    """Title, H1, meta description, JSON-LD types and a visible-text excerpt —
    the factual basis V4 pro uses to formulate the sector."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    h1 = "; ".join(h.get_text(" ", strip=True) for h in soup.find_all("h1")[:3])
    desc_tag = soup.find("meta", attrs={"name": "description"}) or \
        soup.find("meta", attrs={"property": "og:description"})
    desc = (desc_tag.get("content") or "").strip() if desc_tag else ""
    types = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
            items = data.get("@graph", data) if isinstance(data, dict) else data
            for item in (items if isinstance(items, list) else [items]):
                if isinstance(item, dict) and "@type" in item:
                    t = item["@type"]
                    types.extend(t if isinstance(t, list) else [t])
        except (json.JSONDecodeError, AttributeError):
            continue
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)[:800]
    return {"title": title[:200], "h1": h1[:200], "desc": desc[:300],
            "jsonld": ", ".join(sorted(set(types)))[:200], "text": text}


def _signals_summary(signals: dict) -> str:
    return (f"titre « {signals.get('title', '')} », H1 « {signals.get('h1', '')} », "
            f"description « {signals.get('desc', '')} »")


def _parse_json_object(raw: str) -> "dict | None":
    """Tolerant JSON object extraction from an LLM answer."""
    try:
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            if txt.startswith("json"):
                txt = txt[4:]
        start, end = txt.find("{"), txt.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(txt[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _clean_sector(value: str) -> str:
    """Normalize a sector phrasing; '' if unusable."""
    s = re.sub(r"\s+", " ", (value or "").strip().strip("«»\"' .,:;!"))
    words = s.split()
    if not (2 <= len(words) <= 8) or len(s) > 80:
        return ""
    return s


async def _openrouter_json(system: str, user: str, max_tokens: int = 2500) -> "dict | None":
    """One OpenRouter call expecting a JSON object back. None on any failure.

    deepseek-v4-pro est un modèle à raisonnement : sans 'reasoning.exclude' il
    peut brûler tout le budget de tokens en raisonnement interne et renvoyer
    content=null (finish_reason='length') — constaté en prod le 2026-08-24 avec
    max_tokens=400. D'où exclude + budget large + garde sur content vide."""
    if not OPENROUTER_API_KEY:
        return None
    timeout = httpx.Timeout(60.0)
    for _ in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(OPENROUTER_URL, json={
                    "model": WRITER_MODEL,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    "reasoning": {"exclude": True},
                }, headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://citescan.brozapi.com",
                            "X-Title": "CiteScan sector detection"})
            if r.status_code != 200:
                continue
            content = r.json()["choices"][0]["message"].get("content")
            if not content:
                continue
            parsed = _parse_json_object(content)
            if parsed is not None:
                return parsed
        except Exception:
            continue
    return None


async def formulate_sector(signals: dict, domain: str, lang: str) -> "list[str]":
    """V4 pro formulates the sector from real page content. Returns an ordered
    candidate list (main phrasing first, then alternatives); [] if unavailable."""
    lang = lang if lang in _SECTOR_USER else "en"
    user = _SECTOR_USER[lang].format(
        domain=domain, title=signals.get("title", ""), h1=signals.get("h1", ""),
        desc=signals.get("desc", ""), jsonld=signals.get("jsonld") or "-",
        text=signals.get("text", ""))
    data = await _openrouter_json(_WRITER_SYSTEM[lang], user)
    if not data:
        return []
    candidates = []
    main = _clean_sector(str(data.get("secteur", "")))
    if main:
        candidates.append(main)
    for alt in (data.get("alternatives") or [])[:3]:
        alt = _clean_sector(str(alt))
        if alt and alt.lower() != main.lower() and alt not in candidates:
            candidates.append(alt)
    return candidates


async def validate_sector(sector: str, domain: str, signals: dict, lang: str) -> dict:
    """Garde-fou de cohérence : 1 requête Sonar sur le secteur candidat, puis
    V4 pro juge si les domaines cités appartiennent au même secteur que le site.
    status: 'coherent' | 'incoherent' | 'unknown' (Sonar/OpenRouter indisponible)."""
    lang = lang if lang in _SECTOR_VALIDATION_QUERY else "en"
    result = {"status": "unknown", "hosts": [], "corrected": ""}
    if not PERPLEXITY_API_KEY or not OPENROUTER_API_KEY:
        return result
    query = _SECTOR_VALIDATION_QUERY[lang].format(sector=sector)
    timeout = httpx.Timeout(45.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await _agent_query(client, query, lang=lang)
    if not res["ok"]:
        return result
    hosts = sorted({h for h in (_host_of(c) for c in res["citations"]) if h})[:12]
    if not hosts:
        return result
    result["hosts"] = hosts
    user = _SECTOR_CHECK_USER[lang].format(
        domain=domain, summary=_signals_summary(signals), sector=sector,
        hosts=", ".join(hosts))
    data = await _openrouter_json(_WRITER_SYSTEM[lang], user)
    if data is None or "coherent" not in data:
        return result
    result["status"] = "coherent" if data.get("coherent") else "incoherent"
    result["corrected"] = _clean_sector(str(data.get("secteur_corrige", "")))
    return result


async def detect_sector(html: str, domain: str, lang: str,
                        max_attempts: int = 3) -> dict:
    """Secteur précis et validé pour l'audit. Ne lève jamais d'exception :
    repli sur l'heuristique historique si V4 pro est indisponible, avec un
    champ 'method' explicite dans le JSON d'audit."""
    signals = extract_page_signals(html)
    candidates = await formulate_sector(signals, domain, lang)
    history = []
    if not candidates:
        return {"keyword": extract_keyword(html, domain),
                "validated": None, "attempts": 0, "method": "heuristic-fallback",
                "history": []}
    queue = list(candidates)
    current = queue.pop(0)
    for attempt in range(1, max_attempts + 1):
        verdict = await validate_sector(current, domain, signals, lang)
        history.append({"sector": current, "verdict": verdict["status"],
                        "hosts": verdict["hosts"]})
        if verdict["status"] == "coherent":
            return {"keyword": current, "validated": True, "attempts": attempt,
                    "method": "v4-pro+sonar-guardrail", "history": history}
        if verdict["status"] == "incoherent":
            nxt = verdict["corrected"] or (queue.pop(0) if queue else "")
            if not nxt:
                break
            current = nxt
            continue
        # 'unknown' : impossible de trancher (API indisponible) — on garde la
        # formulation V4 pro, marquée comme non validée.
        return {"keyword": current, "validated": None, "attempts": attempt,
                "method": "v4-pro-no-guardrail", "history": history}
    # Essais épuisés sans cohérence : on conserve la dernière formulation
    # (jugée la moins mauvaise) mais marquée non validée — jamais en silence.
    return {"keyword": current, "validated": False, "attempts": max_attempts,
            "method": "v4-pro-guardrail-exhausted", "history": history}


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
        "fr": "Débloquer les bots IA dans robots.txt (GPTBot, ClaudeBot, PerplexityBot) : retirer les règles « Disallow: / » qui les ciblent, puis vérifier avec un fetch de test. Action de 10 minutes, effet immédiat sur la lisibilité par les IA.",
        "en": "Unblock AI bots in robots.txt (GPTBot, ClaudeBot, PerplexityBot): remove the 'Disallow: /' rules targeting them, then verify with a test fetch. A 10-minute fix with immediate effect on AI readability.",
    },
    "no_jsonld": {
        "impact": 8, "effort": 3,
        "fr": "Ajouter des données structurées JSON-LD sur la page d'accueil et les pages clés : types Organization (nom, logo, contact), FAQPage si vous avez une FAQ, Product/Service avec prix. Valider ensuite avec l'outil « Test des résultats enrichis » de Google.",
        "en": "Add JSON-LD structured data on the homepage and key pages: Organization (name, logo, contact), FAQPage if you have a FAQ, Product/Service with pricing. Then validate with Google's Rich Results Test.",
    },
    "thin_content": {
        "impact": 8, "effort": 6,
        "fr": "Épaissir le contenu textuel lisible sans JavaScript (viser 300+ mots par page clé) : les IA citent les pages dont le texte est extractible directement. Déplacer les contenus essentiels hors des composants rendus côté client.",
        "en": "Thicken text content readable without JavaScript (target 300+ words per key page): AIs cite pages whose text is directly extractable. Move essential content out of client-rendered components.",
    },
    "no_about": {
        "impact": 6, "effort": 2,
        "fr": "Créer ou renforcer une page « À propos » avec un auteur identifié (nom, rôle, photo) et des mentions légales accessibles : ces signaux E-E-A-T aident les IA à juger le site fiable et citable.",
        "en": "Create or strengthen an About page with an identified author (name, role, photo) and accessible legal notices: these E-E-A-T signals help AIs judge the site as trustworthy and citable.",
    },
    "no_dates": {
        "impact": 5, "effort": 2,
        "fr": "Afficher des dates de publication et de mise à jour visibles (balises <time> ou datePublished/dateModified en JSON-LD) : les IA privilégient les contenus datés et frais.",
        "en": "Show visible publication and update dates (<time> tags or datePublished/dateModified in JSON-LD): AIs favor dated, fresh content.",
    },
    "not_cited": {
        "impact": 10, "effort": 7,
        "fr": "Le site n'est cité sur aucune requête testée : publier du contenu de référence (guides pratiques, comparatifs chiffrés, FAQ) qui cite des sources reconnues, puis obtenir des liens depuis des sites déjà cités par les IA (annuaires de qualité, articles invités, partenaires).",
        "en": "The site is cited on none of the tested queries: publish reference content (practical guides, data-backed comparisons, FAQ) citing recognized sources, then earn links from sites already cited by AIs (quality directories, guest articles, partners).",
    },
    "competitors_cited": {
        "impact": 9, "effort": 5,
        "fr": "Des concurrents sont cités à votre place : analyser leurs pages citées (structure, profondeur, sources) et produire un contenu plus complet et plus factuel sur les mêmes sujets, avec des chiffres et des réponses directes aux questions des acheteurs.",
        "en": "Competitors are cited instead of you: analyze their cited pages (structure, depth, sources) and produce more comprehensive, factual content on the same topics, with figures and direct answers to buyer questions.",
    },
    "partially_cited": {
        "impact": 6, "effort": 4,
        "fr": "Le site n'est cité que sur certaines requêtes : identifier les requêtes sans citation et renforcer les pages correspondantes (contenu dédié, FAQ, données structurées).",
        "en": "The site is cited on some queries only: identify the uncited queries and strengthen the matching pages (dedicated content, FAQ, structured data).",
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
    eeat = checks["eeat"]
    # Prefer machine codes; fall back to legacy English substring matching for
    # audits generated before the codes existed.
    missing_codes = eeat.get("missing_codes")
    if missing_codes is None:
        legacy = " ".join(eeat.get("missing", []))
        missing_codes = ([c for c in ("about", "dates") if c in legacy])
    if "about" in missing_codes:
        actions.append("no_about")
    if "dates" in missing_codes:
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


# ---------------------------------------------------------------- client-facing writing (V4 pro)

_WRITER_SYSTEM = {
    "fr": "Tu es un consultant senior en visibilité IA (GEO). Tu rédiges des rapports "
          "d'audit pour des dirigeants de TPE non techniques. Français impeccable, ton "
          "professionnel et direct, phrases courtes, aucun jargon non expliqué. Tu "
          "réponds UNIQUEMENT avec l'objet JSON demandé, sans markdown ni commentaire.",
    "en": "You are a senior AI visibility (GEO) consultant. You write audit reports "
          "for non-technical small-business owners. Impeccable English, professional "
          "and direct tone, short sentences, no unexplained jargon. You answer ONLY "
          "with the requested JSON object, no markdown, no commentary.",
}

_WRITER_USER = {
    "fr": """Voici les données brutes d'un audit de visibilité IA du site {domain}.
Secteur détecté : « {keyword} ». Score global : {total}/100 (audit technique {tech}/100, \
citations {cite}). Le site est cité dans {cited}/{n} réponses de Perplexity à des questions \
d'intention d'achat. Concurrents les plus cités : {comps}.
Constats techniques : {tech_details}
Plan d'action brut (déjà priorisé) : {plan}

Rédige en français impeccable :
1. "synthese" : 3 à 4 phrases honnêtes — où en est le site, l'enjeu business, ce que \
le plan ci-dessous apporte.
2. "actions" : le plan d'action réécrit, 3 à 6 actions concrètes et précises (quoi faire, \
où, avec quel outil ou quelle démarche), chacune avec "action" (texte), "impact" (1-10) et \
"effort" (1-10). Garde l'ordre de priorité du plan brut.
JSON attendu : {{"synthese": "...", "actions": [{{"action": "...", "impact": 8, "effort": 3}}]}}""",
    "en": """Here is the raw data of an AI visibility audit for {domain}.
Detected sector: "{keyword}". Overall score: {total}/100 (technical audit {tech}/100, \
citations {cite}). The site is cited in {cited}/{n} Perplexity answers to buyer-intent \
questions. Most cited competitors: {comps}.
Technical findings: {tech_details}
Draft action plan (already prioritized): {plan}

Write in impeccable English:
1. "synthese": 3 to 4 honest sentences — where the site stands, the business stake, what \
the plan below delivers.
2. "actions": the rewritten action plan, 3 to 6 concrete, precise actions (what to do, \
where, with which tool or approach), each with "action" (text), "impact" (1-10) and \
"effort" (1-10). Keep the draft plan's priority order.
Expected JSON: {{"synthese": "...", "actions": [{{"action": "...", "impact": 8, "effort": 3}}]}}""",
}


def _parse_writer_output(raw: str) -> "dict | None":
    """Validate the V4 pro JSON. Returns {"synthese": str, "actions": [...]} or None."""
    try:
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1]
            if txt.startswith("json"):
                txt = txt[4:]
        data = json.loads(txt)
        synthese = (data.get("synthese") or "").strip()
        actions = data.get("actions")
        if not synthese or not isinstance(actions, list) or not actions:
            return None
        plan = []
        for a in actions[:6]:
            action = (a.get("action") or "").strip()
            if not action:
                continue
            try:
                impact = max(1, min(10, int(a.get("impact", 5))))
                effort = max(1, min(10, int(a.get("effort", 5))))
            except (TypeError, ValueError):
                continue
            plan.append({"action": action, "impact": impact, "effort": effort,
                         "priority_score": round(impact / effort, 1)})
        if not plan:
            return None
        for i, item in enumerate(plan, 1):
            item["rank"] = i
        return {"synthese": synthese, "actions": plan}
    except Exception:
        return None


async def write_client_report(audit_data: dict, lang: str) -> "dict | None":
    """V4 pro rewrites the client-facing text (synthesis + action plan) from the
    raw audit data. Returns None on any failure — the caller falls back to the
    rule-based library plan (explicit 'writer' field in the audit JSON)."""
    if not OPENROUTER_API_KEY:
        return None
    lang = lang if lang in _WRITER_SYSTEM else "en"
    score = audit_data.get("score") or {}
    technical = audit_data.get("technical") or {}
    citations = audit_data.get("citations") or {}
    cite_score = score.get("citation")
    cite_txt = (f"{cite_score}/100" if cite_score is not None
                else ("indisponible" if lang == "fr" else "unavailable"))
    tech_details = "; ".join(
        c.get("detail", "") for c in (technical.get("checks") or {}).values()
    ) or (technical.get("error") or "")
    comps = ", ".join(c["domain"] for c in (citations.get("competitors") or [])[:5]) or \
        ("aucun" if lang == "fr" else "none")
    plan_txt = " | ".join(a["action"] for a in (audit_data.get("action_plan") or [])) or \
        ("aucun" if lang == "fr" else "none")
    user = _WRITER_USER[lang].format(
        domain=audit_data.get("domain", ""),
        keyword=audit_data.get("keyword", ""),
        total=score.get("total", 0), tech=score.get("technical", 0), cite=cite_txt,
        cited=citations.get("cited_count", 0), n=citations.get("total", 0),
        comps=comps, tech_details=tech_details[:1200], plan=plan_txt[:1500],
    )
    timeout = httpx.Timeout(90.0)
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(OPENROUTER_URL, json={
                    "model": WRITER_MODEL,
                    "messages": [{"role": "system", "content": _WRITER_SYSTEM[lang]},
                                 {"role": "user", "content": user}],
                    "temperature": 0.3,
                    "max_tokens": 1800,
                    "response_format": {"type": "json_object"},
                    "reasoning": {"exclude": True},
                }, headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://citescan.brozapi.com",
                            "X-Title": "CiteScan report writer"})
            if r.status_code != 200:
                continue
            content = r.json()["choices"][0]["message"].get("content")
            if not content:
                continue
            parsed = _parse_writer_output(content)
            if parsed:
                return parsed
        except Exception:
            continue
    return None


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
        T = _TXT[lang if lang in _TXT else "en"]
        technical = {"score": 0, "word_count": 0, "checks": {},
                     "error": T["site_unreachable"].format(err=fetch_error)}
    else:
        technical = technical_audit(html, robots_text, final_url, lang=lang)

    if html:
        sector_info = await detect_sector(html, domain, lang)
    else:
        sector_info = {"keyword": domain, "validated": None, "attempts": 0,
                       "method": "no-page-content", "history": []}
    keyword = sector_info["keyword"]
    citations = await citation_audit(domain, keyword, lang)
    score = compute_score(technical, citations)
    plan = build_action_plan(technical, citations, lang) if not fetch_error else []

    result = {
        "domain": domain,
        "lang": lang,
        "keyword": keyword,
        "sector": sector_info,
        "score": score,
        "technical": technical,
        "citations": citations,
        "action_plan": plan,
        "mode": score["mode"],
        "perplexity_available": bool(PERPLEXITY_API_KEY),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Rédaction client par V4 pro (synthèse + plan d'action), langue du parcours.
    # Fallback explicite sur le plan issu de la bibliothèque si indisponible.
    written = await write_client_report(result, lang)
    if written:
        result["synthese"] = written["synthese"]
        if written["actions"]:
            result["action_plan"] = written["actions"]
        result["writer"] = WRITER_MODEL
    else:
        result["synthese"] = None
        result["writer"] = "fallback-library" if OPENROUTER_API_KEY else "no-openrouter-key"
    return result
