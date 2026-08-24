#!/bin/bash
# Wrapper (t_74e5bb97) : uniquement les 2 audits live FR+EN + site public
# (~9-10 min, ~1,30 $). La porte SSH rejette les args — ce wrapper pose
# la variable d'env.
exec env LIVE_ONLY=1 bash /root/citescan-tests.sh
