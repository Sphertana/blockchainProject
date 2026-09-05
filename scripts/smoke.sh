#!/usr/bin/env bash
# End-to-end check on the running network: consensus, the 4 access rules through
# the web gateway, and hash-verified download. Assumes `make up` + `make deploy`.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${BASE:-http://localhost:8000}"
COMPOSE="docker compose -f network/docker-compose.yml"
tmp="$(mktemp -d)"
jarT="$tmp/teacher.txt"
jarS="$tmp/student.txt"

pass() { printf "  ok: %s\n" "$1"; }
fail() { printf "  FAIL: %s\n" "$1"; exit 1; }

echo "== chain =="
$COMPOSE exec -T api python - <<'PY'
from app.chain import get_w3, contract_address
w3 = get_w3()
assert w3.is_connected(), "RPC down"
peers = int(w3.net.peer_count)
print("  peers:", peers)
assert peers == 3, f"expected 3 peers, got {peers}"
assert contract_address(), "contract not deployed (run make deploy)"
print("  block:", w3.eth.block_number)
PY
pass "4-validator QBFT network, contract deployed"

STUDENT1="$($COMPOSE exec -T api python -c "import os;print(os.environ['STUDENT1_ADDRESS'])" | tr -d '\r')"

echo "== ensure student1 enrolled =="
$COMPOSE exec -T api python - <<PY
from web3 import Web3
from app.chain import get_w3, get_contract, send_as_teacher
w3 = get_w3(); c = get_contract(w3)
addr = Web3.to_checksum_address("$STUDENT1")
if not c.functions.isEnrolled(addr).call():
    send_as_teacher(w3, c.functions.enroll(addr))
print("  enrolled:", c.functions.isEnrolled(addr).call())
PY

echo "== teacher logs in and publishes a lecture + a locked exam =="
curl -s -o /dev/null -c "$jarT" -d 'username=teacher&password=teacher' "$BASE/login"
echo "smoke lecture $(date)" > "$tmp/lecture.txt"
curl -s -o /dev/null -b "$jarT" -F 'kind=0' -F 'title=Cours smoke' -F "file=@$tmp/lecture.txt" "$BASE/material"
now="$(date +%Y-%m-%dT%H:%M)"
curl -s -o /dev/null -b "$jarT" -F 'kind=2' -F 'title=Examen smoke' -F "exam_at=$now" -F "file=@$tmp/lecture.txt" "$BASE/material"
ids="$($COMPOSE exec -T api python -c "from app.chain import get_w3,get_contract;c=get_contract(get_w3());n=c.functions.materialCount().call();print(n-2,n-1)")"
lecture_id="$(echo "$ids" | awk '{print $1}')"
exam_id="$(echo "$ids" | awk '{print $2}')"
pass "lecture id=$lecture_id, exam id=$exam_id"

echo "== teacher publishes a grade for student1 =="
curl -s -o /dev/null -b "$jarT" -d "address=$STUDENT1&value=A" "$BASE/grade"

echo "== student1 dashboard reflects the rules =="
curl -s -o /dev/null -c "$jarS" -d 'username=student1&password=student1' "$BASE/login"
html="$(curl -s -b "$jarS" "$BASE/dashboard")"
echo "$html" | grep -q "Cours smoke" || fail "student cannot see the lecture"
pass "lecture visible to enrolled student"
echo "$html" | grep -q "verrouillé" || fail "exam is not shown as locked"
pass "exam locked for 24h"
echo "$html" | grep -q "<strong>A</strong>" || fail "student cannot see own grade"
pass "student sees own grade"

echo "== hash-verified download of the lecture =="
curl -s -b "$jarS" "$BASE/material/$lecture_id/download" -o "$tmp/dl.txt"
diff -q "$tmp/lecture.txt" "$tmp/dl.txt" >/dev/null || fail "downloaded file differs"
pass "download matches original (SHA-256 verified on-chain)"

echo "== locked exam cannot be downloaded =="
curl -s -b "$jarS" "$BASE/material/$exam_id/download" | grep -qi "refus" || fail "locked exam was downloadable"
pass "locked exam download refused"

echo
echo "ALL SMOKE CHECKS PASSED"
