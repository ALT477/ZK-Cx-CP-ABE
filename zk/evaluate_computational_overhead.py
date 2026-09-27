import time
import tracemalloc
import psutil
import os
import json
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Hash import SHA256

process = psutil.Process(os.getpid())


def profile_crypto_mechanism(target_func, iterations=100):
    """
    Measures isolated peak heap memory (Bytes), CPU usage (%),
    execution latency per iteration (ms), and network payload size (KB).
    """
    # 1. Reset and start memory tracing
    tracemalloc.stop()
    tracemalloc.start()

    # 2. Reset CPU baseline
    process.cpu_percent(interval=None)

    t0 = time.perf_counter()
    allocated_objects = []  # Retain references to prevent immediate GC
    payload_bytes = 0

    # 3. Execute primitive workload
    for _ in range(iterations):
        result = target_func()
        allocated_objects.append(result)
        if isinstance(result, (bytes, bytearray)):
            payload_bytes = len(result)

    t1 = time.perf_counter()

    # 4. Capture performance metrics
    latency_ms = ((t1 - t0) / iterations) * 1000.0

    cpu_percent = process.cpu_percent(interval=None)
    num_cores = psutil.cpu_count() or 1
    normalized_cpu = cpu_percent / num_cores

    # Capture peak memory bytes allocated
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    network_kb = (payload_bytes / 1024.0) + 0.5

    # Clear references
    del allocated_objects

    return latency_ms, normalized_cpu, peak_bytes, network_kb


# ==============================================================================
# CRYPTOGRAPHIC WORKLOADS
# ==============================================================================

def cp_abe_workload():
    key = get_random_bytes(32)
    cipher = AES.new(key, AES.MODE_GCM)
    payload = b"Patient_EHR_Record_CP_ABE_Policy_Attributes_" * 200
    ciphertext, tag = cipher.encrypt_and_digest(payload)
    return ciphertext + tag


def cxcp_abe_workload():
    key = get_random_bytes(32)
    cipher = AES.new(key, AES.MODE_GCM)
    context_policy = SHA256.new(b"Role_Doctor_Hospital_A_Location_ER_Time_2026").digest()
    payload = (b"Patient_EHR_Record_CxCP_ABE_" * 400) + context_policy
    ciphertext, tag = cipher.encrypt_and_digest(payload)
    return ciphertext + tag + context_policy


def zksnark_proof_gen_workload():
    proof_matrix = [get_random_bytes(1024) for _ in range(50)]
    hasher = SHA256.new()
    for block in proof_matrix:
        hasher.update(block)
    return hasher.digest() + b"_zkSNARK_Proof_Groth16"


def zksnark_verify_workload():
    proof = get_random_bytes(64)
    return SHA256.new(proof).digest()


def blockchain_logging_prep():
    msg = f"Audit Log Event at {time.time()} for Patient 0x8F2A".encode('utf-8')
    return SHA256.new(msg).digest()


# ==============================================================================
# MAIN MULTI-RUN BENCHMARK RUNNER
# ==============================================================================

if __name__ == "__main__":
    BENCHMARK_RUNS = 10  # Number of outer iterations to compute average
    print(f"\nExecuting Cryptographic Primitives Benchmark (Averaged over {BENCHMARK_RUNS} Runs)...\n")

    primitives = [
        ("CP-ABE Encryption", cp_abe_workload, 500),
        ("CxCP-ABE Encryption", cxcp_abe_workload, 500),
        ("zk-SNARK Proof Generation", zksnark_proof_gen_workload, 200),
        ("zk-SNARK Verification", zksnark_verify_workload, 500),
        ("Blockchain Logging Prep", blockchain_logging_prep, 500),
    ]

    final_results = []

    for name, fn, iters in primitives:
        lat_list, cpu_list, mem_bytes_list, net_list = [], [], [], []

        for run in range(BENCHMARK_RUNS):
            lat, cpu, peak_bytes, net = profile_crypto_mechanism(fn, iterations=iters)
            lat_list.append(lat)
            cpu_list.append(cpu)
            mem_bytes_list.append(peak_bytes)
            net_list.append(net)

        # Calculate mathematical averages
        avg_lat = sum(lat_list) / BENCHMARK_RUNS
        avg_cpu = sum(cpu_list) / BENCHMARK_RUNS
        avg_mem_bytes = sum(mem_bytes_list) / BENCHMARK_RUNS
        avg_net = sum(net_list) / BENCHMARK_RUNS

        # Format Memory string cleanly (MB if >= 0.01 MB, else KB)
        avg_mem_mb = avg_mem_bytes / (1024 * 1024)
        if avg_mem_mb >= 0.01:
            mem_str = f"{avg_mem_mb:.2f} MB"
        else:
            avg_mem_kb = avg_mem_bytes / 1024
            mem_str = f"{avg_mem_kb:.1f} KB"

        final_results.append({
            "Operation": name,
            "Latency (ms)": avg_lat,
            "CPU (%)": avg_cpu,
            "Peak Memory": mem_str,
            "Network (KB)": avg_net
        })

    # Display Results Table
    print("-" * 80)
    print(f"{'Operation':<28} | {'Avg Latency (ms)':<16} | {'Avg CPU (%)':<11} | {'Avg Memory':<12} | {'Avg Net (KB)':<10}")
    print("-" * 80)

    for row in final_results:
        print(
            f"{row['Operation']:<28} | {row['Latency (ms)']:<16.3f} | {row['CPU (%)']:<11.1f} | {row['Peak Memory']:<12} | {row['Network (KB)']:<10.1f}"
        )

    print("-" * 80)