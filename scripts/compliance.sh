#!/usr/bin/env bash
# Prove P2P replication and QBFT quorum behavior on the running 4-node network.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose --env-file .env -f network/docker-compose.yml"
stopped=()

restore_validators() {
  if ((${#stopped[@]})); then
    $COMPOSE start "${stopped[@]}" >/dev/null 2>&1 || true
  fi
}
trap restore_validators EXIT

pass() { printf "  ok: %s\n" "$1"; }

echo "== P2P replication and transparency =="
$COMPOSE exec -T api python - <<'PY'
import json
import urllib.request

nodes = ("validator1", "validator2", "validator3", "validator4")


def rpc(node, method, params=None):
    request = urllib.request.Request(
        f"http://{node}:8545",
        json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.load(response)
    assert "error" not in body, body
    return body["result"]


heights = {node: int(rpc(node, "eth_blockNumber"), 16) for node in nodes}
peers = {node: int(rpc(node, "net_peerCount"), 16) for node in nodes}
assert all(count == 3 for count in peers.values()), peers

common_height = min(heights.values())
tag = hex(common_height)
hashes = {node: rpc(node, "eth_getBlockByNumber", [tag, False])["hash"] for node in nodes}
assert len(set(hashes.values())) == 1, hashes

validator_sets = {
    node: tuple(sorted(rpc(node, "qbft_getValidatorsByBlockNumber", [tag])))
    for node in nodes
}
assert all(len(validators) == 4 for validators in validator_sets.values()), validator_sets
assert len(set(validator_sets.values())) == 1, validator_sets

print("  heights:", heights)
print("  peer counts:", peers)
print("  common block:", common_height, next(iter(hashes.values())))
print("  validators:", len(next(iter(validator_sets.values()))))
PY
pass "all validators have 3 peers and the same block hash"

echo "== QBFT tolerates one validator down (3/4 quorum) =="
$COMPOSE stop validator4 >/dev/null
stopped=(validator4)
$COMPOSE exec -T api python - <<'PY'
from app.chain import get_w3, teacher_account

w3 = get_w3()
account = teacher_account(w3)
before = w3.eth.block_number
transaction = {
    "from": account.address,
    "to": account.address,
    "value": 0,
    "nonce": w3.eth.get_transaction_count(account.address),
    "gas": 21_000,
    "gasPrice": 0,
    "chainId": w3.eth.chain_id,
}
signed = account.sign_transaction(transaction)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
assert receipt.status == 1 and receipt.blockNumber > before, (before, receipt)
assert int(w3.net.peer_count) == 2
print("  finalized block:", receipt.blockNumber, "with peers:", int(w3.net.peer_count))
PY
pass "a transaction is finalized with one validator unavailable"

echo "== QBFT refuses to finalize without quorum (2/4) =="
$COMPOSE stop validator3 >/dev/null
stopped=(validator3 validator4)
pending_hash="$($COMPOSE exec -T api python - <<'PY'
from web3.exceptions import TimeExhausted

from app.chain import get_w3, teacher_account

w3 = get_w3()
account = teacher_account(w3)
transaction = {
    "from": account.address,
    "to": account.address,
    "value": 0,
    "nonce": w3.eth.get_transaction_count(account.address),
    "gas": 21_000,
    "gasPrice": 0,
    "chainId": w3.eth.chain_id,
}
signed = account.sign_transaction(transaction)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
try:
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=7, poll_latency=0.5)
except TimeExhausted:
    print(tx_hash.hex())
else:
    raise AssertionError("transaction finalized without the required 3/4 quorum")
PY
)"
pass "a transaction remains pending when only two validators are available"

echo "== Recovery and ledger convergence =="
$COMPOSE start validator3 validator4 >/dev/null
stopped=()
$COMPOSE exec -T -e PENDING_HASH="$pending_hash" api python - <<'PY'
import json
import os
import time
import urllib.request

from app.chain import get_w3

w3 = get_w3()
receipt = w3.eth.wait_for_transaction_receipt(os.environ["PENDING_HASH"], timeout=60)
assert receipt.status == 1
target = receipt.blockNumber
nodes = ("validator1", "validator2", "validator3", "validator4")


def rpc(node, method, params=None):
    request = urllib.request.Request(
        f"http://{node}:8545",
        json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}).encode(),
        {"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)["result"]


deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        heights = {node: int(rpc(node, "eth_blockNumber"), 16) for node in nodes}
        peers = {node: int(rpc(node, "net_peerCount"), 16) for node in nodes}
        if min(heights.values()) >= target and all(count == 3 for count in peers.values()):
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise AssertionError("validators did not reconnect and catch up")

tag = hex(target)
hashes = {node: rpc(node, "eth_getBlockByNumber", [tag, False])["hash"] for node in nodes}
assert len(set(hashes.values())) == 1, hashes
print("  recovered heights:", heights)
print("  recovered peers:", peers)
print("  shared recovered block:", target, next(iter(hashes.values())))
PY
pass "all four copies converge to the same canonical chain after recovery"

echo
echo "ALL P2P / QBFT COMPLIANCE CHECKS PASSED"