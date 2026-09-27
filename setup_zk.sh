#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/7] Installing Node.js dependencies..."
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 20+ is required. Install it first (Ubuntu/Debian recommended)."
  exit 1
fi
node -v
npm install --no-fund --no-audit circomlib snarkjs

echo "[2/7] Installing Circom 2.2.2 if needed..."
if ! command -v circom >/dev/null 2>&1; then
  wget -q https://github.com/iden3/circom/releases/download/v2.2.2/circom-linux-amd64 -O /tmp/circom-linux-amd64
  chmod +x /tmp/circom-linux-amd64
  sudo mv /tmp/circom-linux-amd64 /usr/local/bin/circom
fi
circom --version

echo "[3/7] Compiling the eligibility circuit..."
rm -rf zk/eligibility_js
rm -f zk/eligibility.r1cs zk/eligibility.sym
circom zk/eligibility.circom --r1cs --wasm --sym -l node_modules -o zk

echo "[4/7] Creating Powers of Tau..."
rm -f zk/pot12_0000.ptau zk/pot12_0001.ptau zk/pot12_final.ptau
snarkjs powersoftau new bn128 12 zk/pot12_0000.ptau -v
ENTROPY="$(openssl rand -hex 32)"
snarkjs powersoftau contribute zk/pot12_0000.ptau zk/pot12_0001.ptau \
  --name="IoToDChain contribution" -e="$ENTROPY"
snarkjs powersoftau prepare phase2 zk/pot12_0001.ptau zk/pot12_final.ptau -v

echo "[5/7] Generating Groth16 proving key..."
rm -f zk/eligibility_0000.zkey zk/eligibility_final.zkey
snarkjs groth16 setup zk/eligibility.r1cs zk/pot12_final.ptau zk/eligibility_0000.zkey

echo "[6/7] Contributing to the proving key and exporting verifier key..."
ENTROPY_ZKEY="$(openssl rand -hex 32)"
snarkjs zkey contribute zk/eligibility_0000.zkey zk/eligibility_final.zkey \
  --name="IoToDChain zkey contribution" -e="$ENTROPY_ZKEY"
snarkjs zkey export verificationkey zk/eligibility_final.zkey zk/verification_key.json

echo "[7/7] ZK setup complete."
ls -lh zk/eligibility.r1cs zk/eligibility_final.zkey zk/verification_key.json
