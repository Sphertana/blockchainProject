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
jarN="$tmp/newcomer.txt"

pass() { printf "  ok: %s\n" "$1"; }
fail() { printf "  FAIL: %s\n" "$1"; exit 1; }
csrf_from_html() { sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -1; }
login() {
  local jar="$1" username="$2" password="$3" token
  token="$(curl -fsS -c "$jar" "$BASE/login" | csrf_from_html)"
  curl -fsS -o /dev/null -b "$jar" -c "$jar" \
    -d "username=$username" --data-urlencode "password=$password" \
    --data-urlencode "csrf_token=$token" "$BASE/login"
}

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
login "$jarT" teacher "$TEACHER_PASSWORD"
teacher_html="$(curl -fsS -b "$jarT" -c "$jarT" "$BASE/dashboard")"
teacher_csrf="$(printf '%s' "$teacher_html" | csrf_from_html)"
csrf_status="$(curl -s -o /dev/null -w '%{http_code}' -b "$jarT" \
  -d "address=$STUDENT1&value=forged" "$BASE/grade")"
[[ "$csrf_status" == "403" ]] || fail "teacher action accepted without CSRF token"
pass "state-changing action rejects a missing CSRF token"

echo "smoke lecture $(date)" > "$tmp/lecture.txt"
curl -fsS -o /dev/null -b "$jarT" -c "$jarT" -F "csrf_token=$teacher_csrf" \
  -F 'kind=0' -F 'title=Cours smoke' -F "file=@$tmp/lecture.txt" "$BASE/material"
now="$(date +%Y-%m-%dT%H:%M)"
curl -fsS -o /dev/null -b "$jarT" -c "$jarT" -F "csrf_token=$teacher_csrf" \
  -F 'kind=2' -F 'title=Examen smoke' -F "exam_at=$now" -F "file=@$tmp/lecture.txt" "$BASE/material"
ids="$($COMPOSE exec -T api python -c "from app.chain import get_w3,get_contract;c=get_contract(get_w3());n=c.functions.materialCount().call();print(n-2,n-1)")"
lecture_id="$(echo "$ids" | awk '{print $1}')"
exam_id="$(echo "$ids" | awk '{print $2}')"
pass "lecture id=$lecture_id, exam id=$exam_id"

echo "== teacher publishes a grade for student1 =="
curl -fsS -o /dev/null -b "$jarT" -c "$jarT" \
  -d "address=$STUDENT1&value=A" --data-urlencode "csrf_token=$teacher_csrf" "$BASE/grade"
raw_grade="$($COMPOSE exec -T api python - <<PY | tr -d '\r'
from web3 import Web3
from app.chain import get_w3, get_contract, teacher_account
w3 = get_w3(); c = get_contract(w3)
print(c.functions.gradeOf(Web3.to_checksum_address("$STUDENT1")).call({"from": teacher_account(w3).address})[1])
PY
)"
[[ "$raw_grade" == enc:v1:* && "$raw_grade" != "A" ]] \
  || fail "grade is stored in plaintext on-chain"
pass "grade is AES-256-GCM ciphertext in raw chain storage"

echo "== student1 dashboard reflects the rules =="
login "$jarS" student1 "$STUDENT1_PASSWORD"
html="$(curl -s -b "$jarS" "$BASE/dashboard")"
echo "$html" | grep -q "Cours smoke" || fail "student cannot see the lecture"
pass "lecture visible to enrolled student"
echo "$html" | grep -q "verrouillé" || fail "exam is not shown as locked"
pass "exam locked for 24h"
echo "$html" | grep -q 'grade-value">A<' || fail "student cannot see own grade"
pass "student sees own grade"

echo "== student2 cannot see student1's grade =="
login "$jarS2" student2 "$STUDENT2_PASSWORD"
html2="$(curl -s -b "$jarS2" "$BASE/dashboard")"
echo "$html2" | grep -q 'grade-value">A<' && fail "student2 can see student1's grade"
pass "student2 cannot see student1's grade"

echo "== sign-up, self-service request, teacher approval =="
NEW="smoke$(date +%s)"
register_csrf="$(curl -fsS -c "$jarN" "$BASE/register" | csrf_from_html)"
curl -fsS -o /dev/null -b "$jarN" -c "$jarN" -d "username=$NEW" \
  --data-urlencode 'password=smoke-passw0rd' --data-urlencode 'confirm=smoke-passw0rd' \
  --data-urlencode "csrf_token=$register_csrf" "$BASE/register"
new_html="$(curl -fsS -b "$jarN" -c "$jarN" "$BASE/dashboard")"
new_csrf="$(printf '%s' "$new_html" | csrf_from_html)"
printf '%s' "$new_html" | grep -q "pas encore demand" || fail "new account is not in the 'no request' state"
pass "account created with its own wallet, no access yet"

curl -s -b "$jarN" "$BASE/material/$lecture_id/download" | grep -qi "refus" || fail "non-enrolled user could download a lecture"
pass "non-enrolled user refused by the contract"

curl -fsS -o /dev/null -b "$jarN" -c "$jarN" \
  --data-urlencode "csrf_token=$new_csrf" "$BASE/enrollment/request"
curl -s -b "$jarN" "$BASE/dashboard" | grep -q "En attente de la décision" || fail "request not registered on-chain"
pass "enrollment request signed by the student and mined"

NEW_ADDR="$($COMPOSE exec -T api python -c \
  "import sqlite3;print(sqlite3.connect('data/app.db').execute('select address from users where username=?',('$NEW',)).fetchone()[0])" | tr -d '\r')"
curl -s -b "$jarT" "$BASE/dashboard" | grep -q "$NEW" || fail "request not visible in the teacher queue"
pass "request queued for the teacher"

curl -fsS -o /dev/null -b "$jarT" -c "$jarT" \
  -d "address=$NEW_ADDR&action=approve" --data-urlencode "csrf_token=$teacher_csrf" \
  "$BASE/enrollment/decide"
curl -s -b "$jarN" "$BASE/dashboard" | grep -q "Cours smoke" || fail "approved student still has no access"
pass "teacher approval unlocks the class materials"

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
