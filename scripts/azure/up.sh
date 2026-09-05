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
  --os-disk-size-gb 30 \
  --storage-sku StandardSSD_LRS \
  --admin-username "$ADMIN" \
  --generate-ssh-keys \
  --nsg-rule NONE \
  --public-ip-sku Standard \
  --tags project=classledger environment=demo \
  --custom-data @cloud-init.yaml 1>/dev/null

az vm auto-shutdown -g "$RG" -n "$VM" --time 2300 1>/dev/null

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
subscription_id="$(az account show --query id -o tsv)"
budget_email="${AZ_BUDGET_EMAIL:-$(az account show --query user.name -o tsv)}"
az rest --method put \
  --url "https://management.azure.com/subscriptions/$subscription_id/providers/Microsoft.Consumption/budgets/classledger-budget?api-version=2024-08-01" \
  --headers 'Content-Type=application/json' \
  --body "{\"properties\":{\"category\":\"Cost\",\"amount\":10,\"timeGrain\":\"Monthly\",\"timePeriod\":{\"startDate\":\"$(date +%Y-%m-01)T00:00:00Z\",\"endDate\":\"${end}T00:00:00Z\"},\"notifications\":{\"Actual_80_Percent\":{\"enabled\":true,\"operator\":\"GreaterThanOrEqualTo\",\"threshold\":80,\"thresholdType\":\"Actual\",\"locale\":\"fr-fr\",\"contactEmails\":[\"$budget_email\"],\"contactRoles\":[],\"contactGroups\":[]}}}}" \
  1>/dev/null 2>&1 \
  || echo "note: budget not set (insufficient permission) — add it in the portal."

ip="$(az vm show -d -g "$RG" -n "$VM" --query publicIps -o tsv)"
echo "$ip" > .vm_ip
echo "VM ready at $ip"
echo "Budget 'classledger-budget': 10 billing-currency units/month, email alert at 80%."
echo "Next: ./deploy.sh   (wait ~1 min for Docker to finish installing)"
