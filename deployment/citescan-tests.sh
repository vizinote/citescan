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
 "score": {"total": 55, "technical": 55, "citation": null, "mode": "degraded"},
 "technical": {"score": 55, "word_count": 180, "checks": {
   "robots": {"status": "warn", "points": 15, "detail": "robots.txt introuvable — les bots IA sont autorisés par défaut", "bots": {}},
   "extract": {"status": "warn", "points": 20, "detail": "seulement 180 mots extractibles sans JavaScript"},
   "jsonld": {"status": "warn", "points": 5, "detail": "aucune donnée structurée JSON-LD"},
   "eeat": {"status": "warn", "points": 10, "detail": "dates de publication présentes; pas de page à propos / mentions légales",
            "signals": ["dates de publication présentes"], "missing": ["pas de page à propos / mentions légales"],
            "signal_codes": ["dates"], "missing_codes": ["about", "author"]}}},
 "citations": {"status": "unavailable", "reason": "PERPLEXITY_API_KEY non définie — mode dégradé (audit technique seul)",
               "queries": [], "cited_count": 0, "total": 0, "competitors": []},
 "action_plan": [{"action": "Ajouter des données structurées JSON-LD sur la page d'accueil.", "impact": 8, "effort": 3, "priority_score": 2.7, "rank": 1}],
 "synthese": "Votre site est techniquement solide mais reste invisible des IA. Ce rapport priorise les actions à mener.",
 "writer": "deepseek/deepseek-v4-pro-0813",
 "mode": "degraded", "generated_at": "2026-08-24T00:00:00Z"}
EOF
cat > /tmp/t_audit_en.json <<'EOF'
{"domain": "https://acme-bakery.com", "lang": "en", "keyword": "artisan bakery",
 "score": {"total": 55, "technical": 55, "citation": null, "mode": "degraded"},
 "technical": {"score": 55, "word_count": 180, "checks": {
   "robots": {"status": "warn", "points": 15, "detail": "robots.txt not found — AI bots default to allowed", "bots": {}},
   "extract": {"status": "warn", "points": 20, "detail": "only 180 words extractable without JavaScript"},
   "jsonld": {"status": "warn", "points": 5, "detail": "no JSON-LD structured data"},
   "eeat": {"status": "warn", "points": 10, "detail": "dates present; no about/legal page",
            "signals": ["dates present"], "missing": ["no about/legal page"],
            "signal_codes": ["dates"], "missing_codes": ["about", "author"]}}},
 "citations": {"status": "unavailable", "reason": "PERPLEXITY_API_KEY not set — degraded mode (technical audit only)",
               "queries": [], "cited_count": 0, "total": 0, "competitors": []},
 "action_plan": [{"action": "Add JSON-LD structured data on the homepage and key pages.", "impact": 8, "effort": 3, "priority_score": 2.7, "rank": 1}],
 "synthese": "Your site is technically sound but invisible to AI assistants. This report prioritizes what to do next.",
 "writer": "deepseek/deepseek-v4-pro-0813",
 "mode": "degraded", "generated_at": "2026-08-24T00:00:00Z"}
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
has "rapport FR : plan FR" "$HFR" "Plan d'action priorisé"
hasnot "rapport FR : zero anglais technique" "$HFR" "without JS"
hasnot "rapport FR : zero anglais detail" "$HFR" "not found — AI bots"
hasnot "rapport FR : jargon word count retire" "$HFR" "mots</strong>"

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

PDF=$(curl -s -o /tmp/t_rep.pdf -w "%{http_code}" "$BASE/rapports/$TOKFR/pdf")
ok "PDF FR -> 200" "$PDF" "200"
has "PDF FR : vrai PDF" "$(head -c 5 /tmp/t_rep.pdf)" "%PDF-"

# --- 6. Site public (DNS + Caddy) ---
echo "--- public ---"
ok "public / 200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUB/")" "200"
ok "public /fr/ 200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$PUB/fr/")" "200"
has "public /fr/ en francais" "$(curl -s --max-time 15 "$PUB/fr/")" "Votre site est-il cité"

echo "===== RESULTAT : $PASS PASS, $FAIL FAIL ====="
[ "$FAIL" -eq 0 ]
