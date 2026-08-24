#!/bin/bash
# inject-ai-keys.sh — synchronise les clés des moteurs IA (t_9864864c) depuis
# /opt/data/.env vers /root/.hermes/citescan.env, idempotent.
# Usage : run-script inject-ai-keys.sh
# Après injection des NOUVELLES clés, redéployer (citescan-redeploy.sh) ou
# redémarrer le conteneur pour que l'env soit relu.
set -u
SRC=/opt/data/.env
DST=/root/.hermes/citescan.env
KEYS="OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY MISTRAL_API_KEY"
CHANGED=0

[ -f "$SRC" ] || { echo "ERREUR: $SRC absent"; exit 1; }
touch "$DST"

for K in $KEYS; do
  V=$(grep -E "^${K}=" "$SRC" | head -1 | cut -d= -f2-)
  [ -z "$V" ] && continue
  if grep -qE "^${K}=" "$DST"; then
    CUR=$(grep -E "^${K}=" "$DST" | head -1 | cut -d= -f2-)
    if [ "$CUR" != "$V" ]; then
      sed -i "s|^${K}=.*|${K}=${V}|" "$DST"
      echo "MAJ $K"
      CHANGED=1
    else
      echo "OK  $K (déjà à jour)"
    fi
  else
    echo "${K}=${V}" >> "$DST"
    echo "ADD $K"
    CHANGED=1
  fi
done

if [ "$CHANGED" = "1" ]; then
  # ATTENTION : env_file n'est relu qu'à la (re)création du conteneur.
  # `docker restart` ne recharge PAS l'env — il faut `compose up -d` (recreate).
  echo "clés modifiées — recréation du conteneur pour recharger l'env"
  docker compose -p citescan -f /opt/data/repos/citescan/deployment/docker-compose.yml up -d
else
  echo "aucune modification"
fi
