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
NONE, PENDING, ENROLLED, REJECTED = 0, 1, 2, 3
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
    assert c.functions.classOrganization().call({"from": outsider}) == "ISEP, fall 2026"


# Only the teacher may write.
def test_only_teacher_writes(env):
    _, c, _, alice, _, _ = env
    with pytest.raises(REVERT):
        c.functions.enroll(alice).transact({"from": alice})


# Enrollment: the student asks for themselves, the teacher decides.
def test_student_requests_and_teacher_approves(env):
    _, c, teacher, alice, _, _ = env
    assert c.functions.statusOf(alice).call() == NONE
    c.functions.requestEnrollment().transact({"from": alice})
    assert c.functions.statusOf(alice).call() == PENDING
    assert c.functions.isEnrolled(alice).call() is False
    assert c.functions.pendingApplicants().call({"from": teacher}) == [alice]
    c.functions.approveEnrollment(alice).transact({"from": teacher})
    assert c.functions.statusOf(alice).call() == ENROLLED
    assert c.functions.isEnrolled(alice).call() is True
    assert c.functions.pendingApplicants().call({"from": teacher}) == []


def test_only_teacher_decides_and_queue_is_private(env):
    _, c, teacher, alice, bob, _ = env
    c.functions.requestEnrollment().transact({"from": alice})
    with pytest.raises(REVERT):
        c.functions.approveEnrollment(alice).transact({"from": bob})
    with pytest.raises(REVERT):
        c.functions.approveEnrollment(alice).transact({"from": alice})  # no self-approval
    with pytest.raises(REVERT):
        c.functions.pendingApplicants().call({"from": bob})
    assert c.functions.isEnrolled(alice).call() is False
    c.functions.rejectEnrollment(alice).transact({"from": teacher})
    assert c.functions.statusOf(alice).call() == REJECTED


def test_pending_and_rejected_students_have_no_access(env):
    _, c, teacher, alice, _, _ = env
    add(c, teacher, LECTURE, "Intro")
    c.functions.requestEnrollment().transact({"from": alice})
    with pytest.raises(REVERT):
        c.functions.getFile(0).call({"from": alice})  # pending is not enrolled
    c.functions.rejectEnrollment(alice).transact({"from": teacher})
    with pytest.raises(REVERT):
        c.functions.getFile(0).call({"from": alice})
    c.functions.requestEnrollment().transact({"from": alice})  # a refusal is not final
    c.functions.approveEnrollment(alice).transact({"from": teacher})
    assert c.functions.getFile(0).call({"from": alice})[0] == "ref"


def test_cannot_apply_twice(env):
    _, c, _, alice, _, _ = env
    c.functions.requestEnrollment().transact({"from": alice})
    with pytest.raises(REVERT):
        c.functions.requestEnrollment().transact({"from": alice})


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


def test_lab_visible_to_enrolled_only(env):
    _, c, teacher, alice, _, outsider = env
    add(c, teacher, LAB, "Lab 1")
    assert c.functions.canAccess(0).call({"from": alice}) is False
    c.functions.enroll(alice).transact({"from": teacher})
    assert c.functions.getFile(0).call({"from": alice})[0] == "ref"
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


def test_correction_locked_for_24h(env):
    w3, c, teacher, alice, _, outsider = env
    c.functions.enroll(alice).transact({"from": teacher})
    exam_at = w3.eth.get_block("latest")["timestamp"]
    add(c, teacher, EXAM, "Midterm", exam_at=exam_at)
    add(c, teacher, CORRECTION, "Midterm correction", exam_at=exam_at, has_prev=True, prev_id=0)
    assert c.functions.canAccess(1).call({"from": alice}) is False
    assert c.functions.canAccess(1).call({"from": outsider}) is False
    warp(w3, DAY + 1)
    assert c.functions.canAccess(1).call({"from": alice}) is True


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
    _, title0, _, _, _, _, _ = c.functions.getMeta(0).call({"from": teacher})
    _, _, _, has_prev1, prev_id1, _, _ = c.functions.getMeta(1).call({"from": teacher})
    assert title0 == "Exam v1"
    assert (has_prev1, prev_id1) == (True, 0)
