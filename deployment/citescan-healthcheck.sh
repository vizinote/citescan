#!/usr/bin/env bash
set -uo pipefail
# Healthcheck CiteScan avec auto-remediation niveau 1 (modele badgeia-healthcheck.sh).
# API en local (bind 127.0.0.1:8083, non exposee). Alerte Telegram sur changement d'etat.
#
# Regle de remediation (correctif 2026-08-24) :
#  - restart du conteneur UNIQUEMENT si le conteneur est absent ou l'API LOCALE morte.
#    Un restart ne repare ni le DNS ni Caddy, et il TUE un audit payant en cours
#    (incident du 24/08 : un rapport en generation a ete interrompu par un restart
#    declenche par un faux negatif du controle public en HEAD -> 405).
#  - echec du controle public => alerte Telegram SANS restart.
API_LOCAL="http://127.0.0.1:8083/health"
PUBLIC_URL="https://citescan.brozapi.com"
STATE_FILE="/root/.healthcheck-citescan.state"
CHAT_ID="7750866970"
CONTAINER="citescan-citescan-api-1"
ERR=0; LOCAL_FAIL=0; DETAILS=""; REMED=""

fail()  { echo "[FAIL] $1"; ERR=1; DETAILS="${DETAILS}$1 — "; }
lfail() { echo "[FAIL] $1"; ERR=1; LOCAL_FAIL=1; DETAILS="${DETAILS}$1 — "; }
ok()    { echo "[OK] $1"; }

check_all() {
  ERR=0; LOCAL_FAIL=0; DETAILS=""
  HEALTH=$(curl -fsS --max-time 15 "${API_LOCAL}" 2>/dev/null || true)
  if [ -z "$HEALTH" ]; then lfail "API locale ne repond pas sur ${API_LOCAL}"; else ok "API locale: $HEALTH"; fi
  # URL publique : verifiee seulement quand le DNS est en place (creation zone OVH = action Franck)
  if getent hosts citescan.brozapi.com >/dev/null 2>&1; then
    if ! curl -fsS -o /dev/null --max-time 15 "${PUBLIC_URL}/" 2>/dev/null; then
      fail "Site public ${PUBLIC_URL}/ ne repond pas"
    else
      ok "Site public repond"
    fi
  else
    ok "DNS citescan.brozapi.com pas encore cree (action Franck) — controle public saute"
  fi
  if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then ok "Conteneur ${CONTAINER} en cours"; else lfail "Conteneur ${CONTAINER} non trouve"; fi
}

check_all
if [ "$ERR" = 1 ] && [ "$LOCAL_FAIL" = 1 ]; then
  echo "[REMEDIATION] tentative de reparation automatique (panne locale)"
  if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    docker start "$CONTAINER" >/dev/null 2>&1 && REMED="conteneur relance (docker start). "
  else
    docker restart "$CONTAINER" >/dev/null 2>&1 && REMED="conteneur redemarre (docker restart). "
  fi
  sleep 12
  check_all
  [ "$ERR" = 0 ] && echo "[REMEDIATION] reussie" || echo "[REMEDIATION] insuffisante"
elif [ "$ERR" = 1 ]; then
  echo "[REMEDIATION] non applicable (panne publique uniquement — restart inutile, alerte seule)"
fi

PREV=$(cat "$STATE_FILE" 2>/dev/null || echo "OK")
CUR="OK"; [ "$ERR" = 1 ] && CUR="FAIL"
if [ "$CUR" != "$PREV" ]; then
  TOK=$(grep -iE 'TELEGRAM' /root/.hermes/.env | grep -oE '[0-9]{8,}:[A-Za-z0-9_-]{30,}' | head -1)
  if [ -n "$TOK" ]; then
    if [ "$CUR" = "FAIL" ]; then
      MSG="🔴 CiteScan en panne malgre la reparation automatique (${REMED:-non applicable}) : ${DETAILS}controles toutes les 5 min."
    else
      MSG="✅ CiteScan retabli. ${REMED:+Reparation automatique appliquee : ${REMED}}"
    fi
    curl -s --max-time 10 -X POST "https://api.telegram.org/bot${TOK}/sendMessage" -d chat_id="${CHAT_ID}" --data-urlencode text="${MSG}" >/dev/null || true
  fi
fi
echo "$CUR" > "$STATE_FILE"
exit "$ERR"
