"""
deploy_ganache.py — non-interactive backup deployment path.

Compiles HealthAccess.sol and deploys it to a running Ganache instance,
writing deployment.json in the exact shape blockchain.py expects:
    {"address": "0x...", "abi": [...]}

This is a safety net alongside manual deployment via Remix IDE — same
contract, same result, no browser/IDE required. Useful for quickly
redeploying after any contract tweak, or if live Remix deployment has
any hiccup right before the defense.

Usage:
    python3 deploy_ganache.py [--url http://127.0.0.1:8545] [--out deployment.json]
"""
import argparse
import json
import sys
from pathlib import Path

import solcx
from web3 import Web3

CONTRACT_PATH = Path(__file__).resolve().parent / "HealthAccess.sol"
SOLC_VERSION = "0.8.19"


def compile_contract() -> tuple[list, str]:
    try:
        solcx.set_solc_version(SOLC_VERSION)
    except Exception:
        solcx.install_solc(SOLC_VERSION)
        solcx.set_solc_version(SOLC_VERSION)

    source = CONTRACT_PATH.read_text()
    compiled = solcx.compile_source(
        source, output_values=["abi", "bin"], solc_version=SOLC_VERSION
    )
    _, contract_interface = list(compiled.items())[0]
    return contract_interface["abi"], contract_interface["bin"]


def deploy(url: str, out_path: Path) -> None:
    abi, bytecode = compile_contract()
    print(f"[deploy] Compiled OK — bytecode {len(bytecode)} chars")

    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
    if not w3.is_connected():
        print(f"[deploy] ERROR: could not connect to Ganache at {url}")
        sys.exit(1)

    account = w3.eth.accounts[0]
    print(f"[deploy] Connected — chainId={w3.eth.chain_id}, deployer={account}")

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = Contract.constructor().transact({"from": account, "gas": 3_000_000})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    address = receipt["contractAddress"]
    print(f"[deploy] Deployed at {address} (block {receipt['blockNumber']}, gas {receipt['gasUsed']})")

    out_path.write_text(json.dumps({"address": address, "abi": abi}, indent=2))
    print(f"[deploy] Wrote {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8545")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "deployment.json"))
    args = parser.parse_args()
    deploy(args.url, Path(args.out))
