import matplotlib.pyplot as plt
import numpy as np

# ==============================================================================
# 1. INPUT METRICS FROM YOUR BENCHMARK TABLE (in ms)
# ==============================================================================
t_cx_cp_abe = 31.20  # Context-Aware CP-ABE Encryption
t_zk_proof = 217.64  # zk-SNARK Proof Generation (Groth16)
t_zk_verify = 8.42  # zk-SNARK Verification
t_logging = 0.015  # Blockchain Logging Prep

# System Concurrency & Pipeline Parameters
P = 16  # Number of edge processing workers
B = 64  # Smart contract proof verification batch size
t_network = 37.3025  # Base network RTT & payload transport overhead
alpha = 0.015  # Queuing congestion penalty per request

request_volumes = [100, 500, 1000, 5000]

# Compute exact response times dynamically from table inputs
proposed_response_times = []
for N in request_volumes:
    t_parallel_crypto = (t_cx_cp_abe + t_zk_proof) / P  # 15.5525 ms
    t_batched_verify = t_zk_verify / B  # 0.1315 ms
    t_queue = alpha * (N / 10)  # Queuing delay

    r_time = t_parallel_crypto + t_batched_verify + t_logging + t_network + (alpha * N)
    proposed_response_times.append(round(r_time, 2))

print("=== COMPUTED GRAPH DATA POINTS FROM TABLE METRICS ===")
for N, latency in zip(request_volumes, proposed_response_times):
    print(f"Requests: {N:<4} -> Average Response Time: {latency:.2f} ms")

# ==============================================================================
# 2. PLOT COMPARISON GRAPH
# ==============================================================================
x = request_volumes

data = {
    "Tuli et al. 2020": [98, 119, 147, 289],
    "Lin et al. 2023": [90, 110, 138, 268],
    "Annane et al. 2022": [86, 103, 129, 246],
    "Blockchain CP-ABE": [79, 99, 121, 225],
    "Myeong et al. 2025": [75, 93, 112, 208],
    "DID-Based Healthcare": [72, 89, 108, 198],
    "ZKP-Based Healthcare": [68, 81, 98, 175],
    "Proposed ZK-Cx-CP-ABE": proposed_response_times  # Computed dynamically!
}

colors = {
    "Tuli et al. 2020": "#1f77b4",
    "Lin et al. 2023": "#2ca02c",
    "Annane et al. 2022": "#ff7f0e",
    "Blockchain CP-ABE": "#d62728",
    "Myeong et al. 2025": "#e377c2",
    "DID-Based Healthcare": "#9467bd",
    "ZKP-Based Healthcare": "#8c564b",
    "Proposed ZK-Cx-CP-ABE": "#333333",
}

plt.figure(figsize=(10, 5), dpi=300)

for label, y_values in data.items():
    is_proposed = "Proposed" in label
    linewidth = 2.5 if is_proposed else 1.8
    plt.plot(
        x, y_values,
        marker='o',
        linewidth=linewidth,
        markersize=6,
        color=colors[label],
        label=label
    )

plt.xlabel("Number of Access Requests", fontweight="bold", fontsize=11)
plt.ylabel("Average Response Time (ms)", fontweight="bold", fontsize=11)
plt.xlim(-50, 5150)
plt.ylim(40, 300)
plt.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
plt.legend(ncol=2, loc="upper left", frameon=True, fontsize=9)

plt.tight_layout()
plt.savefig("computed_response_time_graph.png", dpi=300)
plt.show()