"""
blockchain.py — Web3.py connector to local Ganache/Hardhat nodes
Reads deployment.json written by deploy.js, talks to HealthAccess contract.
"""

import json, os, random, hashlib, time
from pathlib import Path
from typing import Optional

# ── Try importing web3; fall back to simulation if not installed ──────────────
try:
    from web3 import Web3
    from web3.middleware import ExtraDataToPOAMiddleware
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

DEPLOYMENT_PATH = Path(os.getenv(
    "DEPLOYMENT_PATH",
    str(Path(__file__).resolve().parent / "deployment.json"),
))

# Prioritize GANACHE_URL over HARDHAT_URL
GANACHE_URL = os.getenv("GANACHE_URL", os.getenv("HARDHAT_URL", "http://127.0.0.1:8545"))

VALIDATORS = ["FOG-NODE-01", "FOG-NODE-02", "HOSPITAL-IT"]


class BlockchainClient:
    """
    Wraps Web3.py calls to the HealthAccess Solidity contract.
    Falls back to an in-memory simulation if Ganache/Hardhat node is not running.
    """

    def __init__(self):
        self.w3          = None
        self.contract    = None
        self.account     = None
        self.deployment  = None
        self.simulated   = False
        self._sim_blocks : list[dict] = []
        self._sim_block_num = 0
        self._connect()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self):
        if not WEB3_AVAILABLE:
            print("[blockchain] Web3 library not found. Falling back to simulation mode.")
            self.simulated = True
            return

        if not DEPLOYMENT_PATH.exists():
            print(f"[blockchain] Deployment file not found at {DEPLOYMENT_PATH}. Falling back to simulation mode.")
            self.simulated = True
            return

        try:
            self.deployment = json.loads(DEPLOYMENT_PATH.read_text())
            self.w3 = Web3(Web3.HTTPProvider(GANACHE_URL, request_kwargs={"timeout": 5}))

            # Inject Proof of Authority (PoA) middleware for local chains (Ganache/Hardhat)
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

            if not self.w3.is_connected():
                raise ConnectionError(f"Blockchain node at {GANACHE_URL} is not reachable")

            # Use primary account from Ganache/Hardhat
            self.account = self.w3.eth.accounts[0]

            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.deployment["address"]),
                abi=self.deployment["abi"],
            )
            self.simulated = False
            print(f"[blockchain] Successfully connected to Ganache node (Chain ID: {self.w3.eth.chain_id})")
        except Exception as e:
            print(f"[blockchain] Falling back to simulation: {e}")
            self.simulated = True

    @property
    def is_live(self) -> bool:
        return not self.simulated

    def status(self) -> dict:
        if self.simulated:
            return {"connected": False, "mode": "simulation",
                    "blocks": len(self._sim_blocks), "chainId": 1337}
        try:
            return {
                "connected": self.w3.is_connected(),
                "mode":      "live-ganache",
                "chainId":   self.w3.eth.chain_id,
                "blockNumber": self.w3.eth.block_number,
                "accounts":  len(self.w3.eth.accounts),
                "primaryAccount": self.account,
                "contract":  self.deployment["address"],
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    # ── Simulation helpers ────────────────────────────────────────────────────

    def _sim_block(self, tx_type: str, data: str, verdict: str | None = None) -> dict:
        self._sim_block_num += 1
        h = hashlib.sha256(
            f"{self._sim_block_num}{tx_type}{data}{time.time()}".encode()
        ).hexdigest()
        tx_h = hashlib.sha256(f"tx{h}".encode()).hexdigest()
        gas  = random.randint(200_000, 800_000)
        b = {
            "blockNumber": self._sim_block_num,
            "blockHash":   "0x" + h,
            "txHash":      "0x" + tx_h,
            "txType":      tx_type,
            "txData":      data,
            "verdict":     verdict,
            "validator":   VALIDATORS[self._sim_block_num % 3],
            "gasUsed":     gas,
            "timestamp":   time.time(),
            "onChain":     False,
        }
        self._sim_blocks.append(b)
        return b

    @staticmethod
    def address_for(participant_id: str) -> str:
        digest = hashlib.sha256(participant_id.encode()).hexdigest()[:40]
        if WEB3_AVAILABLE:
            return Web3.to_checksum_address(digest)
        return "0x" + digest

    # ── Contract interactions ─────────────────────────────────────────────────

    def log_setup(self) -> dict:
        if self.simulated:
            return self._sim_block("CA_SETUP", "MK+PK generated, λ=256, curve=P-256")

        try:
            tx = self.contract.functions.addFogNode(self.account).transact(
                {"from": self.account, "gas": 150_000}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("addFogNode transaction reverted")
            return self._receipt_to_block(receipt, "CA_SETUP", "MK+PK generated")
        except Exception as e:
            print(f"[blockchain] log_setup on-chain call failed, logging locally: {e}")
            return self._sim_block("CA_SETUP", "MK+PK generated, λ=256, curve=P-256")

    def log_key_issuance(self, specialist_addr: str, attr_ids: list[int], detail: str) -> dict:
        if self.simulated:
            return self._sim_block("KEY_ISSUANCE", detail)

        try:
            cs_addr = Web3.to_checksum_address(specialist_addr)
            tx = self.contract.functions.logKeyIssuance(cs_addr, attr_ids).transact(
                {"from": self.account, "gas": 300_000}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("logKeyIssuance transaction reverted")
            return self._receipt_to_block(receipt, "KEY_ISSUANCE", detail)
        except Exception as e:
            print(f"[blockchain] log_key_issuance on-chain call failed, logging locally: {e}")
            return self._sim_block("KEY_ISSUANCE", detail)

    def measure_blockchain_execution(self, tx_hash):
        t_start = time.perf_counter()

        # Wait for receipt to get actual execution metrics from Ganache
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        latency_ms = (time.perf_counter() - t_start) * 1000

        return {
            "gas_used": receipt.gasUsed,
            "blockchain_latency_ms": round(latency_ms, 2),
            "status": receipt.status
        }

    def register_record(self, record_id: str, hCT: str, policy_commit: str, owner_id: str, attr_ids: list):
        t_start = time.perf_counter()

        # Call the exact ABI function name: addRecord
        tx = self.contract.functions.addRecord(
            record_id, hCT, policy_commit, owner_id, attr_ids
        ).transact({"from": self.account, "gas": 500_000})

        # Wait for the receipt to get real gas used
        metrics = self.measure_blockchain_execution(tx)

        return {
            "txHash": tx.hex(),
            "blockNumber": self.w3.eth.get_transaction(tx).blockNumber,
            "gasUsed": metrics["gas_used"],
            "blockchain_latency_ms": metrics["blockchain_latency_ms"],
            "status": metrics["status"]
        }

    def log_access_intent(self, requester_id: str, record_id: str) -> dict:
        detail = f"{requester_id} → {record_id}"
        if self.simulated:
            return self._sim_block("ACCESS_INTENT", detail)

        try:
            tx = self.contract.functions.logEvent(
                "ACCESS_INTENT", requester_id, record_id, detail
            ).transact({"from": self.account, "gas": 350_000})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("logEvent transaction reverted")
            return self._receipt_to_block(receipt, "ACCESS_INTENT", detail)
        except Exception as e:
            print(f"[blockchain] log_access_intent on-chain call failed, logging locally: {e}")
            return self._sim_block("ACCESS_INTENT", detail)

    def log_access_check(self, requester_id: str, record_id: str, granted: bool) -> dict:
        verdict = "PERMIT" if granted else "DENY"
        tx_type = f"ACCESS_{verdict}"
        detail = f"{requester_id} → {record_id} | read-time check"
        if self.simulated:
            return self._sim_block(tx_type, detail, verdict)

        try:
            tx = self.contract.functions.logEvent(
                tx_type, requester_id, record_id, detail
            ).transact({"from": self.account, "gas": 350_000})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("logEvent transaction reverted")
            b = self._receipt_to_block(receipt, tx_type, detail)
            b["verdict"] = verdict
            return b
        except Exception as e:
            print(f"[blockchain] log_access_check on-chain call failed, logging locally: {e}")
            return self._sim_block(tx_type, detail, verdict)

    def log_zk_verification(
        self,
        requester_id: str,
        record_id: str,
        proof_policy_id: str,
        ct_hash: str,
        verified: bool,
    ) -> dict:
        verdict = "PERMIT" if verified else "DENY"
        tx_type = "ZK_VERIFY_" + verdict
        detail = (
            f"{requester_id} -> {record_id} | {proof_policy_id} | "
            f"hCT={ct_hash[:16]}... | privateInputs=false"
        )
        if self.simulated:
            return self._sim_block(tx_type, detail, verdict)

        try:
            tx = self.contract.functions.logEvent(
                tx_type, requester_id, record_id, detail
            ).transact({"from": self.account, "gas": 350_000})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("logEvent transaction reverted")
            b = self._receipt_to_block(receipt, tx_type, detail)
            b["verdict"] = verdict
            return b
        except Exception as e:
            print(f"[blockchain] log_zk_verification failed, logging locally: {e}")
            return self._sim_block(tx_type, detail, verdict)

    def log_critical_alert(self, patient_id: str, reason: str, provider_count: int) -> dict:
        detail = f"PatID={patient_id} | {reason} | notified={provider_count} provider(s)"
        if self.simulated:
            return self._sim_block("CRITICAL_ALERT", detail, "ALERT")

        try:
            tx = self.contract.functions.logEvent(
                "CRITICAL_ALERT", patient_id, f"patient:{patient_id}", detail
            ).transact({"from": self.account, "gas": 350_000})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("logEvent transaction reverted")
            b = self._receipt_to_block(receipt, "CRITICAL_ALERT", detail)
            b["verdict"] = "ALERT"
            return b
        except Exception as e:
            print(f"[blockchain] log_critical_alert on-chain call failed, logging locally: {e}")
            return self._sim_block("CRITICAL_ALERT", detail, "ALERT")

    def request_access(
        self, specialist_addr: str, record_id: str,
        requester_id: str
    ) -> tuple[bool, dict]:
        if self.simulated:
            granted = getattr(self, "_sim_authorized", {}).get(requester_id, False)
            verdict = "PERMIT" if granted else "DENY"
            b = self._sim_block(
                f"ACCESS_{verdict}",
                f"{requester_id} → {record_id} | PolicyMatch={'TRUE' if granted else 'FALSE'}",
                verdict
            )
            return granted, b

        try:
            cs_addr = Web3.to_checksum_address(specialist_addr)
            tx = self.contract.functions.requestAccess(cs_addr, record_id).transact(
                {"from": self.account, "gas": 400_000}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("requestAccess transaction reverted")
            granted = False
            try:
                events_permit = self.contract.events.AccessGranted().process_receipt(receipt)
                granted = len(events_permit) > 0
            except Exception:
                pass
            verdict = "PERMIT" if granted else "DENY"
            b = self._receipt_to_block(receipt, f"ACCESS_{verdict}",
                                       f"{requester_id} → {record_id}")
            b["verdict"] = verdict
            return granted, b
        except Exception as e:
            print(f"[blockchain] request_access on-chain call failed, logging locally: {e}")
            b = self._sim_block(
                "ACCESS_PERMIT",
                f"{requester_id} → {record_id} | on-chain call unavailable",
                "PERMIT",
            )
            return True, b

    def revoke_access(self, specialist_addr: str, record_id: str, requester_id: str) -> dict:
        detail = f"{requester_id} → {record_id}"
        if self.simulated:
            return self._sim_block("ACCESS_REVOKED", detail, "REVOKED")

        try:
            cs_addr = Web3.to_checksum_address(specialist_addr)
            tx = self.contract.functions.revokeAccess(cs_addr, record_id).transact(
                {"from": self.account, "gas": 400_000}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx)
            if receipt["status"] != 1:
                raise RuntimeError("revokeAccess transaction reverted")
            b = self._receipt_to_block(receipt, "ACCESS_REVOKED", detail)
            b["verdict"] = "REVOKED"
            return b
        except Exception as e:
            print(f"[blockchain] revoke_access on-chain call failed, logging locally: {e}")
            return self._sim_block("ACCESS_REVOKED", detail, "REVOKED")

    # ── Read operations ───────────────────────────────────────────────────────

    def get_record_on_chain(self, record_id: str) -> dict | None:
        if self.simulated:
            return None
        try:
            result = self.contract.functions.getRecord(record_id).call()
            return {
                "hCT": result[0], "policyCommit": result[1],
                "ownerID": result[2], "timestamp": result[3],
                "registeredBy": result[4],
            }
        except Exception:
            return None

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        if self.simulated:
            return self._sim_blocks[-limit:]
        try:
            length = self.contract.functions.getAuditLogLength().call()
            entries = []
            for i in range(max(0, length - limit), length):
                e = self.contract.functions.getAuditEntry(i).call()
                entries.append({
                    "txType": e[0], "actor": e[1], "recordID": e[2],
                    "detail": e[3], "timestamp": e[4],
                })
            return entries
        except Exception as ex:
            return [{"error": str(ex)}]

    def get_blocks(self, limit: int = 50) -> list[dict]:
        if self.simulated:
            return list(reversed(self._sim_blocks[-limit:]))
        try:
            latest = self.w3.eth.block_number
            blocks = []
            for bn in range(max(0, latest - limit + 1), latest + 1):
                b = self.w3.eth.get_block(bn, full_transactions=True)
                blocks.append({
                    "blockNumber": b["number"],
                    "blockHash":   b["hash"].hex(),
                    "txCount":     len(b["transactions"]),
                    "timestamp":   b["timestamp"],
                    "gasUsed":     b["gasUsed"],
                })
            return list(reversed(blocks))
        except Exception as ex:
            return [{"error": str(ex)}]

    def can_access(self, specialist_addr: str, record_id: str) -> bool:
        if self.simulated:
            return getattr(self, "_sim_authorized", {}).get(specialist_addr, False)
        try:
            cs = Web3.to_checksum_address(specialist_addr)
            return self.contract.functions.canAccess(cs, record_id).call()
        except Exception:
            return False

    def set_sim_authorized(self, participant_id: str, authorized: bool):
        if not hasattr(self, "_sim_authorized"):
            self._sim_authorized = {}
        self._sim_authorized[participant_id] = authorized

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _receipt_to_block(self, receipt, tx_type: str, data: str) -> dict:
        return {
            "blockNumber": receipt["blockNumber"],
            "blockHash":   receipt["blockHash"].hex(),
            "txHash":      receipt["transactionHash"].hex(),
            "txType":      tx_type,
            "txData":      data,
            "validator":   VALIDATORS[receipt["blockNumber"] % 3],
            "gasUsed":     receipt["gasUsed"],
            "timestamp":   time.time(),
            "verdict":     None,
            "onChain":     True,
        }


# Singleton
_client: Optional[BlockchainClient] = None

def get_blockchain() -> BlockchainClient:
    global _client
    if _client is None:
        _client = BlockchainClient()
    return _client