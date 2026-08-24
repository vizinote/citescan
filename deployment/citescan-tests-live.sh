#!/bin/bash
# Wrapper (t_74e5bb97) : uniquement les 2 audits live FR+EN + site public
# (~9-10 min, ~1,30 $). Log complet dans /tmp (la porte ne renvoie que
# tail -40) ; n'imprime que les FAIL + le RESULTAT.
LIVE_ONLY=1 bash /root/citescan-tests.sh > /tmp/citescan-live.log 2>&1
RC=$?
grep -E "^FAIL" /tmp/citescan-live.log
grep "RESULTAT" /tmp/citescan-live.log
exit $RC
