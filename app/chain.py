"""Blockchain gateway: connect to the Besu node, load the contract, read as a
given user (msg.sender via eth_call), and write as the teacher (signed tx)."""

import json
import os
import time
from pathlib import Path

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ARTIFACT = json.loads(Path("contracts/artifacts/ClassLedger.json").read_text())
ADDRESS_FILE = Path("data/contract-address.txt")


def get_w3() -> Web3:
    rpc = os.environ.get("RPC_URL", "http://validator1:8545")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
    # Besu (QBFT) puts >32 bytes in block extraData; this lets web3 parse blocks.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def wait_for_rpc(w3: Web3, tries: int = 60, delay: float = 2.0) -> bool:
    for _ in range(tries):
        try:
            if w3.is_connected():
                _ = w3.eth.block_number
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def contract_address() -> str | None:
    if os.environ.get("CONTRACT_ADDRESS"):
        return os.environ["CONTRACT_ADDRESS"]
    if ADDRESS_FILE.exists():
        return ADDRESS_FILE.read_text().strip() or None
    return None


def save_address(addr: str) -> None:
    ADDRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADDRESS_FILE.write_text(addr)


def get_contract(w3: Web3):
    addr = contract_address()
    if not addr:
        return None
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ARTIFACT["abi"])


def teacher_account(w3: Web3):
    return w3.eth.account.from_key(os.environ["TEACHER_PRIVATE_KEY"])


def send_as_teacher(w3: Web3, fn):
    """Sign and send a contract call as the teacher on the zero-gas chain."""
    acct = teacher_account(w3)
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": 3_000_000,
            "gasPrice": 0,
            "chainId": w3.eth.chain_id,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise RuntimeError(f"transaction reverted: {tx_hash.hex()}")
    return receipt
