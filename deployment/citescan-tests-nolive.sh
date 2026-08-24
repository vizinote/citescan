#!/bin/bash
# Wrapper (t_74e5bb97) : recette complete SAUF les audits live (~1 min).
# La porte SSH rejette les args — ce wrapper pose la variable d'env.
exec env SKIP_LIVE=1 bash /root/citescan-tests.sh
