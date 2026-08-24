"""Tests offline pour app/engines.py (t_9864864c) — mocks enregistrés par
adaptateur (aucune requête réseau), grille tarifaire, registry, garde-fous."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
import engines

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


# ---------------------------------------------------------------- fake client

class _FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    async def post(self, url, json=None, headers=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def _set_keys(**kw):
    for k in ("PERPLEXITY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "GEMINI_API_KEY", "MISTRAL_API_KEY"):
        os.environ.pop(k, None)
    for k, v in kw.items():
        os.environ[k] = v


# ---------------------------------------------------------------- registry / prix

check("registry: 5 moteurs déclarés",
      list(engines.ENGINES) == ["perplexity", "gemini", "chatgpt", "claude", "mistral"])
check("registry: mistral désactivé par défaut",
      engines.ENGINES["mistral"]["enabled"] is False)

_set_keys(PERPLEXITY_API_KEY="k", GEMINI_API_KEY="k")
check("available_engines: seuls les moteurs avec clé",
      engines.available_engines() == ["perplexity", "gemini"])
check("mistral jamais disponible même avec clé (désactivé)",
      not engines.engine_available("mistral"))
os.environ["MISTRAL_API_KEY"] = "k"
check("mistral avec clé mais désactivé -> indisponible",
      not engines.engine_available("mistral"))
os.environ.pop("MISTRAL_API_KEY", None)

check("normalize_selection: base toujours incluse",
      engines.normalize_selection(["chatgpt"]) == ["perplexity", "gemini", "chatgpt"])
check("normalize_selection: inconnus et désactivés écartés",
      engines.normalize_selection(["chatgpt", "toto", "mistral", "claude"])
      == ["perplexity", "gemini", "chatgpt", "claude"])
check("normalize_selection: vide -> base seule",
      engines.normalize_selection([]) == ["perplexity", "gemini"])

check("prix 29 base", engines.price_eur(["perplexity", "gemini"]) == 29)
check("prix 29 même sans rien demander", engines.price_eur([]) == 29)
check("prix 39 base+chatgpt", engines.price_eur(["chatgpt"]) == 39)
check("prix 39 base+claude", engines.price_eur(["claude"]) == 39)
check("prix 49 les 4", engines.price_eur(["chatgpt", "claude"]) == 49)
check("engines_for_price 29 = base", engines.engines_for_price(29) == ["perplexity", "gemini"])
check("engines_for_price 39 = base+1", engines.engines_for_price(39) == ["perplexity", "gemini", "chatgpt"])
check("engines_for_price 49 = 4 moteurs",
      engines.engines_for_price(49) == ["perplexity", "gemini", "chatgpt", "claude"])

# ---------------------------------------------------------------- garde-fous query_engine

async def _qe(name, client=None):
    return await engines.query_engine(name, client or _FakeClient([]), "q", "fr")

r = asyncio.run(_qe("toto"))
check("query_engine: moteur inconnu -> échec explicite",
      r["ok"] is False and "toto" in r["error"])
r = asyncio.run(_qe("chatgpt"))  # clé OPENAI absente (set_keys plus haut)
check("query_engine: clé absente -> échec explicite, pas d'exception",
      r["ok"] is False and "OPENAI_API_KEY" in r["error"])
r = asyncio.run(_qe("mistral"))
check("query_engine: mistral désactivé -> refus propre",
      r["ok"] is False and "activ" in r["error"])

# timeout : adaptateur artificiellement lent + timeout raccourci
async def _slow(client, prompt, lang="en"):
    await asyncio.sleep(5)
    return {"ok": True, "answer": "", "citations": [], "cost": 0.0, "error": None}

_orig_q = engines.ENGINES["chatgpt"]["query"]
_orig_to = engines.ENGINE_TIMEOUT
engines.ENGINES["chatgpt"]["query"] = _slow
engines.ENGINE_TIMEOUT = 0.2
os.environ["OPENAI_API_KEY"] = "k"
r = asyncio.run(_qe("chatgpt"))
check("query_engine: timeout -> échec explicite borné",
      r["ok"] is False and "timeout" in r["error"])
engines.ENGINES["chatgpt"]["query"] = _orig_q
engines.ENGINE_TIMEOUT = _orig_to

# ---------------------------------------------------------------- mock OpenAI (Responses API)

_OPENAI_OK = {
    "output": [
        {"type": "web_search_call", "id": "ws_1"},
        {"type": "message", "content": [
            {"type": "output_text",
             "text": "Les meilleurs logiciels sont A et B [1].",
             "annotations": [
                 {"type": "url_citation", "url": "https://a.fr/x", "title": "A"},
                 {"type": "url_citation", "url": "https://b.fr/y", "title": "B"},
                 {"type": "file_citation", "file_id": "f1"},
             ]},
        ]},
    ],
    "usage": {"input_tokens": 1000, "output_tokens": 200},
}
_set_keys(OPENAI_API_KEY="sk-test")
fc = _FakeClient([_FakeResp(200, _OPENAI_OK)])
r = asyncio.run(engines.query_engine("chatgpt", fc, "ma requête", "fr"))
check("openai: ok", r["ok"] is True and r["error"] is None)
check("openai: citations = url_citation uniquement, dédupliquées",
      r["citations"] == ["https://a.fr/x", "https://b.fr/y"], str(r["citations"]))
check("openai: answer text conservé", "meilleurs logiciels" in r["answer"])
_sent = fc.sent[0]
check("openai: endpoint responses + tool web_search",
      _sent["url"] == engines.OPENAI_RESPONSES_URL and
      _sent["json"]["tools"] == [{"type": "web_search_preview"}])
check("openai: instructions langue FR", "français" in _sent["json"]["instructions"])
check("openai: auth bearer", _sent["headers"]["Authorization"] == "Bearer sk-test")
# coût = 1000*0.15e-6 + 200*0.60e-6 + 0.01 = 0.01027
check("openai: coût tokens+recherche mesuré", abs(r["cost"] - 0.01027) < 1e-6,
      str(r["cost"]))

fc_err = _FakeClient([_FakeResp(500)])
r = asyncio.run(engines.query_engine("chatgpt", fc_err, "q", "fr"))
check("openai: HTTP 500 -> échec explicite", r["ok"] is False and "500" in r["error"])

# ---------------------------------------------------------------- mock Anthropic (Messages API)

_ANTHROPIC_OK = {
    "content": [
        {"type": "server_tool_use", "id": "srv_1", "name": "web_search"},
        {"type": "web_search_tool_result", "tool_use_id": "srv_1",
         "content": [
             {"type": "web_search_result", "url": "https://c.fr/z", "title": "C"},
             {"type": "web_search_result", "url": "https://a.fr/x", "title": "A"},
         ]},
        {"type": "text",
         "text": "Voici les leaders du secteur [1].",
         "citations": [
             {"type": "web_search_result_location", "url": "https://c.fr/z",
              "title": "C", "cited_text": "..."},
         ]},
    ],
    "usage": {"input_tokens": 500, "output_tokens": 100,
              "server_tool_use": {"web_search_requests": 1}},
}
_set_keys(ANTHROPIC_API_KEY="sk-ant")
fc = _FakeClient([_FakeResp(200, _ANTHROPIC_OK)])
r = asyncio.run(engines.query_engine("claude", fc, "ma requête", "fr"))
check("anthropic: ok", r["ok"] is True)
check("anthropic: citations = union text.citations + tool_result, dédupliquées",
      r["citations"] == ["https://c.fr/z", "https://a.fr/x"], str(r["citations"]))
check("anthropic: answer text conservé", "leaders du secteur" in r["answer"])
_sent = fc.sent[0]
check("anthropic: endpoint messages + headers",
      _sent["url"] == engines.ANTHROPIC_MESSAGES_URL and
      _sent["headers"]["x-api-key"] == "sk-ant" and
      _sent["headers"]["anthropic-version"] == "2023-06-01")
check("anthropic: tool web_search max_uses=1",
      _sent["json"]["tools"][0]["type"].startswith("web_search") and
      _sent["json"]["tools"][0]["max_uses"] == 1)
# coût = 500*1e-6 + 100*5e-6 + 1*0.01 = 0.011
check("anthropic: coût tokens+recherche mesuré", abs(r["cost"] - 0.011) < 1e-6,
      str(r["cost"]))

# ---------------------------------------------------------------- mock Gemini (generateContent)

_GEMINI_OK = {
    "candidates": [
        {"content": {"parts": [{"text": "Les références sont D et E."}]},
         "groundingMetadata": {
             "groundingChunks": [
                 {"web": {"uri": "https://d.fr/w", "title": "D"}},
                 {"web": {"uri": "https://e.fr/v", "title": "E"}},
                 {"web": {"title": "sans uri"}},
             ],
         }},
    ],
    "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 100},
}
_set_keys(GEMINI_API_KEY="gkey")
fc = _FakeClient([_FakeResp(200, _GEMINI_OK)])
r = asyncio.run(engines.query_engine("gemini", fc, "ma requête", "fr"))
check("gemini: ok", r["ok"] is True)
check("gemini: citations = groundingChunks.web.uri (sans uri ignorés)",
      r["citations"] == ["https://d.fr/w", "https://e.fr/v"], str(r["citations"]))
check("gemini: answer text conservé", "références sont D et E" in r["answer"])
_sent = fc.sent[0]
check("gemini: endpoint generateContent + clé en header",
      "generateContent" in _sent["url"] and _sent["headers"]["x-goog-api-key"] == "gkey")
check("gemini: grounding google_search activé",
      _sent["json"]["tools"] == [{"google_search": {}}])
# coût = 400*0.30e-6 + 100*2.50e-6 + 0 = 0.00037
check("gemini: coût tokens mesuré, grounding gratuit", abs(r["cost"] - 0.00037) < 1e-6,
      str(r["cost"]))

# ---------------------------------------------------------------- mock Mistral (désactivé mais parsable)

_MISTRAL_OK = {
    "choices": [{"message": {"role": "assistant",
                             "content": "Réponse Mistral.",
                             "annotations": [{"type": "url_citation",
                                              "url": "https://m.fr/1"}]}}],
    "usage": {"prompt_tokens": 300, "completion_tokens": 80},
}
check("mistral: parser isolé fonctionne",
      engines._parse_mistral(_MISTRAL_OK)["citations"] == ["https://m.fr/1"] and
      "Réponse Mistral" in engines._parse_mistral(_MISTRAL_OK)["answer"])

# ---------------------------------------------------------------- 429 retry (borné)

_sleeps = []
async def _fake_sleep(s):
    _sleeps.append(s)
_orig_sleep = engines.asyncio.sleep
engines.asyncio.sleep = _fake_sleep
try:
    _set_keys(GEMINI_API_KEY="gkey")
    fc = _FakeClient([_FakeResp(429, headers={"Retry-After": "10"}),
                      _FakeResp(200, _GEMINI_OK)])
    r = asyncio.run(engines.query_engine("gemini", fc, "q", "fr"))
    check("429: retry puis succès", r["ok"] is True and len(fc.sent) == 2)
    check("429: Retry-After honoré", _sleeps and _sleeps[0] >= 10.0, str(_sleeps))
finally:
    engines.asyncio.sleep = _orig_sleep

print(f"\nENGINES: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
