"""CiteScan — couche d'abstraction des moteurs IA (t_9864864c).

Interface commune pour interroger un moteur d'IA avec recherche web :

    async query_engine(name, client, prompt, lang)
        -> {"ok": bool, "answer": str, "citations": [url], "cost": float,
            "error": str | None}

Registry ENGINES (ordre = ordre d'affichage) :
    name -> {"label", "env_key", "enabled", "query"}

Règles (carte t_9864864c) :
- les clés sont lues depuis l'environnement À CHAQUE APPEL (jamais en dur,
  jamais dans git) ; un moteur sans clé est simplement indisponible ;
- JAMAIS d'exception vers l'appelant : tout échec (quota, 5xx, timeout)
  retourne ok=False — l'audit livre des résultats PARTIELS explicites ;
- coût réel mesuré par appel (champ "cost", USD) — garde-fou budget ;
- mistral : adaptateur PRÉPARÉ mais DÉSACTIVÉ par défaut (veille Franck
  2026-08-24 — activation ultérieure selon coût/requête).

Grille tarifaire validée par Franck (2026-08-24) :
- 29 € : Perplexity + Gemini (base incluse dans tous les paliers)
- 39 € : base + ChatGPT OU Claude au choix
- 49 € : les 4 IA (« audit complet »)
"""
import asyncio
import os
from urllib.parse import urlparse

import httpx

# 60 s par appel moteur (garde-fou robustesse : un moteur lent ne fait
# jamais échouer l'audit global).
ENGINE_TIMEOUT = 60.0

# Domaines d'infrastructure de redirection du grounding Gemini : les
# groundingChunks renvoient des URL vertexaisearch.cloud.google.com/... qui
# REDIRIGENT vers la vraie source. Ce ne sont JAMAIS des concurrents
# (relecture t_148128db : ce domaine technique apparaissait en « concurrent
# le plus cité » n°1 et dans les verbatims « cités à votre place »). On
# résout la redirection vers la destination réelle ; si la résolution échoue,
# l'URL est EXCLUE des citations.
GROUNDING_REDIRECT_HOSTS = {
    "vertexaisearch.cloud.google.com",
    "vertexaisearch.googleapis.com",
}


def _host_of_url(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _is_infra_url(url: str) -> bool:
    return _host_of_url(url) in GROUNDING_REDIRECT_HOSTS


async def _resolve_grounding_redirects(client: httpx.AsyncClient,
                                       urls: list) -> list:
    """Résout les URL de redirection du grounding vers leur destination réelle
    (GET borné à 8 s, redirections suivies, en parallèle). Une URL non
    résolue — ou pointant toujours vers un domaine d'infrastructure — est
    exclue : jamais de domaine technique dans les résultats remis au client."""

    async def _one(u):
        try:
            r = await client.get(u, follow_redirects=True, timeout=8.0)
            final = str(r.url)
            return None if _is_infra_url(final) else final
        except Exception:
            return None

    resolved = await asyncio.gather(*(_one(u) for u in urls))
    return [u for u in resolved if u]

# Force la langue de réponse (recette 2026-08-24 : sans consigne explicite,
# les moteurs répondent en anglais et polluent les rapports FR).
SYSTEM_PROMPT = {
    "fr": "Tu es un assistant de recherche francophone. Réponds exclusivement en "
          "français, de façon factuelle et concise, et privilégie les sources "
          "francophones pertinentes.",
    "en": "You are an English-speaking research assistant. Answer exclusively in "
          "English, factually and concisely, and prefer relevant English-language "
          "sources.",
}

# 640 tokens suffisent largement : seules 1-2 phrases (verbatim) et les URLs
# citées sont utilisées — réponses plus courtes = audit ~2x plus rapide et
# moins cher (constat prod t_a857e039).
MAX_OUTPUT_TOKENS = 640

# Prix des tokens (USD/token, volontairement conservateurs pour ne jamais
# sous-compter) — utilisés quand l'API ne renvoie pas un coût calculé.
_PRICES = {
    # gpt-4o-mini : $0.15/M in, $0.60/M out ; web_search $10/1000 appels
    "chatgpt": {"in": 0.15 / 1e6, "out": 0.60 / 1e6, "search_call": 0.010},
    # claude-haiku-4.5 : $1/M in, $5/M out ; web_search $10/1000 recherches
    "claude": {"in": 1.00 / 1e6, "out": 5.00 / 1e6, "search_call": 0.010},
    # gemini-2.5-flash : $0.30/M in, $2.50/M out ; grounding Google Search
    # gratuit jusqu'à 5 000 requêtes/mois -> search_call = 0 (surveillé).
    "gemini": {"in": 0.30 / 1e6, "out": 2.50 / 1e6, "search_call": 0.0},
    # mistral-small (adaptateur désactivé — estimation indicative)
    "mistral": {"in": 0.10 / 1e6, "out": 0.30 / 1e6, "search_call": 0.010},
}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _system(lang: str) -> str:
    return SYSTEM_PROMPT.get(lang, SYSTEM_PROMPT["en"])


# ---------------------------------------------------------------- perplexity
# Agent API (POST /v1/agent, modèle perplexity/sonar + outil web_search).
# Migré le 2026-08-24 (t_b4b6a798) : Sonar Chat Completions coupé le
# 27/09/2026. Coût mesuré : ~0,005 $/requête (~0,08 $/audit de 15).

PERPLEXITY_AGENT_URL = "https://api.perplexity.ai/v1/agent"
PERPLEXITY_AGENT_MODEL = "perplexity/sonar"


async def _perplexity_query(client: httpx.AsyncClient, prompt: str,
                            lang: str = "en", retries: int = 3) -> dict:
    delay = 4.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(PERPLEXITY_AGENT_URL, json={
                "model": PERPLEXITY_AGENT_MODEL,
                "input": prompt,
                "instructions": _system(lang),
                "language_preference": lang,
                "tools": [{"type": "web_search"}],
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            }, headers={"Authorization": f"Bearer {_env('PERPLEXITY_API_KEY')}",
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                wait = delay
                retry_after = r.headers.get("Retry-After")
                if retry_after:
                    try:
                        # borné : un Retry-After élevé sous charge parallèle ne
                        # doit pas faire dérailler tout l'audit
                        wait = min(max(wait, float(retry_after)), 30.0)
                    except ValueError:
                        pass
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                        "error": f"HTTP {r.status_code}"}
            data = r.json()
            urls, answer_parts = [], []
            for item in data.get("output", []) or []:
                itype = item.get("type")
                if itype == "search_results":
                    urls += [x.get("url") for x in item.get("results", []) or []
                             if x.get("url")]
                elif itype == "message":
                    for part in item.get("content", []) or []:
                        if part.get("text"):
                            answer_parts.append(part["text"])
                        for ann in part.get("annotations", []) or []:
                            if ann.get("url"):
                                urls.append(ann["url"])
            cost = ((data.get("usage") or {}).get("cost") or {}).get("total_cost") or 0.0
            return {"ok": True, "answer": " ".join(answer_parts).strip(),
                    "citations": list(dict.fromkeys(urls)),
                    "cost": float(cost), "error": None}
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                    "error": str(e)[:200]}
    return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
            "error": "échec inattendu"}


# ---------------------------------------------------------------- openai (chatgpt)
# Responses API + outil web_search ($10/1000 appels + tokens).

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-4o-mini"


def _parse_openai(data: dict) -> dict:
    urls, answer_parts = [], []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                answer_parts.append(part["text"])
                for ann in part.get("annotations", []) or []:
                    if ann.get("type") == "url_citation" and ann.get("url"):
                        urls.append(ann["url"])
    usage = data.get("usage") or {}
    p = _PRICES["chatgpt"]
    cost = (usage.get("input_tokens", 0) * p["in"] +
            usage.get("output_tokens", 0) * p["out"] + p["search_call"])
    return {"answer": " ".join(answer_parts).strip(),
            "citations": list(dict.fromkeys(urls)), "cost": cost}


async def _openai_query(client: httpx.AsyncClient, prompt: str,
                        lang: str = "en", retries: int = 2) -> dict:
    delay = 4.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(OPENAI_RESPONSES_URL, json={
                "model": OPENAI_MODEL,
                "instructions": _system(lang),
                "input": prompt,
                "tools": [{"type": "web_search_preview"}],
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            }, headers={"Authorization": f"Bearer {_env('OPENAI_API_KEY')}",
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                retry_after = r.headers.get("Retry-After")
                wait = delay
                if retry_after:
                    try:
                        wait = min(max(wait, float(retry_after)), 30.0)
                    except ValueError:
                        pass
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                        "error": f"HTTP {r.status_code}"}
            parsed = _parse_openai(r.json())
            parsed.update({"ok": True, "error": None})
            return parsed
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                    "error": str(e)[:200]}
    return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
            "error": "échec inattendu"}


# ---------------------------------------------------------------- anthropic (claude)
# Messages API + outil web_search ($10/1000 recherches + tokens).

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"


def _parse_anthropic(data: dict) -> dict:
    urls, answer_parts = [], []
    blocks = data.get("content", []) or []
    # Préambule d'agent (relecture t_148128db) : Claude annonce sa recherche
    # (« Je vais rechercher les meilleures solutions actuelles… ») dans un bloc
    # texte AVANT le web_search_tool_result — ce raisonnement interne ne doit
    # pas figurer dans le verbatim client : seul le texte postérieur à la
    # dernière recherche web est conservé (sans recherche : tout le texte).
    last_search = max((i for i, b in enumerate(blocks)
                       if b.get("type") == "web_search_tool_result"),
                      default=-1)
    for i, block in enumerate(blocks):
        btype = block.get("type")
        if btype == "text":
            if i > last_search and block.get("text"):
                answer_parts.append(block["text"])
            for cit in block.get("citations", []) or []:
                if cit.get("url"):
                    urls.append(cit["url"])
        elif btype == "web_search_tool_result":
            for res in block.get("content", []) or []:
                if isinstance(res, dict) and res.get("url"):
                    urls.append(res["url"])
    usage = data.get("usage") or {}
    searches = ((usage.get("server_tool_use") or {}).get("web_search_requests")
                or 1)
    p = _PRICES["claude"]
    cost = (usage.get("input_tokens", 0) * p["in"] +
            usage.get("output_tokens", 0) * p["out"] +
            searches * p["search_call"])
    return {"answer": " ".join(answer_parts).strip(),
            "citations": list(dict.fromkeys(urls)), "cost": cost}


async def _anthropic_query(client: httpx.AsyncClient, prompt: str,
                           lang: str = "en", retries: int = 2) -> dict:
    delay = 4.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(ANTHROPIC_MESSAGES_URL, json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "system": _system(lang),
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{"type": "web_search_20250305",
                           "name": "web_search", "max_uses": 1}],
            }, headers={"x-api-key": _env("ANTHROPIC_API_KEY"),
                        "anthropic-version": ANTHROPIC_VERSION,
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                retry_after = r.headers.get("Retry-After")
                wait = delay
                if retry_after:
                    try:
                        wait = min(max(wait, float(retry_after)), 30.0)
                    except ValueError:
                        pass
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                        "error": f"HTTP {r.status_code}"}
            parsed = _parse_anthropic(r.json())
            parsed.update({"ok": True, "error": None})
            return parsed
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                    "error": str(e)[:200]}
    return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
            "error": "échec inattendu"}


# ---------------------------------------------------------------- gemini
# generateContent + grounding Google Search (5 000 requêtes/mois gratuites).

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.5-flash:generateContent")


def _parse_gemini(data: dict) -> dict:
    urls, answer_parts = [], []
    candidates = data.get("candidates", []) or []
    if candidates:
        cand = candidates[0]
        for part in ((cand.get("content") or {}).get("parts", []) or []):
            if part.get("text"):
                answer_parts.append(part["text"])
        gm = cand.get("groundingMetadata") or {}
        for chunk in gm.get("groundingChunks", []) or []:
            uri = (chunk.get("web") or {}).get("uri")
            if uri:
                urls.append(uri)
    usage = data.get("usageMetadata") or {}
    p = _PRICES["gemini"]
    cost = (usage.get("promptTokenCount", 0) * p["in"] +
            usage.get("candidatesTokenCount", 0) * p["out"] +
            p["search_call"])
    return {"answer": " ".join(answer_parts).strip(),
            "citations": list(dict.fromkeys(urls)), "cost": cost}


async def _gemini_query(client: httpx.AsyncClient, prompt: str,
                        lang: str = "en", retries: int = 2) -> dict:
    delay = 4.0
    for attempt in range(retries + 1):
        try:
            r = await client.post(GEMINI_URL, json={
                "systemInstruction": {"parts": [{"text": _system(lang)}]},
                "contents": [{"role": "user",
                              "parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
            }, headers={"x-goog-api-key": _env("GEMINI_API_KEY"),
                        "Content-Type": "application/json"})
            if r.status_code == 429 and attempt < retries:
                retry_after = r.headers.get("Retry-After")
                wait = delay
                if retry_after:
                    try:
                        wait = min(max(wait, float(retry_after)), 30.0)
                    except ValueError:
                        pass
                await asyncio.sleep(wait)
                delay *= 2
                continue
            if r.status_code != 200:
                return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                        "error": f"HTTP {r.status_code}"}
            parsed = _parse_gemini(r.json())
            # t_148128db : résoudre les URL de redirection du grounding vers
            # la destination réelle AVANT de les compter comme citations
            # (sinon vertexaisearch.cloud.google.com est « concurrent n°1 »).
            infra = [u for u in parsed["citations"] if _is_infra_url(u)]
            if infra:
                resolved = await _resolve_grounding_redirects(client, infra)
                parsed["citations"] = list(dict.fromkeys(
                    [u for u in parsed["citations"] if not _is_infra_url(u)]
                    + resolved))
            parsed.update({"ok": True, "error": None})
            return parsed
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                    "error": str(e)[:200]}
    return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
            "error": "échec inattendu"}


# ---------------------------------------------------------------- mistral (DÉSACTIVÉ)
# Veille Franck 2026-08-24 : adaptateur préparé (Le Chat = argument marketing
# FR) mais désactivé par défaut — activation ultérieure selon coût/requête.
# NON TESTÉ en live (pas de clé à ce jour) : à valider avant activation.

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "mistral-small-latest"


def _parse_mistral(data: dict) -> dict:
    urls, answer = [], ""
    choices = data.get("choices", []) or []
    if choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            answer = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    answer += part["text"] + " "
        for ann in msg.get("annotations", []) or []:
            if isinstance(ann, dict) and ann.get("url"):
                urls.append(ann["url"])
    usage = data.get("usage") or {}
    p = _PRICES["mistral"]
    cost = (usage.get("prompt_tokens", 0) * p["in"] +
            usage.get("completion_tokens", 0) * p["out"] + p["search_call"])
    return {"answer": answer.strip(),
            "citations": list(dict.fromkeys(urls)), "cost": cost}


async def _mistral_query(client: httpx.AsyncClient, prompt: str,
                         lang: str = "en", retries: int = 2) -> dict:
    try:
        r = await client.post(MISTRAL_URL, json={
            "model": MISTRAL_MODEL,
            "messages": [{"role": "system", "content": _system(lang)},
                         {"role": "user", "content": prompt}],
            "tools": [{"type": "web_search"}],
            "max_tokens": MAX_OUTPUT_TOKENS,
        }, headers={"Authorization": f"Bearer {_env('MISTRAL_API_KEY')}",
                    "Content-Type": "application/json"})
        if r.status_code != 200:
            return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                    "error": f"HTTP {r.status_code}"}
        parsed = _parse_mistral(r.json())
        parsed.update({"ok": True, "error": None})
        return parsed
    except Exception as e:
        return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                "error": str(e)[:200]}


# ---------------------------------------------------------------- registry

ENGINES = {
    "perplexity": {"label": "Perplexity", "env_key": "PERPLEXITY_API_KEY",
                   "enabled": True, "query": _perplexity_query},
    "gemini": {"label": "Gemini", "env_key": "GEMINI_API_KEY",
               "enabled": True, "query": _gemini_query},
    "chatgpt": {"label": "ChatGPT", "env_key": "OPENAI_API_KEY",
                "enabled": True, "query": _openai_query},
    "claude": {"label": "Claude", "env_key": "ANTHROPIC_API_KEY",
               "enabled": True, "query": _anthropic_query},
    # Préparé, désactivé par défaut (activation ultérieure selon coût).
    "mistral": {"label": "Mistral", "env_key": "MISTRAL_API_KEY",
                "enabled": False, "query": _mistral_query},
}

# Grille tarifaire validée par Franck (2026-08-24) : Perplexity + Gemini
# inclus dans tous les paliers ; chaque moteur supplémentaire (ChatGPT,
# Claude) ajoute un palier de 10 €.
BASE_ENGINES = ("perplexity", "gemini")
EXTRA_ENGINES = ("chatgpt", "claude")
PRICE_LADDER = {0: 29, 1: 39, 2: 49}  # nb d'extras -> prix EUR TTC


def engine_available(name: str) -> bool:
    """Un moteur est utilisable s'il est activé ET sa clé est dans l'env."""
    spec = ENGINES.get(name)
    return bool(spec and spec["enabled"] and _env(spec["env_key"]))


def available_engines() -> list:
    """Moteurs réellement utilisables maintenant (ordre du registry)."""
    return [name for name in ENGINES if engine_available(name)]


def normalize_selection(selected) -> list:
    """Sélection client -> liste de moteurs valide : la base (Perplexity +
    Gemini) est TOUJOURS incluse, les inconnus/désactivés sont écartés,
    l'ordre du registry est conservé. Ne filtre PAS sur la présence des clés
    (la disponibilité est gérée au moment de l'audit, avec mention explicite)."""
    sel = set(selected or []) | set(BASE_ENGINES)
    return [name for name in ENGINES
            if name in sel and ENGINES[name]["enabled"]]


def price_eur(selected) -> int:
    """Prix du palier pour une sélection de moteurs (grille 29/39/49)."""
    sel = set(normalize_selection(selected))
    n_extra = len([e for e in EXTRA_ENGINES if e in sel])
    return PRICE_LADDER[n_extra]


def engines_for_price(price: int) -> list:
    """Moteurs maximum couverts par un palier payé (anti-fraude côté poller :
    on ne peut pas obtenir 4 moteurs en payant 29 € via un client_reference_id
    bricolé)."""
    n_extra = {29: 0, 39: 1, 49: 2}.get(int(price), 0)
    return list(BASE_ENGINES) + list(EXTRA_ENGINES[:n_extra])


async def query_engine(name: str, client: httpx.AsyncClient, prompt: str,
                       lang: str = "en") -> dict:
    """Point d'entrée unique : un appel moteur, jamais d'exception."""
    spec = ENGINES.get(name)
    if not spec or not spec["enabled"]:
        return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                "error": f"moteur inconnu ou désactivé: {name}"}
    if not _env(spec["env_key"]):
        return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                "error": f"clé {spec['env_key']} absente"}
    try:
        res = await asyncio.wait_for(
            spec["query"](client, prompt, lang), timeout=ENGINE_TIMEOUT)
        # Défense en profondeur (t_148128db) : un domaine d'infrastructure de
        # redirection (grounding Gemini) ne doit JAMAIS apparaître dans les
        # citations, quel que soit le moteur qui l'a émis.
        res["citations"] = [u for u in res.get("citations", [])
                            if not _is_infra_url(u)]
        return res
    except asyncio.TimeoutError:
        return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                "error": f"timeout {ENGINE_TIMEOUT:.0f}s"}
    except Exception as e:
        return {"ok": False, "answer": "", "citations": [], "cost": 0.0,
                "error": str(e)[:200]}
