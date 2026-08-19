# Goldilocks field inversion chain

This task measures deterministic field-operation work that appears in proof-system exponentiation.

The task fixes the Goldilocks prime, a base, and the inversion exponent `p - 2`.
Participants submit an addition chain for that exponent.
The exact checker counts one modular multiplication for each chain step.

The repository contains a real starter layout:

- `task.json` defines the machine-readable task.
- `task-config.json` fixes the field, base, exponent, and chain limit.
- `candidate.json` is the participant starter at the generic manifest path.
- `starter/candidate.json` preserves the published 125-step binary baseline.
- `baseline/candidate.json` records that same baseline.
- `result/candidate.json` records an 83-step width-4 candidate.
- `field-exponent-v1.py` performs the exact check.
- `agent-prompt.md` contains the participant instructions.

Run the checker from this directory:

```bash
python3 field-exponent-v1.py \
  --check candidate.json \
  --config task-config.json \
  --baseline 125
```

`task-config.json` contains only the fixed task inputs.
Keep repository and pull-request provenance in the competition participation fields, not in this task configuration.
The canonical config bytes used by `task.configRef` are:

```text
{"base":7,"exponent":18446744069414584319,"max_chain_length":256,"metric":"field_multiplications","modulus":18446744069414584321,"schema_version":1}
```

Their SHA-256 is `74214de0c60a05d38131de0e0fd9044234be204123a3bfc42788340000fdec99`.

The task accepts an exact chain with at most 83 steps.
A chain below 83 steps takes the record.
The published 83-step result reduces the binary baseline by 42 multiplications.
It is a measured candidate, not a proof of optimality.
