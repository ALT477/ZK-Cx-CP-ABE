# IoToDChain + ZK-Cx-CP-ABE integration

This version integrates the zero-knowledge eligibility workflow from `مستند نصي جديد.txt`
into the existing IoToDChain backend architecture in `code.zip`.

## Added components

- `zk/eligibility.circom`: Groth16 eligibility circuit.
- `zk_snark.py`: Python wrapper around Circom/snarkjs.
- `setup_zk.sh`: compiles the circuit and creates the Groth16 proving/verifying artifacts.
- `package.json`: local `circomlib` and `snarkjs` dependencies.
- `ZKEligibilityProfile` and `ZKProofLog` database tables.
- `/api/zk/eligibility/profile`: private patient eligibility profile.
- `/api/zk/eligibility/prove`: Mode A, patient creates a proof for a health record.
- `/api/zk/eligibility/verify`: a verifier checks a proof without receiving age, HbA1c, or CKD.
- blockchain audit event `log_zk_verification()`.

## Eligibility relation

The circuit proves:

`30 <= age <= 60`
`HbA1c <= 69.0`
`CKD = 0`

HbA1c is encoded as `hba1c10 = HbA1c * 10`.

The private witness is:

- `age`
- `hba1c10`
- `ckd`

The public bindings are:

- `policyHash = SHA256(ProofPolicyID + condition)` reduced to the BN128 field
- `ctHash = SHA256(ciphertext)` reduced to the BN128 field

The API also compares the public values against the expected policy and the selected health-record `hEncM`, so a proof cannot be reused for a different record or policy.

## Installation

From the `code/` directory on Ubuntu/Debian:

1. Install Node.js 20+ and OpenSSL.
2. Make the script executable:
   `chmod +x setup_zk.sh`
3. Run:
   `./setup_zk.sh`

The script creates:

- `zk/eligibility.r1cs`
- `zk/eligibility_js/eligibility.wasm`
- `zk/eligibility_final.zkey`
- `zk/verification_key.json`

These generated artifacts are intentionally not included in the source archive.

## API flow

1. Patient authenticates normally and receives the existing IoToDChain session token.
2. Patient stores the private eligibility profile with:
   `PUT /api/zk/eligibility/profile`
3. Patient has an existing IoToDChain health record from `/api/vitals/submit`.
4. Patient calls:
   `POST /api/zk/eligibility/prove?record_id=<record_id>`
5. The response contains only the Groth16 proof, public inputs, hashes, timing and blockchain audit information.
6. A verifier can submit the proof to:
   `POST /api/zk/eligibility/verify`
7. The verifier receives `verified=true/false`; private witness values are not returned.

## Important implementation note

The original notebook used an in-memory AES/CxCP-ABE demonstration and a Python list as a simulated blockchain.
This integration deliberately reuses the existing IoToDChain `crypto.py`, `database.py`, and
`blockchain.py` modules from the supplied ZIP instead of replacing them.

The ZK component is therefore an additional authorization/eligibility layer, not a replacement
for the existing CxABE-PRE encryption/decryption and access-request workflow.

The Groth16 setup script uses fresh random contributions for the local prototype. For a
production or publication-grade deployment, use a properly managed trusted-setup ceremony
or a setup model appropriate to the selected proof system.
