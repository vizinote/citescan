"""Tests du poller de livraison (deployment/citescan-deliveries.py) —
parsing client_reference_id multi-moteurs et bornage au palier payé (t_9864864c)."""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "deliveries", os.path.join(ROOT, "deployment", "citescan-deliveries.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


# --- parse_client_reference ---
d, l, e = mod.parse_client_reference("example.fr|fr|perplexity,gemini,chatgpt")
check("ref complète: domaine+lang+moteurs",
      d == "example.fr" and l == "fr" and e == ["perplexity", "gemini", "chatgpt"])
d, l, e = mod.parse_client_reference("example.com|en")
check("ref historique 2 segments: moteurs vides",
      d == "example.com" and l == "en" and e == [])
d, l, e = mod.parse_client_reference("example.fr")
check("ref domaine seul: lang FR déduite du TLD",
      d == "example.fr" and l == "fr" and e == [])
d, l, e = mod.parse_client_reference(None)
check("ref vide: (None, None, [])", d is None and l is None and e == [])
d, l, e = mod.parse_client_reference("example.fr|fr|chatgpt,toto,claude")
check("ref moteurs inconnus filtrés", e == ["chatgpt", "claude"])

# --- clamp_engines (anti-fraude palier) ---
check("clamp 29: base seule même si 4 moteurs demandés",
      mod.clamp_engines(["perplexity", "gemini", "chatgpt", "claude"], 29)
      == ["perplexity", "gemini"])
check("clamp 39: base + 1 extra au choix",
      mod.clamp_engines(["chatgpt", "claude"], 39)
      == ["perplexity", "gemini", "chatgpt"])
check("clamp 39 avec claude seul",
      mod.clamp_engines(["claude"], 39) == ["perplexity", "gemini", "claude"])
check("clamp 49: les 4",
      mod.clamp_engines(["chatgpt", "claude"], 49)
      == ["perplexity", "gemini", "chatgpt", "claude"])
check("clamp lien historique (None): base",
      mod.clamp_engines(["chatgpt", "claude"], None) == ["perplexity", "gemini"])
check("clamp sans demande: base",
      mod.clamp_engines([], 49) == ["perplexity", "gemini"])

# --- load_payment_links (format 2 et 3 éléments) ---
tmp = tempfile.mkdtemp(prefix="citescan-links-")
links_json = os.path.join(tmp, "links.json")
with open(links_json, "w") as f:
    json.dump({"links": {
        "https://buy.stripe.com/a": ["audit", "Audit CiteScan 29 €", 29],
        "https://buy.stripe.com/b": ["audit", "Audit CiteScan 49 €", 49],
        "https://buy.stripe.com/old": ["audit", "Audit CiteScan 29 €"],
    }}, f)
_orig = mod.LINKS_JSON
mod.LINKS_JSON = links_json
try:
    links = mod.load_payment_links()
finally:
    mod.LINKS_JSON = _orig
check("links: palier lu quand présent",
      links["https://buy.stripe.com/a"] == ("audit", "Audit CiteScan 29 €", 29))
check("links: format historique 2 éléments -> palier None",
      links["https://buy.stripe.com/old"] == ("audit", "Audit CiteScan 29 €", None))

print(f"\nDELIVERIES: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
