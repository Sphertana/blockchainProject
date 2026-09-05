"""Seed the demo: enroll the two students and add one sample lecture."""

import os

from web3 import Web3

from app.chain import get_contract, get_w3, send_as_teacher, wait_for_rpc


def main() -> None:
    w3 = get_w3()
    wait_for_rpc(w3)
    c = get_contract(w3)
    if c is None:
        raise SystemExit("contract not deployed — run `make deploy` first")

    for var in ("STUDENT1_ADDRESS", "STUDENT2_ADDRESS"):
        addr = Web3.to_checksum_address(os.environ[var])
        if not c.functions.isEnrolled(addr).call():
            send_as_teacher(w3, c.functions.enroll(addr))
            print("enrolled", addr)

    send_as_teacher(
        w3,
        c.functions.addMaterial(0, "Welcome lecture", "seed-ref", b"\x00" * 32, 0, False, 0),
    )
    print("added sample lecture; materials:", c.functions.materialCount().call())


if __name__ == "__main__":
    main()
