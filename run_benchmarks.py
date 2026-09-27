import requests
import time
import numpy as np

BASE_URL = "http://192.168.43.55:8000"

# 📍 PASTE YOUR COPIED TOKEN HERE
# Keep "Bearer " if your token string doesn't already include it
SESSION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJQQVQtNzFGMjYzMDMiLCJyb2xlIjoicGF0aWVudCIsInB1cnBvc2UiOiJzZXNzaW9uIiwiZXhwIjoxNzkyNjYxODExLCJpYXQiOjE3OTAwNjk4MTF9.nGyvvQr10NApXaajYZQfHLqUZloJaB3Ui-8uWcmAgkY"


def get_authenticated_session():
    session = requests.Session()

    # Format Authorization header (add "Bearer " prefix if not already present)
    token_str = SESSION_TOKEN if SESSION_TOKEN.startswith("Bearer ") else f"Bearer {SESSION_TOKEN}"

    session.headers.update({
        "Authorization": token_str,
        "Content-Type": "application/json"
    })

    return session


def run_request_scaling_test(num_requests=50):
    session = get_authenticated_session()
    print(f"\n--- Running Benchmark: {num_requests} repeated requests ---")

    latencies = []

    # Sample payload matching /api/vitals/submit
    payload = {
        "patient_id": "PAT-71F26303",
        "heart_rate": 80,
        "systolic": 120,
        "diastolic": 80,
        "temperature": 37.0,
        "spo2": 98,
        "device_id": "DEV-001"
    }

    for i in range(num_requests):
        t0 = time.perf_counter()
        try:
            res = session.post(f"{BASE_URL}/api/vitals/submit", json=payload)
            t1 = time.perf_counter()

            if res.status_code == 200:
                latency_ms = (t1 - t0) * 1000
                latencies.append(latency_ms)
                print(f"[SUCCESS] Iteration {i + 1}: Latency = {latency_ms:.2f} ms")
            else:
                print(f"[FAIL] Iteration {i + 1}: HTTP {res.status_code} -> {res.text}")

        except Exception as e:
            print(f"[ERROR] Iteration {i + 1}: Request failed -> {e}")

    # Summary Statistics
    print(f"\nCompleted: {len(latencies)} / {num_requests} successful executions")
    if latencies:
        print(f"Mean Latency: {np.mean(latencies):.2f} ms (+/- {np.std(latencies):.2f} ms)")
        print(f"Min Latency:  {np.min(latencies):.2f} ms")
        print(f"Max Latency:  {np.max(latencies):.2f} ms")
    else:
        print("No successful executions recorded. Check token validity or server errors above.")


if __name__ == "__main__":
    run_request_scaling_test(50)