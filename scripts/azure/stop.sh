#!/usr/bin/env bash
# Deallocate the VM to stop compute charges (keeps the disk and data).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
az vm deallocate -g "$RG" -n "$VM"
echo "VM deallocated — compute billing stopped. Restart later with: az vm start -g $RG -n $VM"
