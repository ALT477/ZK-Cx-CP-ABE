from web3 import Web3
from solcx import compile_source

# 1. Connect to Ganache
w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:7545"))

# 2. Compile Solidity code
with open("contracts/HealthAccess.sol", "r") as f:
    contract_source = f.read()

compiled_sol = compile_source(contract_source, solc_version="0.8.20")
contract_id, contract_interface = compiled_sol.popitem()

# 3. Deploy
account = w3.eth.accounts[0]
Contract = w3.eth.contract(abi=contract_interface['abi'], bytecode=contract_interface['bin'])
tx_hash = Contract.constructor().transact({'from': account})
tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

print("Newly Deployed Contract Address:", tx_receipt.contractAddress)