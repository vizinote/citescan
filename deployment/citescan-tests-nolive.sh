#!/bin/bash
# Wrapper (t_74e5bb97) : recette complete SAUF les audits live (~1 min).
# Log complet dans /tmp (la porte ne renvoie que tail -40) ; n'imprime que
# les FAIL + le RESULTAT.
SKIP_LIVE=1 bash /root/citescan-tests.sh > /tmp/citescan-nolive.log 2>&1
RC=$?
grep -E "^FAIL" /tmp/citescan-nolive.log
grep "RESULTAT" /tmp/citescan-nolive.log
exit $RC
