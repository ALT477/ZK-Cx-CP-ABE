#!/usr/bin/env python3
"""Small real Groth16 benchmark for the integrated IoToDChain ZK layer."""
import argparse
import hashlib
import json
import os
import statistics
import time

from zk_snark import EligibilityInput, ZKSnarkEngine

CONDITION = "(30 <= age <= 60) AND (HbA1c <= 69.0) AND (CKD = 0)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    engine = ZKSnarkEngine()
    inp = EligibilityInput(age=45, hba1c=6.5, ckd=0)

    rows = []
    for i in range(args.runs):
        ct_hash = hashlib.sha256(os.urandom(1024 * 1024)).hexdigest()
        started = time.perf_counter()
        result = engine.prove_and_verify(
            inp, "ProofPolicyID_trial", ct_hash, CONDITION
        )
        total_ms = (time.perf_counter() - started) * 1000
        rows.append({
            "run": i + 1,
            "prove_ms": result["prove_ms"],
            "verify_ms": result["verify_ms"],
            "total_ms": round(total_ms, 3),
            "verified": result["verified"],
            "proof_bytes": len(json.dumps(result["proof"]).encode()),
            "public_bytes": len(json.dumps(result["public"]).encode()),
        })

    print(json.dumps(rows, indent=2))
    print("Mean prove (ms):", round(statistics.mean(r["prove_ms"] for r in rows), 3))
    print("Mean verify (ms):", round(statistics.mean(r["verify_ms"] for r in rows), 3))
    print("Mean total (ms):", round(statistics.mean(r["total_ms"] for r in rows), 3))


if __name__ == "__main__":
    main()
