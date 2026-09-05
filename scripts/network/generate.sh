#!/usr/bin/env bash
# Generate QBFT node keys + genesis (once), then lay them out for Docker Compose.
set -euo pipefail
cd "$(dirname "$0")/../.."

BESU_IMAGE="${BESU_IMAGE:-hyperledger/besu:24.12.0}"

# Clean previous material inside a container: on Linux, Besu writes root-owned
# files that a plain host `rm` could not delete.
docker run --rm -v "$PWD/network:/network" --entrypoint sh "$BESU_IMAGE" \
  -c "rm -rf /network/networkFiles /network/data"

docker run --rm -v "$PWD/network:/network" "$BESU_IMAGE" \
  operator generate-blockchain-config \
  --config-file=/network/qbft-config.json \
  --to=/network/networkFiles \
  --private-key-file-name=key

python3 scripts/network/layout.py
echo "Network material ready in network/data/ (keys are git-ignored)."
