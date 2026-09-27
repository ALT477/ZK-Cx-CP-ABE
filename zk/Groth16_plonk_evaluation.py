import glob
import json
import os
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def find_file(filename):
    """Recursively search for a file within BASE_DIR."""
    matches = glob.glob(os.path.join(BASE_DIR, "**", filename), recursive=True)
    return matches[0] if matches else None

# Auto-detect compiled files
GENERATE_WITNESS_PATH = find_file("generate_witness.js")
WASM_PATH = find_file("*.wasm")
INPUT_PATH = find_file("input.json") or os.path.join(BASE_DIR, "input.json")

GROTH16_ZKEY = find_file("*groth16*.zkey") or os.path.join(BASE_DIR, "circuit_final_groth16.zkey")
PLONK_ZKEY = find_file("*plonk*.zkey") or os.path.join(BASE_DIR, "circuit_final_plonk.zkey")

def run_command(cmd):
    """Executes command silently and returns execution time in milliseconds."""
    t0 = time.perf_counter()
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    t1 = time.perf_counter()
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nError: {res.stderr}")
    return (t1 - t0) * 1000.0

def benchmark_operation(cmd, iterations=5):
    """Runs a command multiple times and returns average latency in ms."""
    times = []
    for _ in range(iterations):
        times.append(run_command(cmd))
    return sum(times) / len(times)

def evaluate_groth16_vs_plonk(iterations=5):
    print("=== Detected Files ===")
    print(f"Witness Generator : {GENERATE_WITNESS_PATH}")
    print(f"WASM Executable   : {WASM_PATH}")
    print(f"Input File        : {INPUT_PATH}\n")

    if not GENERATE_WITNESS_PATH:
        raise FileNotFoundError("generate_witness.js not found. Run circom compilation first.")
    if not WASM_PATH:
        raise FileNotFoundError(".wasm file not found.")

    results = {}

    for system in ["groth16", "plonk"]:
        zkey = GROTH16_ZKEY if system == "groth16" else PLONK_ZKEY

        if not os.path.exists(zkey):
            print(f"Skipping {system.upper()}: Key not found ({zkey})")
            continue

        print(f"=== Benchmarking {system.upper()} (Averaged over {iterations} runs) ===")
        witness_file = os.path.join(BASE_DIR, f"witness_{system}.wtns")
        proof_file = os.path.join(BASE_DIR, f"proof_{system}.json")
        public_file = os.path.join(BASE_DIR, f"public_{system}.json")
        vkey_file = os.path.join(BASE_DIR, f"vkey_{system}.json")

        # 1. Pre-export Verification Key (Excluded from runtime verification latency)
        print("1. Exporting verification key...")
        run_command(f'npx snarkjs zkey export verificationkey "{zkey}" "{vkey_file}"')

        # 2. Witness Generation Latency
        print("2. Computing witness...")
        witness_cmd = f'node "{GENERATE_WITNESS_PATH}" "{WASM_PATH}" "{INPUT_PATH}" "{witness_file}"'
        avg_witness_time = benchmark_operation(witness_cmd, iterations=iterations)

        # 3. Proof Generation Latency
        print("3. Generating proof...")
        proof_cmd = f'npx snarkjs {system} prove "{zkey}" "{witness_file}" "{proof_file}" "{public_file}"'
        avg_proof_time = benchmark_operation(proof_cmd, iterations=iterations)

        # 4. Proof Verification Latency
        print("4. Verifying proof...")
        verify_cmd = f'npx snarkjs {system} verify "{vkey_file}" "{public_file}" "{proof_file}"'
        avg_verify_time = benchmark_operation(verify_cmd, iterations=iterations)

        results[system] = {
            "witness_time_ms": round(avg_witness_time, 2),
            "proof_time_ms": round(avg_proof_time, 2),
            "verify_time_ms": round(avg_verify_time, 2),
            "proof_bytes": os.path.getsize(proof_file),
            "public_bytes": os.path.getsize(public_file),
            "vkey_kb": round(os.path.getsize(vkey_file) / 1024.0, 2),
            "zkey_mb": round(os.path.getsize(zkey) / (1024.0 * 1024.0), 2),
        }

        # Clean up temporary artifact files
        for temp_f in [witness_file, proof_file, public_file, vkey_file]:
            if os.path.exists(temp_f):
                os.remove(temp_f)

    return results

if __name__ == "__main__":
    real_data = evaluate_groth16_vs_plonk(iterations=5)

    print("\n" + "=" * 50)
    print("FINAL SYSTEM BENCHMARK RESULTS")
    print("=" * 50)

    g16 = real_data.get("groth16", {})
    plk = real_data.get("plonk", {})

    print("\n| Metric | Groth16 | PLONK |")
    print("| :--- | :---: | :---: |")
    print(f"| **Witness generation time (ms)** | {g16.get('witness_time_ms', 'N/A')} | {plk.get('witness_time_ms', 'N/A')} |")
    print(f"| **Proof generation time (ms)** | {g16.get('proof_time_ms', 'N/A')} | {plk.get('proof_time_ms', 'N/A')} |")
    print(f"| **Proof verification time (ms)** | {g16.get('verify_time_ms', 'N/A')} | {plk.get('verify_time_ms', 'N/A')} |")
    print(f"| **Proof size (bytes)** | {g16.get('proof_bytes', 'N/A')} | {plk.get('proof_bytes', 'N/A')} |")
    print(f"| **Public input size (bytes)** | {g16.get('public_bytes', 'N/A')} | {plk.get('public_bytes', 'N/A')} |")
    print(f"| **Verification key size (KB)** | {g16.get('vkey_kb', 'N/A')} | {plk.get('vkey_kb', 'N/A')} |")
    print(f"| **Proving key size (MB)** | {g16.get('zkey_mb', 'N/A')} | {plk.get('zkey_mb', 'N/A')} |")