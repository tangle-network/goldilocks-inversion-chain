#!/usr/bin/env python3
"""Check finite-field addition chains and count their exact CPU work.

The task fixes a field, base, and exponent. A candidate supplies an addition
chain for the exponent. Each chain step is one modular multiplication or
square, so the ranking metric is deterministic across operator hardware.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import re
import sys


ADAPTER_REF = "task:field-exponent-v1"
EVALUATOR_REF = "evaluator:field-exponent-v1"
TASK_PREFIX = "field-exponent:task:"
CANDIDATE_PREFIX = "field-exponent:candidate:"
BASELINE_PREFIX = "field-exponent:baseline:"
METRIC = "field_multiplications"
MAX_CONFIG_BYTES = 16 * 1024
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_INPUT_BYTES = 256 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024
MAX_CHAIN_LENGTH = 512
MAX_EXPONENT = 2**64 - 1
PROVENANCE_REF_RE = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}/"
    r"(?:commit/[0-9a-f]{40}|pull/[1-9][0-9]{0,8})$"
)
MAX_PROVENANCE_REFS = 8
MAX_PROVENANCE_REF_BYTES = 256


class EvaluationError(ValueError):
    """A task, candidate, or evidence record failed closed validation."""


def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise EvaluationError(f"JSON object repeats field {key!r}")
        value[key] = item
    return value


def parse_json(raw, label):
    try:
        return json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is not valid JSON") from error


def encode_reference(prefix, value):
    encoded = base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{prefix}{encoded}"


def decode_reference(reference, prefix, limit, label):
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise EvaluationError(f"{label} reference must start with {prefix}")
    encoded = reference[len(prefix) :]
    if not encoded or len(encoded) > limit * 2:
        raise EvaluationError(f"{label} reference has an invalid size")
    if any(
        character
        not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in encoded
    ):
        raise EvaluationError(f"{label} reference is not unpadded base64url")
    try:
        value = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError) as error:
        raise EvaluationError(f"{label} reference is not valid base64url") from error
    if not value or len(value) > limit:
        raise EvaluationError(f"{label} reference has an invalid decoded size")
    return value


def require_int(value, label, minimum=None, maximum=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise EvaluationError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise EvaluationError(f"{label} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise EvaluationError(f"{label} must be at most {maximum}")
    return value


def require_exact_keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise EvaluationError(f"{label} has invalid fields")


def validate_config(config):
    require_exact_keys(
        config,
        {"schema_version", "modulus", "base", "exponent", "metric", "max_chain_length"},
        "task config",
    )
    if config["schema_version"] != 1:
        raise EvaluationError("unsupported task config schema_version")
    modulus = require_int(config["modulus"], "task config modulus", 3, MAX_EXPONENT)
    if modulus % 2 == 0:
        raise EvaluationError("task config modulus must be odd")
    base = require_int(config["base"], "task config base", 2)
    if base >= modulus:
        raise EvaluationError("task config base must be less than modulus")
    exponent = require_int(config["exponent"], "task config exponent", 2, MAX_EXPONENT)
    if config["metric"] != METRIC:
        raise EvaluationError(f"task config metric must be {METRIC}")
    max_chain_length = require_int(
        config["max_chain_length"], "task config max_chain_length", 2, MAX_CHAIN_LENGTH
    )
    return {
        "schema_version": 1,
        "modulus": modulus,
        "base": base,
        "exponent": exponent,
        "metric": METRIC,
        "max_chain_length": max_chain_length,
    }


def validate_candidate(candidate, config):
    require_exact_keys(candidate, {"schema_version", "kind", "chain"}, "candidate")
    if candidate["schema_version"] != 1 or candidate["kind"] != "addition-chain":
        raise EvaluationError("candidate does not match the addition-chain schema")
    chain = candidate["chain"]
    if not isinstance(chain, list) or not chain:
        raise EvaluationError("candidate chain must be a non-empty list")
    if len(chain) > config["max_chain_length"]:
        raise EvaluationError("candidate chain exceeds the task limit")
    for index, value in enumerate(chain):
        require_int(value, f"candidate chain[{index}]", 1, config["exponent"])
    if chain[0] != 1:
        raise EvaluationError("candidate chain must start with 1")
    if chain[-1] != config["exponent"]:
        raise EvaluationError("candidate chain must end at the task exponent")
    if any(left >= right for left, right in zip(chain, chain[1:])):
        raise EvaluationError("candidate chain must be strictly increasing")
    return {"schema_version": 1, "kind": "addition-chain", "chain": chain}


def find_sum_pair(chain, value):
    prior = set(chain)
    for left in chain:
        right = value - left
        if right in prior and right <= left:
            return left, right
    raise EvaluationError(f"chain value {value} is not the sum of two prior values")


def replay_chain(config, chain):
    powers = {1: config["base"] % config["modulus"]}
    pairs = []
    for value in chain[1:]:
        left, right = find_sum_pair(chain[: chain.index(value)], value)
        powers[value] = (powers[left] * powers[right]) % config["modulus"]
        pairs.append({"value": value, "left": left, "right": right})
    expected = pow(config["base"], config["exponent"], config["modulus"])
    if powers[config["exponent"]] != expected:
        raise EvaluationError("replayed chain result does not match modular exponentiation")
    return pairs, powers[config["exponent"]]


def baseline_value(reference):
    if not isinstance(reference, str) or not reference.startswith(BASELINE_PREFIX):
        raise EvaluationError(f"baseline reference must start with {BASELINE_PREFIX}")
    value_text = reference[len(BASELINE_PREFIX) :]
    if not value_text.isdecimal():
        raise EvaluationError("baseline must be a decimal integer")
    value = int(value_text)
    if value < 1 or value > MAX_CHAIN_LENGTH:
        raise EvaluationError("baseline is outside the supported chain range")
    return value


def evidence_for(request, config, candidate_ref, candidate, pairs, result):
    evidence = {
        "candidate_ref": candidate_ref,
        "config_ref": request["task"]["config_ref"],
        "modulus": config["modulus"],
        "base": config["base"],
        "exponent": config["exponent"],
        "chain": candidate["chain"],
        "pairs": pairs,
        "result": result,
        "operation_count": len(candidate["chain"]) - 1,
    }
    encoded = json.dumps(evidence, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise EvaluationError("evidence exceeds the input limit")
    supplied = parse_json(request["evidence_json"], "evidence")
    if supplied != evidence:
        raise EvaluationError("evidence does not match the reconstructed chain")
    return encoded


def expected_evidence_refs(evidence_json):
    digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
    return {
        f"evidence:field-exponent:{digest}",
        EVALUATOR_REF,
        f"execution:field-exponent-v1:{digest}",
        f"output:field-exponent:{digest}",
    }


def validate_evidence_refs(references, expected):
    if not isinstance(references, list):
        raise EvaluationError("binding evidence_refs do not match the reconstructed evidence")
    if len(references) > len(expected) + MAX_PROVENANCE_REFS:
        raise EvaluationError("binding evidence_refs exceed the provenance limit")
    if any(
        not isinstance(reference, str)
        or len(reference.encode("utf-8")) > MAX_PROVENANCE_REF_BYTES
        or any(character in reference for character in "\r\n\x00")
        for reference in references
    ):
        raise EvaluationError("binding evidence_refs contain an invalid reference")
    if len(set(references)) != len(references) or not expected.issubset(set(references)):
        raise EvaluationError("binding evidence_refs do not match the reconstructed evidence")
    extras = set(references) - expected
    if any(PROVENANCE_REF_RE.fullmatch(reference) is None for reference in extras):
        raise EvaluationError("binding evidence_refs contain an unsupported provenance reference")


def evaluate(request):
    if request.get("protocol_version") != 1:
        raise EvaluationError("unsupported protocol version")
    if request.get("adapter_ref") != ADAPTER_REF or request.get("evaluator_ref") != EVALUATOR_REF:
        raise EvaluationError("request does not select the field-exponent evaluator")
    task = request.get("task")
    submission = request.get("submission")
    binding = request.get("binding")
    if not all(isinstance(value, dict) for value in (task, submission, binding)):
        raise EvaluationError("request task, submission, and binding must be objects")
    if task.get("adapter_ref") != ADAPTER_REF or task.get("evaluator_ref") != EVALUATOR_REF:
        raise EvaluationError("task references do not select the field-exponent evaluator")
    if task.get("ranking", {}).get("metric") != METRIC:
        raise EvaluationError(f"ranking metric must be {METRIC}")
    if submission.get("task_ref") != task.get("adapter_ref"):
        raise EvaluationError("submission task_ref does not match the task adapter")
    if binding.get("submission_ref") != submission.get("submission_ref"):
        raise EvaluationError("submission_ref does not match the binding")
    candidate_ref = submission.get("artifact_ref")
    if binding.get("candidate_ref") != candidate_ref:
        raise EvaluationError("candidate reference does not match the binding")
    config_raw = decode_reference(task.get("config_ref"), TASK_PREFIX, MAX_CONFIG_BYTES, "task config")
    config = validate_config(parse_json(config_raw, "task config"))
    candidate_raw = decode_reference(candidate_ref, CANDIDATE_PREFIX, MAX_CANDIDATE_BYTES, "candidate")
    candidate = validate_candidate(parse_json(candidate_raw, "candidate"), config)
    pairs, result = replay_chain(config, candidate["chain"])
    evidence_json = evidence_for(request, config, candidate_ref, candidate, pairs, result)
    validate_evidence_refs(binding.get("evidence_refs"), expected_evidence_refs(evidence_json))
    operation_count = len(candidate["chain"]) - 1
    baseline = baseline_value(task.get("baseline_ref"))
    evidence_digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
    return {
        "protocol_version": 1,
        "evaluator_ref": EVALUATOR_REF,
        "adapter_ref": ADAPTER_REF,
        "binding": binding,
        "evaluation": {
            "evidence": {
                "evidence_ref": f"evidence:field-exponent:{evidence_digest}",
                "execution_ref": f"execution:field-exponent-v1:{evidence_digest}",
                "output_ref": f"output:field-exponent:{evidence_digest}",
                "evaluator_ref": EVALUATOR_REF,
                "attestation_ref": None,
            },
            "metrics": {
                "metrics": [
                    {
                        "name": METRIC,
                        "unit": "field multiplications",
                        "direction": "LowerIsBetter",
                        "value": float(operation_count),
                        "uncertainty": 0.0,
                        "sample_count": 1,
                        "cost": float(operation_count),
                        "baseline_delta": float(baseline - operation_count),
                    }
                ]
            },
        },
    }


def check_candidate(candidate_path, config_path, baseline):
    config = validate_config(parse_json(pathlib.Path(config_path).read_text(), "task config"))
    candidate_raw = pathlib.Path(candidate_path).read_bytes()
    if len(candidate_raw) > MAX_CANDIDATE_BYTES:
        raise EvaluationError("candidate exceeds the input limit")
    candidate = validate_candidate(parse_json(candidate_raw, "candidate"), config)
    pairs, result = replay_chain(config, candidate["chain"])
    candidate_ref = encode_reference(CANDIDATE_PREFIX, json.dumps(candidate, separators=(",", ":"), sort_keys=True).encode())
    evidence = {
        "candidate_ref": candidate_ref,
        "config_ref": encode_reference(TASK_PREFIX, json.dumps(config, separators=(",", ":"), sort_keys=True).encode()),
        "modulus": config["modulus"],
        "base": config["base"],
        "exponent": config["exponent"],
        "chain": candidate["chain"],
        "pairs": pairs,
        "result": result,
        "operation_count": len(candidate["chain"]) - 1,
    }
    evidence_json = json.dumps(evidence, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()
    return {
        "candidate_ref": candidate_ref,
        "evidence_json": evidence,
        "evidence_refs": [
            f"evidence:field-exponent:{digest}",
            EVALUATOR_REF,
            f"execution:field-exponent-v1:{digest}",
            f"output:field-exponent:{digest}",
        ],
        "metric": METRIC,
        "value": len(candidate["chain"]) - 1,
        "baseline": baseline,
        "baseline_delta": baseline - (len(candidate["chain"]) - 1),
        "result": result,
    }


def main():
    try:
        if len(sys.argv) > 1:
            parser = argparse.ArgumentParser(description="Check a finite-field addition chain.")
            parser.add_argument("--check", required=True, metavar="CANDIDATE_JSON")
            parser.add_argument("--config", required=True, metavar="CONFIG_JSON")
            parser.add_argument("--baseline", type=int, required=True)
            args = parser.parse_args()
            json.dump(check_candidate(args.check, args.config, args.baseline), sys.stdout, indent=2)
            sys.stdout.write("\n")
            return
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise EvaluationError("request exceeds the input limit")
        response = evaluate(parse_json(raw, "request"))
        json.dump(response, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
    except (EvaluationError, KeyError, OSError, TypeError, ValueError) as error:
        sys.stderr.write(f"field-exponent-v1: {error}\n")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
