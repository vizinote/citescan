#!/bin/bash
# Inspect the latest CiteScan reports in prod DB + check rendered HTML for holes.
set -u
DB=$(docker exec citescan-citescan-api-1 sh -c 'echo ${CITESCAN_DB:-/data/citescan.db}')
echo "== DB: $DB"
echo "== latest reports:"
docker exec citescan-citescan-api-1 python3 - "$DB" <<'EOF'
import sqlite3, sys, json
db = sys.argv[1]
conn = sqlite3.connect(db)
rows = conn.execute("SELECT token, domain, lang, created_at FROM reports ORDER BY created_at DESC LIMIT 5").fetchall()
for r in rows:
    print(r)
print("== rescans:")
for r in conn.execute("SELECT token, parent_token, domain, lang, eligible_at, status FROM rescans ORDER BY created_at DESC LIMIT 5").fetchall():
    print(r)
EOF
