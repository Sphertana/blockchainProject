#!/usr/bin/env bash
# Provision one Ubuntu VM (Docker preinstalled) with HTTP open for the demo.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

myip="$(curl -fsS https://api.ipify.org)"

az group create -n "$RG" -l "$LOCATION" 1>/dev/null

az vm create \
  -g "$RG" -n "$VM" \
  --image Ubuntu2204 \
  --size "$VM_SIZE" \
  --admin-username "$ADMIN" \
  --generate-ssh-keys \
  --nsg-rule NONE \
  --public-ip-sku Standard \
  --custom-data @cloud-init.yaml 1>/dev/null

# Web open for the demo; SSH restricted to the machine that ran this script.
nic_id="$(az vm show -g "$RG" -n "$VM" --query 'networkProfile.networkInterfaces[0].id' -o tsv)"
nsg_id="$(az network nic show --ids "$nic_id" --query 'networkSecurityGroup.id' -o tsv)"
nsg_name="${nsg_id##*/}"
az network nsg rule create -g "$RG" --nsg-name "$nsg_name" -n http-demo \
  --priority 900 --access Allow --protocol Tcp --direction Inbound \
  --destination-port-ranges 80 --source-address-prefixes Internet 1>/dev/null
az network nsg rule create -g "$RG" --nsg-name "$nsg_name" -n ssh-admin-only \
  --priority 1000 --access Allow --protocol Tcp \
  --direction Inbound --destination-port-ranges 22 \
  --source-address-prefixes "$myip/32" 1>/dev/null

# Best-effort cost guardrail; ignored if the account lacks the permission.
end="$(date -v+1y +%Y-%m-01 2>/dev/null || date -d '+1 year' +%Y-%m-01)"
az consumption budget create --budget-name classledger-budget --amount 10 \
  --category Cost --time-grain Monthly \
  --start-date "$(date +%Y-%m-01)" --end-date "$end" 2>/dev/null \
  || echo "note: budget not set (insufficient permission) — add it in the portal."

ip="$(az vm show -d -g "$RG" -n "$VM" --query publicIps -o tsv)"
echo "$ip" > .vm_ip
echo "VM ready at $ip"
echo "Add an email threshold to 'classledger-budget' in Cost Management; CLI 2.87 creates the budget but not its notification."
echo "Next: ./deploy.sh   (wait ~1 min for Docker to finish installing)"
