#!/usr/bin/env bash
# Generate QBFT node keys + genesis (once), then lay them out for Docker Compose.
set -euo pipefail
cd "$(dirname "$0")/../.."

BESU_IMAGE="${BESU_IMAGE:-hyperledger/besu:26.2.0}"

# Besu 26.2 rejects a --to directory created on a macOS bind mount mid-command.
docker run --rm -v "$PWD/network:/network" --entrypoint sh "$BESU_IMAGE" -c '
  rm -rf /network/networkFiles /network/data /tmp/generated
  besu operator generate-blockchain-config \
    --config-file=/network/qbft-config.json \
    --to=/tmp/generated \
    --private-key-file-name=key
  cp -R /tmp/generated /network/networkFiles
'

python3 scripts/network/layout.py
echo "Network material ready in network/data/ (keys are git-ignored)."
