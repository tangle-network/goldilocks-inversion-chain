# Goldilocks field inversion chain

Find an exact addition chain with at most 83 steps.
A chain below 83 steps takes the record.

Use the fixed task configuration:

- modulus `p = 18446744069414584321`
- base `x = 7`
- exponent `p - 2 = 18446744069414584319`

Submit `candidate.json` with this shape:

```json
{
  "schema_version": 1,
  "kind": "addition-chain",
  "chain": [1, 2, 3]
}
```

The chain must start at `1`, end at `p - 2`, and increase strictly.
Each new value must equal the sum of two earlier chain values.
The score is the number of chain steps.

Run the exact checker before submission:

```bash
python3 field-exponent-v1.py \
  --check candidate.json \
  --config task-config.json \
  --baseline 125
```

The checker replays the chain modulo `p` and compares it with an exact reference.
It rejects invalid chains, incorrect results, and altered evidence.

The published 125-step binary chain is the baseline.
The published 83-step chain is accepted as the current record.
It is a measured candidate, not a proof of optimality.
