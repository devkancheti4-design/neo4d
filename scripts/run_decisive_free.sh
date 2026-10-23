#!/usr/bin/env bash
# Run 2 of the decisive test: neo4d with freedom on the tasks 64 samples missed, against sampling 4x more.
set -euo pipefail
cd /root/neo4d && export DECISIVE_DIR=/root/decisive
V=/root/venv-vllm/bin/python; T=/root/venv-train/bin/python
[ -f $DECISIVE_DIR/pool_more_checked.jsonl ] || $V -m neo4d.decisive sample_more
[ -f $DECISIVE_DIR/search_free.jsonl ] || $V -m neo4d.decisive search_free
$V -m neo4d.decisive datasets_free
$V -m neo4d.decisive purity_free
for s in 0 1 2; do for arm in sample256 neo4d_free neo4d_free_ship; do
  [ -f $DECISIVE_DIR/adapters/${arm}_s$s/adapter_config.json ] || $T -m neo4d.decisive train --arm $arm --seed $s
  [ -f $DECISIVE_DIR/samples/${arm}_s${s}_mbpp_eval_results.json ] || { $V -m neo4d.decisive generate --arm $arm --seed $s; $V -m neo4d.decisive evaluate --arm $arm --seed $s; }
done; done
$V -m neo4d.decisive report_free
echo DECISIVE_FREE_DONE
