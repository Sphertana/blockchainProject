"""Rule tests for ClassLedger, run on an in-process EVM (no Besu needed).

Each of the four access rules from the assignment has a matching test.
"""

import json
from pathlib import Path

import pytest
from eth_tester.exceptions import TransactionFailed
from web3 import EthereumTesterProvider, Web3
from web3.exceptions import ContractLogicError

ARTIFACT = json.loads(Path("contracts/artifacts/ClassLedger.json").read_text())

# A revert surfaces as one or the other depending on the web3/eth-tester build.
REVERT = (ContractLogicError, TransactionFailed)

LECTURE, LAB, EXAM, CORRECTION = 0, 1, 2, 3
DAY = 24 * 3600


@pytest.fixture
def env():
    w3 = Web3(EthereumTesterProvider())
    teacher, alice, bob, outsider = w3.eth.accounts[:4]
    Factory = w3.eth.contract(abi=ARTIFACT["abi"], bytecode=ARTIFACT["bytecode"])
    tx = Factory.constructor("Blockchain 101", "ISEP, fall 2026").transact({"from": teacher})
    addr = w3.eth.wait_for_transaction_receipt(tx)["contractAddress"]
    c = w3.eth.contract(address=addr, abi=ARTIFACT["abi"])
    return w3, c, teacher, alice, bob, outsider


def warp(w3, seconds):
    tester = w3.provider.ethereum_tester
    tester.time_travel(w3.eth.get_block("latest")["timestamp"] + seconds)
    tester.mine_block()


def add(c, teacher, kind, title, exam_at=0, has_prev=False, prev_id=0):
    tx = c.functions.addMaterial(kind, title, "ref", b"\x00" * 32, exam_at, has_prev, prev_id).transact(
        {"from": teacher}
    )
    return c.w3.eth.wait_for_transaction_receipt(tx)


# Rule: description & organization are public.
def test_class_info_is_public(env):
    _, c, _, _, _, outsider = env
    assert c.functions.classDescription().call({"from": outsider}) == "Blockchain 101"


# Only the teacher may write.
def test_only_teacher_writes(env):
    _, c, _, alice, _, _ = env
    with pytest.raises(REVERT):
        c.functions.enroll(alice).transact({"from": alice})


# Rule: lectures/labs visible to enrolled students only.
def test_lecture_visible_to_enrolled_only(env):
    w3, c, teacher, alice, _, outsider = env
    add(c, teacher, LECTURE, "Intro")
    with pytest.raises(REVERT):
        c.functions.getFile(0).call({"from": alice})  # not enrolled yet
    c.functions.enroll(alice).transact({"from": teacher})
    ref, _ = c.functions.getFile(0).call({"from": alice})
    assert ref == "ref"
    assert c.functions.canAccess(0).call({"from": outsider}) is False


# Rule: exams/corrections only 24h after the exam date.
def test_exam_locked_for_24h(env):
    w3, c, teacher, alice, _, _ = env
    c.functions.enroll(alice).transact({"from": teacher})
    exam_at = w3.eth.get_block("latest")["timestamp"]
    add(c, teacher, EXAM, "Midterm", exam_at=exam_at)
    assert c.functions.canAccess(0).call({"from": alice}) is False
    assert c.functions.canAccess(0).call({"from": teacher}) is True  # teacher always
    warp(w3, DAY + 1)
    assert c.functions.canAccess(0).call({"from": alice}) is True


# Rule: a student sees only their own grade.
def test_grade_is_private(env):
    _, c, teacher, alice, bob, _ = env
    c.functions.enroll(alice).transact({"from": teacher})
    c.functions.enroll(bob).transact({"from": teacher})
    c.functions.publishGrade(alice, "A").transact({"from": teacher})
    published, value = c.functions.myGrade().call({"from": alice})
    assert (published, value) == (True, "A")
    assert c.functions.myGrade().call({"from": bob})[0] is False
    with pytest.raises(REVERT):
        c.functions.gradeOf(alice).call({"from": bob})


# Immutability: a correction is a new version; the original stays.
def test_revision_is_append_only(env):
    w3, c, teacher, _, _, _ = env
    exam_at = w3.eth.get_block("latest")["timestamp"]
    add(c, teacher, EXAM, "Exam v1", exam_at=exam_at)
    add(c, teacher, CORRECTION, "Exam correction", exam_at=exam_at, has_prev=True, prev_id=0)
    assert c.functions.materialCount().call() == 2
    _, title0, _, _, _, _ = c.functions.getMeta(0).call({"from": teacher})
    _, _, _, has_prev1, prev_id1, _ = c.functions.getMeta(1).call({"from": teacher})
    assert title0 == "Exam v1"
    assert (has_prev1, prev_id1) == (True, 0)
