"""Deploy ClassLedger from the committed artifact and record its address."""

import os

from app.chain import ARTIFACT, get_w3, save_address, teacher_account, wait_for_rpc


def main() -> None:
    w3 = get_w3()
    if not wait_for_rpc(w3):
        raise SystemExit("blockchain RPC not reachable")
    acct = teacher_account(w3)
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
    save_address(receipt.contractAddress)
    print("ClassLedger deployed at", receipt.contractAddress)


if __name__ == "__main__":
    main()
