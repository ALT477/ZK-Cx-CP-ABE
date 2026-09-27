import time
import matplotlib.pyplot as plt
from web3 import Web3

# ----------------------------------------------------------------------
# 1. CONFIGURATION & NETWORK CONNECTION
# ----------------------------------------------------------------------
RPC_URL = "http://127.0.0.1:8545"
CONTRACT_ADDRESS = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
NUM_RUNS = 10  # Number of benchmark iterations to compute averages

w3 = Web3(Web3.HTTPProvider(RPC_URL))

if not w3.is_connected():
    raise ConnectionError(f"Cannot connect to local Ethereum node at {RPC_URL}")

account = w3.eth.accounts[0]
sample_bytes32 = b"12345678901234567890123456789012"

CONTRACT_ABI = [
    {
        "inputs": [{"name": "patientId", "type": "bytes32"}],
        "name": "RegisterPatient",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "CheckPermission",
        "outputs": [{"name": "allowed", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}, {"name": "status", "type": "bool"}],
        "name": "AuthEvent",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "details", "type": "string"}],
        "name": "LogAccess",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)

# ----------------------------------------------------------------------
# 2. PRE-STATE INITIALIZATION
# ----------------------------------------------------------------------
print("[PRE-CHECK] Initializing state to prevent EVM reverts...")
try:
    tx = contract.functions.RegisterPatient(sample_bytes32).transact({"from": account})
    w3.eth.wait_for_transaction_receipt(tx)
    print(" -> State initialized successfully.")
except Exception as err:
    print(f" -> Pre-initialization note: {err}")

# ----------------------------------------------------------------------
# 3. BENCHMARKING FUNCTIONS (SINGLE RUN EXECUTORS)
# ----------------------------------------------------------------------
def measure_register_patient_tps(batch_size=15):
    t0 = time.perf_counter()
    succ = 0
    for _ in range(batch_size):
        try:
            tx = contract.functions.RegisterPatient(sample_bytes32).transact({"from": account})
            w3.eth.wait_for_transaction_receipt(tx)
            succ += 1
        except Exception:
            pass
    dt = time.perf_counter() - t0
    return succ / dt if dt > 0 and succ > 0 else 0.0


def measure_check_permission_tps(batch_size=100):
    t0 = time.perf_counter()
    succ = 0
    for _ in range(batch_size):
        try:
            _ = contract.functions.CheckPermission(account).call({"from": account})
            succ += 1
        except Exception:
            try:
                _ = contract.functions.CheckPermission(account, sample_bytes32).call({"from": account})
                succ += 1
            except Exception:
                try:
                    tx = contract.functions.CheckPermission(account).transact({"from": account})
                    w3.eth.wait_for_transaction_receipt(tx)
                    succ += 1
                except Exception:
                    break
    dt = time.perf_counter() - t0
    return succ / dt if dt > 0 and succ > 0 else 0.0


def measure_auth_event_tps(batch_size=15):
    t0 = time.perf_counter()
    succ = 0
    for _ in range(batch_size):
        try:
            tx = contract.functions.AuthEvent(account, True).transact({"from": account})
            w3.eth.wait_for_transaction_receipt(tx)
            succ += 1
        except Exception:
            pass
    dt = time.perf_counter() - t0
    return succ / dt if dt > 0 and succ > 0 else 0.0


def measure_log_access_tps(batch_size=15):
    t0 = time.perf_counter()
    succ = 0
    for _ in range(batch_size):
        try:
            tx = contract.functions.LogAccess("Audit Log").transact({"from": account})
            w3.eth.wait_for_transaction_receipt(tx)
            succ += 1
        except Exception:
            pass
    dt = time.perf_counter() - t0
    return succ / dt if dt > 0 and succ > 0 else 0.0

# ----------------------------------------------------------------------
# 4. MULTI-RUN AVERAGE EVALUATION
# ----------------------------------------------------------------------
print(f"\n[BENCHMARK] Executing throughput benchmarks across {NUM_RUNS} iterations...")

raw_results = {
    "RegisterPatient": [],
    "CheckPermission": [],
    "AuthEvent": [],
    "LogAccess": []
}

for i in range(1, NUM_RUNS + 1):
    print(f" Iteration {i}/{NUM_RUNS}...", end="\r")
    raw_results["RegisterPatient"].append(measure_register_patient_tps())
    raw_results["CheckPermission"].append(measure_check_permission_tps())
    raw_results["AuthEvent"].append(measure_auth_event_tps())
    raw_results["LogAccess"].append(measure_log_access_tps())

print(f"\nIterative evaluation complete across {NUM_RUNS} runs.")

# Compute mathematical mean
avg_results = {
    func: round(sum(scores) / len(scores), 2)
    for func, scores in raw_results.items()
}

print("\n" + "=" * 55)
print(f"AVERAGE THROUGHPUT RESULTS ({NUM_RUNS} ITERATIONS MEAN)")
print("=" * 55)
for fn, tps in avg_results.items():
    print(f"  - {fn:<20}: {tps} Transactions/s")
print("=" * 55)

# ----------------------------------------------------------------------
# 5. PLOT AVERAGE METRICS
# ----------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5), dpi=300)
funcs = list(avg_results.keys())
vals = list(avg_results.values())
colors = ["#1d70e8", "#2ea44f", "#ff8c00", "#7b1fa2"]

bars = ax.bar(funcs, vals, color=colors, width=0.55)
max_val = max(vals) if max(vals) > 0 else 10.0

for bar in bars:
    y = bar.get_height()
    ax.text(bar.get_x() + bar.get_width() / 2.0, y + (max_val * 0.02), f"{y:.1f}",
            ha="center", va="bottom", fontsize=11, fontweight="bold")

ax.set_ylabel(f"Average Throughput (Transactions/s, N={NUM_RUNS})", fontsize=11)
ax.set_xlabel("Smart Contract Function", fontsize=11)
ax.set_title(f"Empirical Smart Contract Throughput (Mean of {NUM_RUNS} Runs)", fontsize=13, fontweight="bold")
ax.set_ylim(0, max_val * 1.2)
ax.yaxis.grid(True, linestyle="--", alpha=0.6)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.tight_layout()
plt.savefig("average_throughput_results.png")
print("\nSaved visualization to 'average_throughput_results.png'.")
plt.show()