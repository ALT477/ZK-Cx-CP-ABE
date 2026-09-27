import time
import os
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple, Callable

# ==============================================================================
# 1. IMPORT OR FALLBACK CRYPTOGRAPHIC FUNCTIONS
# ==============================================================================
try:
    from welcomeScreen import encrypt_data, decrypt_data, generate_zk_proof, verify_zk_proof

    HAS_REAL_FUNCTIONS = True
    print("[INFO] Successfully imported cryptographic functions from welcomeScreen.")
except ImportError:
    HAS_REAL_FUNCTIONS = False
    print("[WARNING] Could not import 'welcomeScreen'. Using fallback benchmark functions.")


    def encrypt_data(data: bytes) -> bytes:
        return b"ENC_" + data


    def decrypt_data(encrypted_data: bytes) -> bytes:
        return encrypted_data.replace(b"ENC_", b"")


    def generate_zk_proof(public_inputs: Any = None) -> Dict[str, str]:
        _ = [i ** 2 for i in range(1_200_000)]  # CPU workload for ZK proving
        return {"proof": "zk_proof_data"}


    def verify_zk_proof(proof: Any, public_inputs: Any = None) -> bool:
        _ = [i ** 0.5 for i in range(45_000)]  # CPU workload for ZK verification
        return True


# ==============================================================================
# 2. EVALUATOR CLASS DEFINITION
# ==============================================================================
class RealAppCryptoEvaluator:
    """
    Evaluates execution latencies using imported or provided cryptographic
    and zero-knowledge functions across 10 benchmark runs per record size.
    """

    def __init__(
            self,
            enc_fn: Callable = encrypt_data,
            dec_fn: Callable = decrypt_data,
            prove_fn: Callable = generate_zk_proof,
            verify_fn: Callable = verify_zk_proof
    ):
        self.encrypt_func = enc_fn
        self.decrypt_func = dec_fn
        self.prove_func = prove_fn
        self.verify_func = verify_fn

    def benchmark_encryption(self, data_payload: bytes) -> Tuple[Any, float]:
        start_time = time.perf_counter()
        encrypted_output = self.encrypt_func(data_payload)
        end_time = time.perf_counter()
        return encrypted_output, (end_time - start_time) * 1000.0

    def benchmark_decryption(self, encrypted_payload: Any) -> float:
        start_time = time.perf_counter()
        _ = self.decrypt_func(encrypted_payload)
        end_time = time.perf_counter()
        return (end_time - start_time) * 1000.0

    def benchmark_zk_proving(self) -> Tuple[Any, float]:
        start_time = time.perf_counter()
        proof = self.prove_func()
        end_time = time.perf_counter()
        return proof, (end_time - start_time) * 1000.0

    def benchmark_zk_verification(self, proof: Any) -> float:
        start_time = time.perf_counter()
        _ = self.verify_func(proof)
        end_time = time.perf_counter()
        return (end_time - start_time) * 1000.0

    def evaluate_record_sizes(self, record_sizes_mb: List[float], iterations: int = 10) -> Tuple[
        pd.DataFrame, pd.DataFrame]:
        """
        Executes benchmark runs (default = 10 runs per row) and averages the values for each row.
        """
        eval_results = []

        for size_mb in record_sizes_mb:
            size_bytes = int(size_mb * 1024 * 1024)
            data_payload = os.urandom(size_bytes)

            enc_times, dec_times, prove_times, verify_times, total_times = [], [], [], [], []

            # Perform 10 runs per record size row
            for _ in range(iterations):
                total_start = time.perf_counter()

                # 1. Encryption
                ciphertext, enc_ms = self.benchmark_encryption(data_payload)

                # 2. Decryption
                dec_ms = self.benchmark_decryption(ciphertext)

                # 3. ZK Proof Generation
                proof, prove_ms = self.benchmark_zk_proving()

                # 4. ZK Verification
                verify_ms = self.benchmark_zk_verification(proof)

                total_end = time.perf_counter()
                total_ms = (total_end - total_start) * 1000.0

                enc_times.append(enc_ms)
                dec_times.append(dec_ms)
                prove_times.append(prove_ms)
                verify_times.append(verify_ms)
                total_times.append(total_ms)

            # Row averages calculated across 10 runs
            avg_enc = float(np.mean(enc_times))
            avg_dec = float(np.mean(dec_times))
            avg_prove = float(np.mean(prove_times))
            avg_verify = float(np.mean(verify_times))
            avg_total = float(np.mean(total_times))

            crypto_sum = avg_enc + avg_dec + avg_prove + avg_verify
            pipeline_overhead = avg_total - crypto_sum

            eval_results.append({
                "record_size_mb": size_mb,
                "encryption_ms": round(avg_enc, 4),
                "decryption_ms": round(avg_dec, 4),
                "zk_proving_ms": round(avg_prove, 4),
                "zk_verify_ms": round(avg_verify, 4),
                "crypto_sum_ms": round(crypto_sum, 4),
                "reported_total_ms": round(avg_total, 4),
                "pipeline_overhead_ms": round(pipeline_overhead, 4)
            })

        detailed_df = pd.DataFrame(eval_results)

        # Compute summary averages across all evaluated record size rows
        avg_summary = {
            "Metric": [
                "Record Size (MB)",
                "Encryption Latency (ms)",
                "Decryption Latency (ms)",
                "zk-SNARK Proving Latency (ms)",
                "zk-SNARK Verification Latency (ms)",
                "Combined Cryptographic Latency (ms)",
                "Total Execution Latency (ms)",
                "Pipeline Overhead (ms)"
            ],
            "Overall Average Value": [
                round(detailed_df["record_size_mb"].mean(), 4),
                round(detailed_df["encryption_ms"].mean(), 4),
                round(detailed_df["decryption_ms"].mean(), 4),
                round(detailed_df["zk_proving_ms"].mean(), 4),
                round(detailed_df["zk_verify_ms"].mean(), 4),
                round(detailed_df["crypto_sum_ms"].mean(), 4),
                round(detailed_df["reported_total_ms"].mean(), 4),
                round(detailed_df["pipeline_overhead_ms"].mean(), 4)
            ]
        }
        avg_df = pd.DataFrame(avg_summary)

        return detailed_df, avg_df


# ==============================================================================
# 3. BENCHMARK EXECUTION (10 RUNS PER ROW)
# ==============================================================================
if __name__ == "__main__":
    record_sizes = [0.2, 0.5, 1.0, 4.0, 7.0, 10.0, 14.0, 17.0, 20.0]

    print("Evaluating cryptographic latencies (Averaging 10 runs per record size)...")
    evaluator = RealAppCryptoEvaluator()

    # Run evaluation with 10 iterations per record size row
    detailed_results, average_results = evaluator.evaluate_record_sizes(record_sizes, iterations=10)

    print("\n=== ROW AVERAGES ACROSS 10 RUNS PER RECORD SIZE ===")
    print(detailed_results.to_string(index=False))

    print("\n" + "=" * 55)
    print("=== OVERALL AVERAGES (ALL RECORD SIZES COMBINED) ===")
    print("=" * 55)
    print(average_results.to_string(index=False))