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
jarS2="$tmp/student2.txt"

pass() { printf "  ok: %s\n" "$1"; }
fail() { printf "  FAIL: %s\n" "$1"; exit 1; }

echo "== chain =="
$COMPOSE exec -T api python - <<'PY'
import time

from app.chain import get_w3, contract_address, wait_for_rpc
w3 = get_w3()
assert wait_for_rpc(w3, tries=60, delay=2), "RPC down"
for _ in range(60):
    peers = int(w3.net.peer_count)
    if peers == 3:
        break
    time.sleep(2)
print("  peers:", peers)
assert peers == 3, f"expected 3 peers, got {peers}"
assert contract_address(), "contract not deployed (run make deploy)"
print("  block:", w3.eth.block_number)
PY
pass "4-validator QBFT network, contract deployed"

STUDENT1="$($COMPOSE exec -T api python -c "import os;print(os.environ['STUDENT1_ADDRESS'])" | tr -d '\r')"
TEACHER_PASSWORD="$($COMPOSE exec -T api python -c "import os;print(os.environ['TEACHER_PASSWORD'])" | tr -d '\r')"
STUDENT1_PASSWORD="$($COMPOSE exec -T api python -c "import os;print(os.environ['STUDENT1_PASSWORD'])" | tr -d '\r')"
STUDENT2_PASSWORD="$($COMPOSE exec -T api python -c "import os;print(os.environ['STUDENT2_PASSWORD'])" | tr -d '\r')"

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
curl -s -o /dev/null -c "$jarT" -d 'username=teacher' --data-urlencode "password=$TEACHER_PASSWORD" "$BASE/login"
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
curl -s -o /dev/null -c "$jarS" -d 'username=student1' --data-urlencode "password=$STUDENT1_PASSWORD" "$BASE/login"
html="$(curl -s -b "$jarS" "$BASE/dashboard")"
echo "$html" | grep -q "Cours smoke" || fail "student cannot see the lecture"
pass "lecture visible to enrolled student"
echo "$html" | grep -q "verrouillé" || fail "exam is not shown as locked"
pass "exam locked for 24h"
echo "$html" | grep -q "<strong>A</strong>" || fail "student cannot see own grade"
pass "student sees own grade"

echo "== student2 cannot see student1's grade =="
curl -s -o /dev/null -c "$jarS2" -d 'username=student2' --data-urlencode "password=$STUDENT2_PASSWORD" "$BASE/login"
html2="$(curl -s -b "$jarS2" "$BASE/dashboard")"
echo "$html2" | grep -q "<strong>A</strong>" && fail "student2 can see student1's grade"
pass "student2 cannot see student1's grade"

echo "== hash-verified download of the lecture =="
curl -s -b "$jarS" "$BASE/material/$lecture_id/download" -o "$tmp/dl.txt"
diff -q "$tmp/lecture.txt" "$tmp/dl.txt" >/dev/null || fail "downloaded file differs"
pass "download matches original (SHA-256 verified on-chain)"

echo "== tampered file is rejected =="
ref="$($COMPOSE exec -T api python -c "from app.chain import get_w3,get_contract,teacher_account;w=get_w3();c=get_contract(w);print(c.functions.getFile($lecture_id).call({'from':teacher_account(w).address})[0])" | tr -d '\r')"
$COMPOSE exec -T -e FILE_REF="$ref" api python - <<'PY'
import os
from pathlib import Path

path = Path("data/files") / os.environ["FILE_REF"]
Path("/tmp/smoke-original").write_bytes(path.read_bytes())
with path.open("ab") as stream:
    stream.write(b"tampered")
PY
tamper_response="$(curl -s -b "$jarS" "$BASE/material/$lecture_id/download")"
$COMPOSE exec -T -e FILE_REF="$ref" api python - <<'PY'
import os
from pathlib import Path

path = Path("data/files") / os.environ["FILE_REF"]
path.write_bytes(Path("/tmp/smoke-original").read_bytes())
PY
echo "$tamper_response" | grep -qi "compromise" || fail "tampered file was not rejected"
pass "tampered file rejected by on-chain SHA-256 check"

echo "== locked exam cannot be downloaded =="
curl -s -b "$jarS" "$BASE/material/$exam_id/download" | grep -qi "refus" || fail "locked exam was downloadable"
pass "locked exam download refused"

echo
echo "ALL SMOKE CHECKS PASSED"
