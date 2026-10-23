#!/usr/bin/env bash
# The decisive test end to end on one GPU machine (neo4d/decisive.py). Two environments, so vLLM's and TRL's pins never
# meet: /root/venv-vllm (sampling, generation, EvalPlus) and /root/venv-train (TRL + PEFT). Resumable step by step.
set -euo pipefail
cd /root/neo4d && export DECISIVE_DIR=/root/decisive
V=/root/venv-vllm/bin/python; T=/root/venv-train/bin/python
[ -f $DECISIVE_DIR/pool.jsonl ] || $V -m neo4d.decisive sample
[ -f $DECISIVE_DIR/pool_checked.jsonl ] || $V -m neo4d.decisive check
[ -f $DECISIVE_DIR/search.jsonl ] || $V -m neo4d.decisive search
$V -m neo4d.decisive datasets
[ -f $DECISIVE_DIR/samples/base_mbpp_eval_results.json ] || { $V -m neo4d.decisive generate --arm base; $V -m neo4d.decisive evaluate --arm base; }
for s in 0 1 2; do for arm in sample16 sample64 neo4d neo4d_ship; do
  [ -f $DECISIVE_DIR/adapters/${arm}_s$s/adapter_config.json ] || $T -m neo4d.decisive train --arm $arm --seed $s
  [ -f $DECISIVE_DIR/samples/${arm}_s${s}_mbpp_eval_results.json ] || { $V -m neo4d.decisive generate --arm $arm --seed $s; $V -m neo4d.decisive evaluate --arm $arm --seed $s; }
done; done
$V -m neo4d.decisive report
echo DECISIVE_DONE
