"""Tests du sélecteur frontend multi-moteurs (t_9864864c, déverrouillé t_b0ca2cc3).

1. Structure des pages offre FR/EN : cases Perplexity+Gemini cochées et
   verrouillées, ChatGPT/Claude optionnels, prix dynamique, CTA ACTIF
   (paiement déverrouillé le 2026-08-24, GO Franck).
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
    """Le bloc <script> ACTIF (hors commentaires HTML) contenant PRICE_LADDER.
    Itère bloc par bloc : le checkout (déverrouillé t_b0ca2cc3) est aussi un
    <script> actif et une regex lazy peut chevaucher deux blocs."""
    no_comments = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for m in re.finditer(r"<script>(.*?)</script>", no_comments, flags=re.S):
        if "PRICE_LADDER" in m.group(1):
            return m.group(1)
    return ""


for lang, path in PAGES.items():
    html = open(path, encoding="utf-8").read()
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    check(f"{lang}: Perplexity + Gemini cochés et verrouillés",
          len(re.findall(r'<input type="checkbox" checked disabled>', visible)) == 2)
    extras = re.findall(r'class="eng-extra" value="(chatgpt|claude)"', visible)
    check(f"{lang}: ChatGPT et Claude optionnels", extras == ["chatgpt", "claude"], str(extras))
    check(f"{lang}: prix dynamique (offer-price + order-btn-live)",
          'id="offer-price"' in visible and 'id="order-btn-live"' in visible)
    check(f"{lang}: CTA déverrouillé (pas de btn--disabled ni notice)",
          'btn--disabled' not in visible and 'cta-disabled-notice' not in visible
          and re.search(r'<button[^>]*disabled', visible) is None)
    check(f"{lang}: formulaire de commande actif (hors commentaire)",
          'id="order-form"' in visible)
    # Liens réels activés le 2026-08-24 (GO Franck) : présents dans la partie
    # VISIBLE de la page (checkout actif).
    check(f"{lang}: liens Stripe présents dans la partie visible (paiement actif)",
          "buy.stripe.com" in visible)
    check(f"{lang}: grille JS 29/39/49",
          "PRICE_LADDER = {0: 29, 1: 39, 2: 49}" in visible)
    check(f"{lang}: 3 liens Stripe réels actifs",
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
    if (id === "order-btn-live") return btnEl;
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

# ------------------------------------------------- exécution réelle du checkout
# t_96c4f606 : pour CHAQUE combinaison, le bon Payment Link doit être choisi
# et le client_reference_id doit transporter "<domaine>|<langue>|<moteurs csv>".
# Liens canoniques créés par la carte Stripe t_6808ea76 (INACTIFS, verrou n°3).
CANONICAL_LINKS = {
    29: "https://buy.stripe.com/aFa7sF3gB90F7tN33fcZa09",
    39: "https://buy.stripe.com/9B69AN6sN3Gl4hBbzLcZa0a",
    49: "https://buy.stripe.com/bJe00d8AV2Ch8xRcDPcZa0b",
}

def _checkout_script(html: str) -> str:
    """Le bloc <script> ACTIF (déverrouillé t_b0ca2cc3) contenant STRIPE_PAYMENT_LINKS."""
    no_comments = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for m in re.finditer(r"<script>(.*?)</script>", no_comments, flags=re.S):
        if "STRIPE_PAYMENT_LINKS" in m.group(1):
            return m.group(1)
    return ""

_CHECKOUT_HARNESS = r"""
const state = {chatgpt: false, claude: false};
const extras = ["chatgpt", "claude"].map(v => ({
  value: v,
  get checked() { return state[v]; },
  addEventListener() {},
}));
const priceEl = {textContent: ""};
const btnEl = {textContent: ""};
const domainEl = {value: "https://www.exemple-site.fr/landing?x=1"};
const alerts = [];
const document = {
  querySelectorAll(sel) {
    if (sel === ".eng-extra") return extras;
    if (sel === ".eng-extra:checked") return extras.filter(x => x.checked);
    return [];
  },
  getElementById(id) {
    if (id === "offer-price") return priceEl;
    if (id === "order-btn-live") return btnEl;
    if (id === "order-domain") return domainEl;
    return null;
  },
};
const window = {location: {href: ""}};
function alert(msg) { alerts.push(msg); }
__LIVE_SCRIPT__
__CHECKOUT_SCRIPT__
const combos = [
  [{}, 29, ["perplexity", "gemini"]],
  [{chatgpt: true}, 39, ["perplexity", "gemini", "chatgpt"]],
  [{claude: true}, 39, ["perplexity", "gemini", "claude"]],
  [{chatgpt: true, claude: true}, 49, ["perplexity", "gemini", "chatgpt", "claude"]],
];
const out = [];
for (const [on, price, engines] of combos) {
  state.chatgpt = !!on.chatgpt; state.claude = !!on.claude;
  window.location.href = ""; alerts.length = 0;
  const ret = citescanCheckout({preventDefault() {}}, __LANG__);
  out.push({price, engines, ret,
            href: window.location.href, alerts: alerts.slice(),
            expectedBase: STRIPE_PAYMENT_LINKS[price],
            expectedRef: "www.exemple-site.fr|" + __LANG__ + "|" + engines.join(",")});
}
// Domaine invalide : alerte, aucune redirection.
window.location.href = ""; alerts.length = 0;
domainEl.value = "https://localhost";
const retBad = citescanCheckout({preventDefault() {}}, __LANG__);
out.push({invalid: true, ret: retBad, href: window.location.href,
          alerted: alerts.length > 0});
console.log(JSON.stringify(out));
"""

from urllib.parse import unquote

for lang, path in PAGES.items():
    html = open(path, encoding="utf-8").read()
    live = _live_script(html)
    checkout = _checkout_script(html)
    check(f"{lang}: bloc checkout extrait (actif, paiement déverrouillé)",
          "STRIPE_PAYMENT_LINKS" in checkout and "citescanCheckout" in checkout)
    # La langue propagée au checkout est celle de la page (attribut onsubmit).
    check(f"{lang}: onsubmit propage la langue '{lang}'",
          f"citescanCheckout(event, '{lang}')" in html)
    js = (_CHECKOUT_HARNESS
          .replace("__LIVE_SCRIPT__", live)
          .replace("__CHECKOUT_SCRIPT__", checkout)
          .replace("__LANG__", json.dumps(lang)))
    js_path = os.path.join(ROOT, f".tmp_checkout_test_{lang}.js")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js)
    try:
        proc = subprocess.run(["node", js_path], capture_output=True, text=True, timeout=30)
        check(f"{lang}: node exécute le checkout sans erreur",
              proc.returncode == 0, proc.stderr[:300])
        results = json.loads(proc.stdout)
        for r in results:
            if r.get("invalid"):
                check(f"{lang}: domaine invalide bloqué (alerte, pas de redirection)",
                      r["ret"] is False and r["href"] == "" and r["alerted"], str(r))
                continue
            base, _, query = r["href"].partition("?")
            ref = unquote(query.split("client_reference_id=")[-1])
            check(f"{lang}: lien Stripe du palier {r['price']} EUR ({','.join(r['engines'])})",
                  base == CANONICAL_LINKS[r["price"]] and base == r["expectedBase"], str(r))
            check(f"{lang}: client_reference_id correct ({r['price']} EUR)",
                  ref == r["expectedRef"], f"ref={ref!r}")
            check(f"{lang}: checkout retourne false (pas de soumission native)",
                  r["ret"] is False, str(r))
    finally:
        os.unlink(js_path)

print(f"\nFRONTEND: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
