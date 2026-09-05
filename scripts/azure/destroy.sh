#!/usr/bin/env bash
# Delete everything (resource group and all its resources).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
az group delete -n "$RG" --yes --no-wait
echo "Deletion of resource group '$RG' started."
