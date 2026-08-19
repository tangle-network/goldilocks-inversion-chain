# Goldilocks field inversion chain

This task measures deterministic field-operation work that appears in proof-system exponentiation.

The task fixes the Goldilocks prime, a base, and the inversion exponent `p - 2`.
Participants submit an addition chain for that exponent.
The exact checker counts one modular multiplication for each chain step.

The repository contains a real starter layout:

- `task.json` defines the machine-readable task.
- `task-config.json` fixes the field, base, exponent, and chain limit.
- `starter/candidate.json` is the published 125-step binary baseline.
- `baseline/candidate.json` records that same baseline.
- `result/candidate.json` records an 83-step width-4 candidate.
- `field-exponent-v1.py` performs the exact check.
- `agent-prompt.md` contains the participant instructions.

Run the checker from this directory:

```bash
python3 field-exponent-v1.py \
  --check starter/candidate.json \
  --config task-config.json \
  --baseline 125
```

The published 83-step result reduces the binary baseline by 42 multiplications.
It is a measured candidate, not a proof of optimality.

If you include source provenance, use only the public repository commit or pull-request URL.
