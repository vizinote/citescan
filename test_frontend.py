"""Tests du sélecteur frontend multi-moteurs (t_9864864c).

1. Structure des pages offre FR/EN : cases Perplexity+Gemini cochées et
   verrouillées, ChatGPT/Claude optionnels, prix dynamique, CTA verrouillé.
2. Logique JS exécutée réellement (node, DOM simulé) : prix correct pour
   chaque combinaison et liste de moteurs propagée au checkout Stripe.
"""
import json
import os
import re
import subprocess
import sys

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


ROOT = os.path.dirname(__file__)
PAGES = {"fr": os.path.join(ROOT, "offre.html"),
         "en": os.path.join(ROOT, "en", "offer.html")}


def _live_script(html: str) -> str:
    """Le bloc <script> ACTIF (hors commentaires HTML) contenant PRICE_LADDER."""
    no_comments = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    m = re.search(r"<script>(.*?PRICE_LADDER.*?)</script>", no_comments, flags=re.S)
    return m.group(1) if m else ""


for lang, path in PAGES.items():
    html = open(path, encoding="utf-8").read()
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    check(f"{lang}: Perplexity + Gemini cochés et verrouillés",
          len(re.findall(r'<input type="checkbox" checked disabled>', visible)) == 2)
    extras = re.findall(r'class="eng-extra" value="(chatgpt|claude)"', visible)
    check(f"{lang}: ChatGPT et Claude optionnels", extras == ["chatgpt", "claude"], str(extras))
    check(f"{lang}: prix dynamique (offer-price + order-btn)",
          'id="offer-price"' in visible and 'id="order-btn"' in visible)
    check(f"{lang}: CTA toujours verrouillé (btn--disabled + disabled)",
          'btn--disabled' in visible and re.search(r'<button[^>]*disabled', visible) is not None)
    # Liens réels créés le 2026-08-24 (INACTIFS) : présents dans le HTML mais
    # UNIQUEMENT dans le bloc commenté — jamais dans la partie visible.
    check(f"{lang}: aucun lien Stripe dans la partie visible (verrou actif)",
          "buy.stripe.com" not in visible)
    check(f"{lang}: grille JS 29/39/49",
          "PRICE_LADDER = {0: 29, 1: 39, 2: 49}" in visible)
    check(f"{lang}: 3 liens Stripe réels prêts au déverrouillage (bloc commenté)",
          len(re.findall(r"https://buy\.stripe\.com/\S+", html)) == 3)
    check(f"{lang}: checkout propage domaine|langue|moteurs",
          'd + "|" + lang + "|" + currentEngines().join(",")' in html)
    check(f"{lang}: sélecteur stylé",
          "engine-select" in open(os.path.join(ROOT, "assets", "style.css"),
                                  encoding="utf-8").read())

# ---------------------------------------------------------------- exécution JS réelle

_HARNESS = r"""
// DOM minimal simulé : 2 cases extras (chatgpt, claude), prix + bouton.
const state = {chatgpt: false, claude: false};
const extras = ["chatgpt", "claude"].map(v => ({
  value: v,
  get checked() { return state[v]; },
  addEventListener() {},
}));
const priceEl = {textContent: ""};
const btnEl = {textContent: ""};
const document = {
  querySelectorAll(sel) {
    if (sel === ".eng-extra") return extras;
    if (sel === ".eng-extra:checked") return extras.filter(x => x.checked);
    return [];
  },
  getElementById(id) {
    if (id === "offer-price") return priceEl;
    if (id === "order-btn") return btnEl;
    return null;
  },
};
__SCRIPT__
const out = [];
const combos = [
  [{}, 29, ["perplexity", "gemini"]],
  [{chatgpt: true}, 39, ["perplexity", "gemini", "chatgpt"]],
  [{claude: true}, 39, ["perplexity", "gemini", "claude"]],
  [{chatgpt: true, claude: true}, 49, ["perplexity", "gemini", "chatgpt", "claude"]],
];
for (const [on, price, engines] of combos) {
  state.chatgpt = !!on.chatgpt; state.claude = !!on.claude;
  updatePrice();
  out.push({price: currentPrice(), engines: currentEngines(),
            displayed: priceEl.textContent, button: btnEl.textContent,
            expectedPrice: price, expectedEngines: engines});
}
console.log(JSON.stringify(out));
"""

script = _live_script(open(PAGES["fr"], encoding="utf-8").read())
check("script actif extrait", "PRICE_LADDER" in script and "updatePrice" in script)
js = _HARNESS.replace("__SCRIPT__", script)
js_path = os.path.join(ROOT, ".tmp_selector_test.js")
with open(js_path, "w", encoding="utf-8") as f:
    f.write(js)
try:
    proc = subprocess.run(["node", js_path], capture_output=True, text=True, timeout=30)
    check("node exécute le sélecteur sans erreur",
          proc.returncode == 0, proc.stderr[:300])
    results = json.loads(proc.stdout)
    for r in results:
        check(f"JS: prix {r['expectedPrice']} EUR pour {r['expectedEngines']}",
              r["price"] == r["expectedPrice"] and r["engines"] == r["expectedEngines"],
              str(r))
        check(f"JS: prix affiché et bouton à jour ({r['expectedPrice']})",
              str(r["expectedPrice"]) in r["displayed"] and
              str(r["expectedPrice"]) in r["button"], str(r))
finally:
    os.unlink(js_path)

print(f"\nFRONTEND: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
