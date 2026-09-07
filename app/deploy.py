"""Deploy ClassLedger from the committed artifact and record its address."""

import os

from web3 import Web3
from web3.exceptions import ContractLogicError

from app.chain import ARTIFACT, contract_address, get_w3, save_address, teacher_account, wait_for_rpc


def main() -> None:
    w3 = get_w3()
    if not wait_for_rpc(w3):
        raise SystemExit("blockchain RPC not reachable")

    acct = teacher_account(w3)
    existing = contract_address()
    if existing:
        try:
            address = Web3.to_checksum_address(existing)
            if w3.eth.get_code(address):
                current = w3.eth.contract(address=address, abi=ARTIFACT["abi"])
                current.functions.statusOf(acct.address).call()
                print("ClassLedger already deployed at", existing)
                return
            print("Existing ClassLedger address has no code; redeploying")
        except (ValueError, ContractLogicError):
            print("Existing ClassLedger is incompatible; redeploying current version")
            pass

    factory = w3.eth.contract(abi=ARTIFACT["abi"], bytecode=ARTIFACT["bytecode"])
    description = os.environ.get("CLASS_DESCRIPTION", "Blockchain 101 — distributed ledgers")
    organization = os.environ.get("CLASS_ORGANIZATION", "ISEP — Fall 2026, Room B12, Fridays 10:00")
    tx = factory.constructor(description, organization).build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": 4_000_000,
            "gasPrice": 0,
            "chainId": w3.eth.chain_id,
        }
    )
    signed = acct.sign_transaction(tx)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    if receipt.status != 1 or not receipt.contractAddress:
        raise SystemExit("ClassLedger deployment reverted")
    if not w3.eth.get_code(receipt.contractAddress):
        raise SystemExit("ClassLedger deployment produced no contract code")
    save_address(receipt.contractAddress)
    print("ClassLedger deployed at", receipt.contractAddress)


if __name__ == "__main__":
    main()
