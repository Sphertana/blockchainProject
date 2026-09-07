"""Seed the demo: put the two students in the class and add one sample lecture.

student1 is added straight from the teacher's roster; student2 goes through the
real workflow (they sign their own request, the teacher approves) so the demo
starts with both paths already exercised on-chain.
"""

import os

from web3 import Web3

from app import files
from app.chain import get_contract, get_w3, send_as, send_as_teacher, wait_for_rpc


def main() -> None:
    w3 = get_w3()
    wait_for_rpc(w3)
    c = get_contract(w3)
    if c is None:
        raise SystemExit("contract not deployed — run `make deploy` first")

    addr1 = Web3.to_checksum_address(os.environ["STUDENT1_ADDRESS"])
    if not c.functions.isEnrolled(addr1).call():
        send_as_teacher(w3, c.functions.enroll(addr1))
        print("enrolled directly", addr1)

    addr2 = Web3.to_checksum_address(os.environ["STUDENT2_ADDRESS"])
    if not c.functions.isEnrolled(addr2).call():
        if c.functions.statusOf(addr2).call() != 1:  # 1 = PENDING
            send_as(w3, c.functions.requestEnrollment(), os.environ["STUDENT2_PRIVATE_KEY"])
            print("enrollment requested by", addr2)
        send_as_teacher(w3, c.functions.approveEnrollment(addr2))
        print("approved", addr2)

    if c.functions.materialCount().call() == 0:
        content = b"Welcome to Blockchain 101.\n"
        ref, digest = files.save(content, "welcome.txt")
        try:
            send_as_teacher(
                w3, c.functions.addMaterial(0, "Welcome lecture", ref, digest, 0, False, 0)
            )
        except Exception:
            files.delete(ref)
            raise
        print("added sample lecture")
    else:
        print("sample material already present")
    print("materials:", c.functions.materialCount().call())


if __name__ == "__main__":
    main()
