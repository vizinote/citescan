#!/bin/bash
# citescan-tests.sh — tests bout-en-bout CiteScan (carte recette 2026-08-24).
# "Teste bout-en-bout" = sortie de ce script. Exit code != 0 si un test echoue.
# Usage : run-script citescan-tests.sh   (ou bash /root/citescan-tests.sh)
set -u
BASE="${CITESCAN_BASE:-http://127.0.0.1:8083}"
PUB="${CITESCAN_PUBLIC:-https://citescan.brozapi.com}"
TOKEN=$(grep -E '^CITESCAN_INTERNAL_TOKEN=' /root/.hermes/citescan.env 2>/dev/null | cut -d= -f2-)
PASS=0; FAIL=0

ok()    { if [ "$2" = "$3" ]; then echo "PASS $1"; PASS=$((PASS+1)); else echo "FAIL $1 (attendu=$3 obtenu=$2)"; FAIL=$((FAIL+1)); fi; }
has()   { case "$2" in *"$3"*) echo "PASS $1"; PASS=$((PASS+1));; *) echo "FAIL $1 -- chaine absente: $3"; FAIL=$((FAIL+1));; esac; }
hasnot(){ case "$2" in *"$3"*) echo "FAIL $1 -- chaine interdite presente: $3"; FAIL=$((FAIL+1));; *) echo "PASS $1"; PASS=$((PASS+1));; esac; }

echo "===== CiteScan tests bout-en-bout — $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
echo "BASE=$BASE PUB=$PUB"

# --- 1. Healthcheck ---
echo "--- healthcheck ---"
BODY=$(curl -s -o /tmp/t_health.json -w "%{http_code}" "$BASE/health")
ok "health 200" "$BODY" "200"
has "health ok:true" "$(cat /tmp/t_health.json)" '"ok":true'

# --- 2. Pages / et /fr/ : 200 + bonne langue (contenu serveur, sans JS) ---
echo "--- pages publiques (langue) ---"
EN=$(curl -s "$BASE/")
FR=$(curl -s "$BASE/fr/")
ok "/ -> 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")" "200"
ok "/fr/ -> 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/fr/")" "200"
has "/ EN : titre EN" "$EN" "Is your site cited by ChatGPT"
has "/ EN : bouton EN" "$EN" "Scan my site"
hasnot "/ EN : pas de FR dans le corps" "$EN" "Scanner mon site"
has "/fr/ FR : titre FR" "$FR" "Votre site est-il cité par ChatGPT"
has "/fr/ FR : bouton FR" "$FR" "Scanner mon site"
has "/fr/ FR : sous-titre FR" "$FR" "Scan gratuit instantané"
hasnot "/fr/ FR : pas d'EN dans le corps" "$FR" "Scan my site"
has "/fr/ : lien retour English vers /" "$FR" 'id="lang-switch" href="/"'
has "/ : lien Français vers /fr/" "$EN" 'id="lang-switch" href="/fr/"'
has "/fr/ : JSON-LD valide (schema.org)" "$FR" 'https://schema.org'
hasnot "/ : JSON-LD non corrompu" "$EN" 'https://***'

# --- 3. Fichiers de textes i18n ---
echo "--- textes i18n ---"
FRJ=$(curl -s "$BASE/textes/fr.json")
ENJ=$(curl -s "$BASE/textes/en.json")
has "fr.json FR" "$FRJ" "Scanner mon site"
has "en.json EN" "$ENJ" "Scan my site"

# --- 4. Scan gratuit : domaine nu, https, invalide (jamais de 500) ---
echo "--- scan gratuit ---"
S1=$(curl -s -w "|%{http_code}" -H "X-Internal-Token: $TOKEN" "$BASE/api/scan?url=brozapi.com")
CODE1="${S1##*|}"
ok "scan domaine nu -> 200" "$CODE1" "200"
has "scan nu : score present" "${S1%|*}" '"score"'
hasnot "scan nu : pas de 500" "$CODE1" "500"
S2=$(curl -s -w "|%{http_code}" -H "X-Internal-Token: $TOKEN" "$BASE/api/scan?url=https://example.com")
ok "scan https -> 200" "${S2##*|}" "200"
has "scan https : score" "${S2%|*}" '"score"'
S3=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Internal-Token: $TOKEN" "$BASE/api/scan?url=%25%25%25")
ok "scan invalide -> 400" "$S3" "400"
S4=$(curl -s -H "X-Internal-Token: $TOKEN" "$BASE/api/scan?url=inaccessible-zzz.invalid&lang=fr")
has "scan FR : findings en francais" "$S4" "site inaccessible"
hasnot "scan FR : pas d'anglais" "$S4" "site unreachable"
S5=$(curl -s -H "X-Internal-Token: $TOKEN" "$BASE/api/scan?url=example.com&lang=en")
has "scan EN : findings en anglais" "$S5" "robots.txt"

# --- 5. Rapports payants FR + EN (rendu reel, audit fixture = sans cout Perplexity) ---
echo "--- rapports FR/EN (rendu) ---"
cat > /tmp/t_audit_fr.json <<'EOF'
{"domain": "https://boulangerie-martin.fr", "lang": "fr", "keyword": "boulangerie artisanale",
 "score": {"total": 55, "technical": 55, "citation": 50, "mode": "full"},
 "technical": {"score": 55, "word_count": 180, "checks": {
   "robots": {"status": "warn", "points": 15, "detail": "robots.txt introuvable — les bots IA sont autorisés par défaut", "bots": {}},
   "extract": {"status": "warn", "points": 20, "detail": "contenu textuel un peu mince : étoffez le texte visible sans JavaScript pour maximiser vos chances d'être cité"},
   "jsonld": {"status": "warn", "points": 5, "detail": "aucune donnée structurée JSON-LD"},
   "eeat": {"status": "warn", "points": 10, "detail": "dates de publication présentes; pas de page à propos / mentions légales",
            "signals": ["dates de publication présentes"], "missing": ["pas de page à propos / mentions légales"],
            "signal_codes": ["dates"], "missing_codes": ["about", "author"]}}},
 "citations": {"status": "ok", "queries_ok": 2, "total": 2, "cited_count": 1,
   "queries": [
     {"query": "Quel est le meilleur boulangerie artisanale pour une petite entreprise ?", "cited": true,
      "error": null, "citations": ["capterra.com"],
      "verbatim": "Les boulangeries artisanales les mieux notées sont référencées sur des annuaires spécialisés. Les comparatifs locaux dominent les réponses."},
     {"query": "Où acheter boulangerie artisanale en ligne en France ?", "cited": false,
      "error": null, "citations": ["boulangerie-concurrent.fr"],
      "verbatim": "Plusieurs enseignes proposent la vente en ligne de pain artisanal."}],
   "competitors": [{"domain": "capterra.com", "count": 2}, {"domain": "boulangerie-concurrent.fr", "count": 1}],
   "competitor_urls": {"capterra.com": "https://capterra.com/x"},
   "cost_usd": 0.01, "engine": "agent-api:perplexity/sonar"},
 "cms": {"cms": "wordpress", "label": "WordPress",
         "instruction": "WordPress détecté : installez l'extension gratuite « WPCode »."},
 "platforms": [{"name": "Capterra", "domain": "capterra.com"}],
 "deliverables": {
   "pourquoi_cites": ["L'IA privilégie les annuaires avec avis clients vérifiés."],
   "actions_contenu": [{"titre": "Prix du pain artisanal en 2026 : le guide complet",
                        "angle": "Transparence tarifaire chiffrée par ville."}],
   "faq": [{"q": "Combien coûte une baguette artisanale ?",
            "r": "Comptez entre 1,20 et 1,60 € selon la région."},
           {"q": "Le pain artisanal se conserve combien de temps ?",
            "r": "De 2 à 3 jours dans un torchon à température ambiante."}],
   "faq_jsonld": "{\n  \"@context\": \"https://schema.org\",\n  \"@type\": \"FAQPage\",\n  \"mainEntity\": [\n    {\n      \"@type\": \"Question\",\n      \"name\": \"Combien coûte une baguette artisanale ?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Comptez entre 1,20 et 1,60 € selon la région.\"\n      }\n    }\n  ]\n}",
   "roadmap": {"j30": ["Publier la FAQ fournie"], "j60": ["Créer le guide des prix"],
               "j90": ["S'inscrire sur Capterra"]},
   "roadmap_source": "v4-pro", "competitor_pages": [],
   "writer": "deepseek/deepseek-v4-pro-0813"},
 "action_plan": [{"action": "Ajouter des données structurées JSON-LD sur la page d'accueil.", "impact": 8, "effort": 3, "priority_score": 2.7, "rank": 1}],
 "synthese": "Votre site est techniquement solide mais reste invisible des IA. Ce rapport priorise les actions à mener.",
 "writer": "deepseek/deepseek-v4-pro-0813",
 "mode": "full", "generated_at": "2026-08-24T00:00:00Z"}
EOF
cat > /tmp/t_audit_en.json <<'EOF'
{"domain": "https://acme-bakery.com", "lang": "en", "keyword": "artisan bakery",
 "score": {"total": 55, "technical": 55, "citation": 50, "mode": "full"},
 "technical": {"score": 55, "word_count": 180, "checks": {
   "robots": {"status": "warn", "points": 15, "detail": "robots.txt not found — AI bots default to allowed", "bots": {}},
   "extract": {"status": "warn", "points": 20, "detail": "text content is on the thin side: expand the text visible without JavaScript to maximize your chances of being cited"},
   "jsonld": {"status": "warn", "points": 5, "detail": "no JSON-LD structured data"},
   "eeat": {"status": "warn", "points": 10, "detail": "dates present; no about/legal page",
            "signals": ["dates present"], "missing": ["no about/legal page"],
            "signal_codes": ["dates"], "missing_codes": ["about", "author"]}}},
 "citations": {"status": "ok", "queries_ok": 2, "total": 2, "cited_count": 1,
   "queries": [
     {"query": "What is the best artisan bakery for a small business?", "cited": true,
      "error": null, "citations": ["yelp.com"],
      "verbatim": "The best-rated artisan bakeries are listed on review directories. Local comparisons dominate the answers."},
     {"query": "Where can I buy artisan bakery online?", "cited": false,
      "error": null, "citations": ["competitor-bakery.com"],
      "verbatim": "Several brands sell artisan bread online."}],
   "competitors": [{"domain": "yelp.com", "count": 2}, {"domain": "competitor-bakery.com", "count": 1}],
   "competitor_urls": {"yelp.com": "https://yelp.com/x"},
   "cost_usd": 0.01, "engine": "agent-api:perplexity/sonar"},
 "cms": {"cms": "webflow", "label": "Webflow",
         "instruction": "Webflow detected: Project Settings → Custom Code → paste into Head Code."},
 "platforms": [{"name": "Yelp", "domain": "yelp.com"}],
 "deliverables": {
   "pourquoi_cites": ["The AI favors directories with verified customer reviews."],
   "actions_contenu": [{"titre": "Artisan bread prices in 2026: the complete guide",
                        "angle": "Transparent per-city pricing with figures."}],
   "faq": [{"q": "How much does an artisan baguette cost?",
            "r": "Between $1.50 and $2.50 depending on the region."}],
   "faq_jsonld": "{\n  \"@context\": \"https://schema.org\",\n  \"@type\": \"FAQPage\",\n  \"mainEntity\": [\n    {\n      \"@type\": \"Question\",\n      \"name\": \"How much does an artisan baguette cost?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Between $1.50 and $2.50 depending on the region.\"\n      }\n    }\n  ]\n}",
   "roadmap": {"j30": ["Publish the provided FAQ"], "j60": ["Create the price guide"],
               "j90": ["Register on Yelp"]},
   "roadmap_source": "v4-pro", "competitor_pages": [],
   "writer": "deepseek/deepseek-v4-pro-0813"},
 "action_plan": [{"action": "Add JSON-LD structured data on the homepage and key pages.", "impact": 8, "effort": 3, "priority_score": 2.7, "rank": 1}],
 "synthese": "Your site is technically sound but invisible to AI assistants. This report prioritizes what to do next.",
 "writer": "deepseek/deepseek-v4-pro-0813",
 "mode": "full", "generated_at": "2026-08-24T00:00:00Z"}
EOF

RFR=$(curl -s -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
      -d "{\"lang\":\"fr\",\"audit\":$(cat /tmp/t_audit_fr.json)}" "$BASE/api/report")
TOKFR=$(printf '%s' "$RFR" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
ok "rapport FR cree" "$([ -n "$TOKFR" ] && echo oui)" "oui"
HFR=$(curl -s "$BASE/rapports/$TOKFR")
has "rapport FR : titre FR" "$HFR" "Rapport d'audit de visibilité IA"
has "rapport FR : synthese V4 affichee" "$HFR" "Synthèse"
has "rapport FR : synthese FR" "$HFR" "invisible des IA"
has "rapport FR : detail FR" "$HFR" "introuvable"
has "rapport FR : plan FR" "$HFR" "Plan d'action complet"
hasnot "rapport FR : zero anglais technique" "$HFR" "without JS"
hasnot "rapport FR : zero anglais detail" "$HFR" "not found — AI bots"
hasnot "rapport FR : jargon word count retire" "$HFR" "mots</strong>"
hasnot "rapport FR : pas de compteur de mots brut" "$HFR" "mots extractibles"
has "rapport FR : secteur analyse (nouveau libelle)" "$HFR" "Secteur analysé"
# --- rapport niveau 2 (t_a857e039) : controles exiges ---
has "rapport FR : top 3 actions" "$HFR" "Vos 3 actions prioritaires"
has "rapport FR : roadmap 30/60/90 presente" "$HFR" "Feuille de route 30 / 60 / 90 jours"
has "rapport FR : phase J30" "$HFR" "Les 30 premiers jours"
has "rapport FR : phase J60" "$HFR" "Jours 30 à 60"
has "rapport FR : phase J90" "$HFR" "Jours 60 à 90"
has "rapport FR : verbatims IA presents" "$HFR" "Ce que l'IA répond vraiment"
has "rapport FR : verbatim reel" "$HFR" "Les boulangeries artisanales les mieux notées"
has "rapport FR : pourquoi concurrents cites" "$HFR" "Pourquoi vos concurrents sont cités"
has "rapport FR : 3 contenus titre+angle" "$HFR" "Prix du pain artisanal en 2026"
has "rapport FR : FAQ presente" "$HFR" "Votre FAQ prête à publier"
has "rapport FR : question FAQ" "$HFR" "Combien coûte une baguette artisanale ?"
has "rapport FR : JSON-LD FAQPage affiche" "$HFR" "FAQPage"
has "rapport FR : CMS instruction (WPCode)" "$HFR" "WPCode"
has "rapport FR : plateformes/annuaires" "$HFR" "Plateformes et annuaires"
has "rapport FR : rescan J+30 affiche" "$HFR" "Mesurez vos progrès dans 30 jours"
has "rapport FR : lien rescan" "$HFR" "/rescan/"
# JSON-LD du rapport : extraction du bloc <pre class="code"> puis json.loads reel
printf '%s' "$HFR" > /tmp/t_rep_fr.html
JLOK=$(python3 - <<'PYEOF'
import html, json, re
page = open("/tmp/t_rep_fr.html").read()
m = re.search(r'<pre class="code">(.*?)</pre>', page, re.S)
if not m:
    print("non"); raise SystemExit
block = html.unescape(m.group(1))
block = re.sub(r"</?script[^>]*>", "", block).strip()
try:
    data = json.loads(block)
    ok = data.get("@type") == "FAQPage" and len(data.get("mainEntity", [])) >= 1
    print("oui" if ok else "non")
except Exception:
    print("non")
PYEOF
)
ok "rapport FR : JSON-LD FAQPage valide (json.loads)" "$JLOK" "oui"
# /api/report : url_rescan + top_actions dans la reponse
has "api report FR : top_actions present" "$RFR" "top_actions"
has "api report FR : url_rescan presente" "$RFR" "url_rescan"
RESCAN_TOK=$(printf '%s' "$RFR" | python3 -c 'import sys,json; print((json.load(sys.stdin).get("url_rescan") or "").rsplit("/",1)[-1])' 2>/dev/null)
ok "rescan token extrait" "$([ -n "$RESCAN_TOK" ] && echo oui)" "oui"
ok "rescan J+30 : page 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/rescan/$RESCAN_TOK")" "200"
has "rescan J+30 : pas encore eligible (J+30)" "$(curl -s "$BASE/rescan/$RESCAN_TOK")" "disponible"
ok "rescan inconnu -> 404" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/rescan/token-inconnu-xxxxxxxx")" "404"

# --- 5a-bis. ANTI-TROU (recette t_72143dd9) : gel du texte rendu, aucune
# phrase du rapport ne doit contenir de trou (variable non injectee).
noholes() { # $1 = fichier HTML du rapport gelé
  python3 - "$1" <<'PYEOF'
import html, re, sys
raw = open(sys.argv[1], encoding="utf-8").read()
bad = []
if re.search(r"\{\{|\{%", raw): bad.append("gabarit Jinja non rendu")
if re.search(r"<strong>\s*</strong>", raw): bad.append("<strong> vide")
if re.search(r">\s*None\s*<", raw): bad.append("'None' injecte")
t = re.sub(r"<script.*?</script>", " ", raw, flags=re.S)
t = re.sub(r"<style.*?</style>", " ", t, flags=re.S)
t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
if re.search(r"\S  +[,:.;!?]", t): bad.append("double espace avant ponctuation")
for m in re.finditer(r"(à partir du|becomes active on)\s*\n?\s*([^\n<]*)", t):
    if not re.match(r"(\d{4}-\d{2}-\d{2}|J\+30|day 30)", m.group(2).strip()):
        bad.append("date re-scan absente apres: " + m.group(1))
for m in re.finditer(r"(Nous avons posé|We asked Perplexity)([^\n]*\n?[^\n]*)", t):
    if not re.search(r"\d+", m.group(0)):
        bad.append("compteurs verbatims absents")
print("TROU:" + "; ".join(bad) if bad else "OK")
PYEOF
}
ok "rapport FR : aucun trou (texte gele)" "$(noholes /tmp/t_rep_fr.html)" "OK"
ok "rapport FR : date re-scan J+30 injectee" \
  "$(printf '%s' "$HFR" | tr '\n' ' ' | grep -qE 'à partir du\s*<strong>[0-9]{4}-[0-9]{2}-[0-9]{2}</strong>' && echo oui)" "oui"
ok "rapport FR : compteurs verbatims injectes" \
  "$(printf '%s' "$HFR" | grep -qE 'posé <strong>[0-9]+ questions' && echo oui)" "oui"

REN=$(curl -s -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
      -d "{\"lang\":\"en\",\"audit\":$(cat /tmp/t_audit_en.json)}" "$BASE/api/report")
TOKEN_EN=$(printf '%s' "$REN" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
ok "rapport EN cree" "$([ -n "$TOKEN_EN" ] && echo oui)" "oui"
HEN=$(curl -s "$BASE/rapports/$TOKEN_EN")
has "rapport EN : titre EN" "$HEN" "AI Visibility Audit Report"
has "rapport EN : synthese affichee" "$HEN" "Executive summary"
has "rapport EN : synthese EN" "$HEN" "invisible to AI assistants"
has "rapport EN : detail EN" "$HEN" "without JavaScript"
hasnot "rapport EN : zero FR" "$HEN" "Rapport d'audit"
hasnot "rapport EN : jargon word count retire" "$HEN" "words</strong>"
hasnot "rapport EN : pas de compteur de mots brut" "$HEN" "words extractable"
has "rapport EN : analyzed sector (nouveau libelle)" "$HEN" "Analyzed sector"
# --- niveau 2 EN ---
has "rapport EN : top 3 actions" "$HEN" "Your top 3 priority actions"
has "rapport EN : roadmap 30/60/90" "$HEN" "30 / 60 / 90-day roadmap"
has "rapport EN : verbatims IA" "$HEN" "What the AI actually answers"
has "rapport EN : verbatim reel" "$HEN" "The best-rated artisan bakeries"
has "rapport EN : FAQ" "$HEN" "Your ready-to-publish FAQ"
has "rapport EN : JSON-LD FAQPage" "$HEN" "FAQPage"
has "rapport EN : CMS instruction (Custom Code)" "$HEN" "Custom Code"
has "rapport EN : rescan J+30" "$HEN" "Measure your progress in 30 days"
has "robots.txt : /rescan/ disallow" "$(curl -s "$BASE/robots.txt")" "Disallow: /rescan/"

printf '%s' "$HEN" > /tmp/t_rep_en.html
ok "rapport EN : aucun trou (texte gele)" "$(noholes /tmp/t_rep_en.html)" "OK"
ok "rapport EN : date re-scan J+30 injectee" \
  "$(printf '%s' "$HEN" | tr '\n' ' ' | grep -qE 'becomes active on\s*<strong>[0-9]{4}-[0-9]{2}-[0-9]{2}</strong>' && echo oui)" "oui"
ok "rapport EN : compteurs verbatims injectes" \
  "$(printf '%s' "$HEN" | grep -qE 'We asked Perplexity <strong>[0-9]+ buyer-intent' && echo oui)" "oui"

PDF=$(curl -s -o /tmp/t_rep.pdf -w "%{http_code}" "$BASE/rapports/$TOKFR/pdf")
ok "PDF FR -> 200" "$PDF" "200"
has "PDF FR : vrai PDF" "$(head -c 5 /tmp/t_rep.pdf)" "%PDF-"

# --- 5a-ter. MULTI-MOTEURS (t_9864864c) : pages offre + rapport multi ---
echo "--- multi-moteurs : pages offre (selecteur + verrou) ---"
ok "offre FR -> 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/offre.html")" "200"
ok "offre EN -> 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/en/offer.html")" "200"
OFFR=$(curl -s "$BASE/offre.html")
OFFEN=$(curl -s "$BASE/en/offer.html")
has "offre FR : selecteur present" "$OFFR" 'id="engine-select"'
has "offre FR : Perplexity+Gemini coches verrouilles" "$OFFR" 'checked disabled'
has "offre FR : extras chatgpt+claude" "$OFFR" 'class="eng-extra" value="chatgpt"'
has "offre FR : extra claude" "$OFFR" 'class="eng-extra" value="claude"'
has "offre FR : grille JS 29/39/49" "$OFFR" 'PRICE_LADDER = {0: 29, 1: 39, 2: 49}'
has "offre FR : prix dynamique id" "$OFFR" 'id="offer-price"'
has "offre FR : CTA verrouille" "$OFFR" 'btn--disabled'
hasnot "offre FR : aucun lien Stripe actif" "$OFFR" 'buy.stripe.com'
has "offre EN : selecteur present" "$OFFEN" 'id="engine-select"'
has "offre EN : grille JS" "$OFFEN" 'PRICE_LADDER'
hasnot "offre EN : aucun lien Stripe actif" "$OFFEN" 'buy.stripe.com'
ok "style.css sert engine-select" "$(curl -s "$BASE/assets/style.css" | grep -c 'engine-select')" "6"

echo "--- multi-moteurs : rapport multi (fixture, sans cout) ---"
cat > /tmp/t_audit_multi.json <<'EOF'
{"domain": "https://boulangerie-martin.fr", "lang": "fr", "keyword": "boulangerie artisanale",
 "score": {"total": 55, "technical": 55, "citation": 25, "mode": "full"},
 "technical": {"score": 55, "word_count": 180, "checks": {
   "robots": {"status": "warn", "points": 15, "detail": "robots.txt introuvable — les bots IA sont autorisés par défaut", "bots": {}},
   "extract": {"status": "warn", "points": 20, "detail": "contenu textuel un peu mince"},
   "jsonld": {"status": "warn", "points": 5, "detail": "aucune donnée structurée JSON-LD"},
   "eeat": {"status": "warn", "points": 10, "detail": "dates de publication présentes",
            "signals": ["dates de publication présentes"], "missing": [],
            "signal_codes": ["dates"], "missing_codes": []}}},
 "citations": {"status": "partial", "queries_ok": 4, "total": 6, "cited_count": 1,
   "queries": [
     {"query": "Quel est le meilleur boulangerie artisanale ?", "cited": true, "error": null,
      "citations": ["capterra.com"], "verbatim": "Perplexity cite cette boulangerie en premier.",
      "by_engine": {"perplexity": "yes", "gemini": "no", "claude": "error"}},
     {"query": "Où acheter boulangerie artisanale en ligne ?", "cited": false, "error": null,
      "citations": ["capterra.com"], "verbatim": "Les annuaires dominent les réponses.",
      "by_engine": {"perplexity": "no", "gemini": "no", "claude": "error"}}],
   "competitors": [{"domain": "capterra.com", "count": 3}],
   "competitor_urls": {"capterra.com": "https://capterra.com/x"},
   "cost_usd": 0.02, "engine": "multi:perplexity,gemini,claude",
   "engines_run": ["perplexity", "gemini", "claude"],
   "engines_missing": ["chatgpt"],
   "matrix": [
     {"query": "Quel est le meilleur boulangerie artisanale ?",
      "by_engine": {"perplexity": "yes", "gemini": "no", "claude": "error"}},
     {"query": "Où acheter boulangerie artisanale en ligne ?",
      "by_engine": {"perplexity": "no", "gemini": "no", "claude": "error"}}],
   "engines": {
     "perplexity": {"status": "ok", "queries_ok": 2, "total": 2, "cited_count": 1,
       "queries": [
         {"query": "Quel est le meilleur boulangerie artisanale ?", "cited": true, "error": null,
          "citations": ["capterra.com"], "verbatim": "Perplexity cite cette boulangerie en premier."},
         {"query": "Où acheter boulangerie artisanale en ligne ?", "cited": false, "error": null,
          "citations": ["capterra.com"], "verbatim": "Les annuaires dominent les réponses."}],
       "competitors": [{"domain": "capterra.com", "count": 2}], "competitor_urls": {},
       "cost_usd": 0.01, "engine": "perplexity", "engine_label": "Perplexity"},
     "gemini": {"status": "ok", "queries_ok": 2, "total": 2, "cited_count": 0,
       "queries": [
         {"query": "Quel est le meilleur boulangerie artisanale ?", "cited": false, "error": null,
          "citations": ["capterra.com"], "verbatim": "Gemini privilégie les comparatifs locaux."},
         {"query": "Où acheter boulangerie artisanale en ligne ?", "cited": false, "error": null,
          "citations": [], "verbatim": "Gemini ne cite pas cette boulangerie."}],
       "competitors": [], "competitor_urls": {},
       "cost_usd": 0.01, "engine": "gemini", "engine_label": "Gemini"},
     "claude": {"status": "failed", "queries_ok": 0, "total": 2, "cited_count": 0,
       "queries": [
         {"query": "Quel est le meilleur boulangerie artisanale ?", "cited": false,
          "error": "HTTP 500", "citations": [], "verbatim": ""},
         {"query": "Où acheter boulangerie artisanale en ligne ?", "cited": false,
          "error": "HTTP 500", "citations": [], "verbatim": ""}],
       "competitors": [], "competitor_urls": {},
       "cost_usd": 0.0, "engine": "claude", "engine_label": "Claude"}}},
 "cms": {"cms": "wordpress", "label": "WordPress", "instruction": "WordPress détecté."},
 "platforms": [],
 "deliverables": {"pourquoi_cites": [], "actions_contenu": [], "faq": [], "faq_jsonld": "",
   "roadmap": {"j30": ["Publier la FAQ"], "j60": ["Créer le guide"], "j90": ["S'inscrire"]},
   "roadmap_source": "v4-pro", "competitor_pages": [], "writer": "deepseek/deepseek-v4-pro-0813"},
 "action_plan": [{"action": "Ajouter des données structurées JSON-LD.", "impact": 8, "effort": 3, "priority_score": 2.7, "rank": 1}],
 "synthese": "Rapport multi-moteurs de test.",
 "writer": "deepseek/deepseek-v4-pro-0813",
 "engines": ["perplexity", "gemini", "claude"],
 "mode": "full", "generated_at": "2026-08-24T00:00:00Z"}
EOF
RMULTI=$(curl -s -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
      -d "{\"lang\":\"fr\",\"audit\":$(cat /tmp/t_audit_multi.json)}" "$BASE/api/report")
TOKM=$(printf '%s' "$RMULTI" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
ok "rapport multi cree" "$([ -n "$TOKM" ] && echo oui)" "oui"
HM=$(curl -s "$BASE/rapports/$TOKM")
printf '%s' "$HM" > /tmp/t_rep_multi.html
has "multi : section visibilite par moteur" "$HM" "Visibilité par moteur d'IA"
has "multi : colonnes moteurs" "$HM" "<th>Perplexity</th><th>Gemini</th><th>Claude</th>"
has "multi : section ecarts" "$HM" "Écarts entre moteurs"
has "multi : ecart cite perplexity pas gemini" "$HM" "cité par Perplexity mais pas par Gemini"
has "multi : verbatims par moteur" "$HM" "verbatims par moteur"
has "multi : verbatim perplexity" "$HM" "Perplexity cite cette boulangerie en premier."
has "multi : verbatim gemini" "$HM" "Gemini privilégie les comparatifs locaux."
has "multi : moteur en panne mentionne" "$HM" "Claude était indisponible lors de l'audit"
has "multi : moteur sans cle mentionne" "$HM" "ChatGPT"
has "multi : mesures requete x moteur" "$HM" "mesures requête × moteur"
ok "rapport multi : aucun trou (texte gele)" "$(noholes /tmp/t_rep_multi.html)" "OK"
PDFM=$(curl -s -o /tmp/t_rep_multi.pdf -w "%{http_code}" "$BASE/rapports/$TOKM/pdf")
ok "rapport multi : PDF -> 200" "$PDFM" "200"
has "rapport multi : vrai PDF" "$(head -c 5 /tmp/t_rep_multi.pdf)" "%PDF-"

# API : parametre engines accepte (audit fixture multi relu cote API)
has "api report multi : token + rescan" "$RMULTI" "url_rescan"

# --- 5b. NON-REGRESSION SECTEUR (pipeline reel brozapi.com, ~0,20 $ Sonar+V4) ---
# Recette t_ffc46988 : le rapport sur brozapi.com (studio de LOGICIELS) ne doit
# citer AUCUN site de bricolage/outillage et le secteur affiche doit etre la
# formulation precise validee par le garde-fou Sonar. SKIP_LIVE=1 pour sauter.
echo "--- non-regression secteur brozapi.com (pipeline reel) ---"
if [ "${SKIP_LIVE:-0}" = "1" ]; then
  echo "SKIP tests live (SKIP_LIVE=1)"
else
  # Les 2 audits live (FR + EN) tournent EN PARALLELE (t_a857e039) : le pipeline
  # niveau 2 dure ~5-6 min par audit, sequentiel on depassait le timeout 570s
  # de la porte SSH. Le compteur de cout est isole par audit (contextvar).
  echo ">>> lancement des 2 audits live FR+EN en parallele (~6 min, ~0,25 $ total)"
  curl -s --max-time 540 -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
    -d '{"url":"https://brozapi.com","lang":"fr"}' "$BASE/api/report" > /tmp/t_rreal.json &
  PID_FR=$!
  curl -s --max-time 540 -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" \
    -d '{"url":"https://brozapi.com","lang":"en"}' "$BASE/api/report" > /tmp/t_renl.json &
  PID_EN=$!
  wait $PID_FR $PID_EN
  RREAL=$(cat /tmp/t_rreal.json)
  RENL=$(cat /tmp/t_renl.json)

  TOKREAL=$(printf '%s' "$RREAL" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
  ok "rapport reel FR cree" "$([ -n "$TOKREAL" ] && echo oui)" "oui"
  HREAL=$(curl -s "$BASE/rapports/$TOKREAL")
  printf '%s' "$HREAL" > /tmp/t_real_fr.html
  has "reel FR : secteur analyse affiche" "$HREAL" "Secteur analysé"
  hasnot "reel FR : secteur PAS 'micro-outils'" "$HREAL" "Secteur analysé : « micro-outils »"
  hasnot "reel FR : aucun site bricolage (leroymerlin)" "$HREAL" "leroymerlin"
  hasnot "reel FR : aucun site bricolage (tivoly)" "$HREAL" "tivoly"
  hasnot "reel FR : aucun site bricolage (doga)" "$HREAL" "doga.fr"
  hasnot "reel FR : aucun site bricolage (bosch)" "$HREAL" "bosch"
  hasnot "reel FR : aucun site bricolage (dremel)" "$HREAL" "dremel"
  hasnot "reel FR : aucun site bricolage (milwaukee)" "$HREAL" "milwaukee"
  has "reel FR : vrai tableau HTML des requetes" "$HREAL" "<table>"
  has "reel FR : colonne Requete testee" "$HREAL" "Requête testée"
  has "reel FR : colonne Votre site cite" "$HREAL" "Votre site cité ?"
  has "reel FR : colonne Concurrents cites" "$HREAL" "Concurrents cités"
  hasnot "reel FR : pas de markdown brut (pipes)" "$HREAL" "| ---"
  hasnot "reel FR : pas de compteur de mots" "$HREAL" "mots extractibles"
  # niveau 2 (t_a857e039) sur pipeline reel
  has "reel FR : verbatims IA" "$HREAL" "Ce que l'IA répond vraiment"
  has "reel FR : roadmap 30/60/90" "$HREAL" "Feuille de route 30 / 60 / 90 jours"
  has "reel FR : FAQ prete a publier" "$HREAL" "Votre FAQ prête à publier"
  has "reel FR : JSON-LD FAQPage" "$HREAL" "FAQPage"
  has "reel FR : 3 contenus titre+angle" "$HREAL" "titres et angles fournis"
  has "reel FR : lien rescan J+30" "$HREAL" "/rescan/"
  # garde-fou budget : cout total mesure affiche, seuil 0,50 $ (t_a857e039)
  COST=$(printf '%s' "$RREAL" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("cost_usd"))' 2>/dev/null)
  echo ">>> COUT REEL DE L'AUDIT (Sonar + V4 pro + fetches) : ${COST:-inconnu} USD (seuil 0.50)"
  COSTOK=$(python3 -c "c='$COST'; print('oui' if c and c != 'None' and float(c) <= 0.50 else 'non')" 2>/dev/null)
  ok "cout audit <= 0.50 USD" "$COSTOK" "oui"
  PDFR=$(curl -s -o /tmp/t_real_fr.pdf -w "%{http_code}" "$BASE/rapports/$TOKREAL/pdf")
  ok "reel FR : PDF -> 200" "$PDFR" "200"
  has "reel FR : vrai PDF" "$(head -c 5 /tmp/t_real_fr.pdf)" "%PDF-"
  ok "reel FR : aucun trou (texte gele)" "$(noholes /tmp/t_real_fr.html)" "OK"

  # Rapport live EN (lance en parallele ci-dessus) — memes controles niveau 2
  echo "--- live EN (pipeline reel brozapi.com) ---"
  TOKRENL=$(printf '%s' "$RENL" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))' 2>/dev/null)
  ok "rapport reel EN cree" "$([ -n "$TOKRENL" ] && echo oui)" "oui"
  HENL=$(curl -s "$BASE/rapports/$TOKRENL")
  printf '%s' "$HENL" > /tmp/t_real_en.html
  has "reel EN : titre EN" "$HENL" "AI Visibility Audit Report"
  has "reel EN : verbatims IA" "$HENL" "What the AI actually answers"
  has "reel EN : roadmap 30/60/90" "$HENL" "30 / 60 / 90-day roadmap"
  has "reel EN : FAQ prete" "$HENL" "Your ready-to-publish FAQ"
  has "reel EN : JSON-LD FAQPage" "$HENL" "FAQPage"
  has "reel EN : lien rescan J+30" "$HENL" "/rescan/"
  hasnot "reel EN : aucun site bricolage (leroymerlin)" "$HENL" "leroymerlin"
  PDFEN=$(curl -s -o /tmp/t_real_en.pdf -w "%{http_code}" "$BASE/rapports/$TOKRENL/pdf")
  ok "reel EN : PDF -> 200" "$PDFEN" "200"
  has "reel EN : vrai PDF" "$(head -c 5 /tmp/t_real_en.pdf)" "%PDF-"
  ok "reel EN : aucun trou (texte gele)" "$(noholes /tmp/t_real_en.html)" "OK"
  echo "$TOKREAL $TOKRENL" > /tmp/t_live_tokens.txt
fi

# --- 6. Site public (DNS + Caddy) ---
echo "--- public ---"
ok "public / 200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUB/")" "200"
ok "public /fr/ 200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUB/fr/")" "200"
has "public /fr/ en francais" "$(curl -s --max-time 15 "$PUB/fr/")" "Votre site est-il cité"

echo "===== RESULTAT : $PASS PASS, $FAIL FAIL ====="
[ "$FAIL" -eq 0 ]
