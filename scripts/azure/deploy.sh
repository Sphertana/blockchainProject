#!/usr/bin/env bash
# Copy the repo to the VM and start the HTTPS stack.
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/azure/config.sh
ip="$(cat scripts/azure/.vm_ip)"

# Also works for VMs created before HTTPS support was added.
subscription_id="$(az account show --query id -o tsv)"
dns_label="${AZ_DNS_LABEL:-classledger-${subscription_id%%-*}}"
nic_id="$(az vm show -g "$RG" -n "$VM" --query 'networkProfile.networkInterfaces[0].id' -o tsv)"
pip_id="$(az network nic show --ids "$nic_id" --query 'ipConfigurations[0].publicIPAddress.id' -o tsv)"
az network public-ip update --ids "$pip_id" --dns-name "$dns_label" 1>/dev/null
host="$(az network public-ip show --ids "$pip_id" --query dnsSettings.fqdn -o tsv)"
echo "$host" > scripts/azure/.vm_host
nsg_id="$(az network nic show --ids "$nic_id" --query 'networkSecurityGroup.id' -o tsv)"
az network nsg rule create -g "$RG" --nsg-name "${nsg_id##*/}" -n https-demo \
  --priority 910 --access Allow --protocol Tcp --direction Inbound \
  --destination-port-ranges 443 --source-address-prefixes Internet 1>/dev/null

# Push code only — never local secrets, keys, or chain data.
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '.env' --exclude '.github/skills' \
  --exclude 'EXPLICATIONS_PERSO.md' --exclude 'scripts/azure/.demo_credentials' \
  --exclude 'EXPLICATIONS_PERSO.pdf' \
  --exclude 'scripts/azure/.vm_ip' --exclude 'scripts/azure/.vm_host' \
  --exclude 'data' \
  --exclude 'network/data' --exclude 'network/networkFiles' \
  ./ "$ADMIN@$ip:~/classledger/"

ssh "$ADMIN@$ip" PUBLIC_HOST="$host" 'bash -s' <<'REMOTE'
set -euo pipefail
sudo cloud-init status --wait
cd ~/classledger
if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s/^SESSION_SECRET=.*/SESSION_SECRET=$(openssl rand -hex 32)/" .env
  sed -i "s/^WALLET_SECRET=.*/WALLET_SECRET=$(openssl rand -hex 32)/" .env
  sed -i "s/^TEACHER_PASSWORD=.*/TEACHER_PASSWORD=$(openssl rand -hex 8)/" .env
  sed -i "s/^STUDENT1_PASSWORD=.*/STUDENT1_PASSWORD=$(openssl rand -hex 8)/" .env
  sed -i "s/^STUDENT2_PASSWORD=.*/STUDENT2_PASSWORD=$(openssl rand -hex 8)/" .env
fi

ensure_secret() {
  local name="$1"
  grep -q "^${name}=" .env || echo "${name}=$(openssl rand -hex 32)" >> .env
}
set_value() {
  local name="$1" value="$2"
  grep -q "^${name}=" .env \
    && sed -i "s|^${name}=.*|${name}=${value}|" .env \
    || echo "${name}=${value}" >> .env
}
ensure_secret SESSION_SECRET
ensure_secret WALLET_SECRET
grade_key="$(sed -n 's/^GRADE_ENCRYPTION_KEY=//p' .env)"
if [[ ! "$grade_key" =~ ^[0-9a-fA-F]{64}$ || "$grade_key" == "${grade_key//?/0}" ]]; then
  set_value GRADE_ENCRYPTION_KEY "$(openssl rand -hex 32)"
fi
for name in CLASS_TIMEZONE RPC_URL TEACHER_ADDRESS TEACHER_PRIVATE_KEY \
  STUDENT1_ADDRESS STUDENT1_PRIVATE_KEY STUDENT2_ADDRESS STUDENT2_PRIVATE_KEY; do
  grep -q "^${name}=" .env || grep "^${name}=" .env.example >> .env
done
set_value ENVIRONMENT production
set_value COOKIE_SECURE true
set_value TRUST_PROXY true
set_value WEB_BIND 127.0.0.1
set_value WEB_PORT 8000
set_value COMPOSE_PROFILES azure
set_value PUBLIC_HOST "$PUBLIC_HOST"
chmod 600 .env

make up
for _ in $(seq 1 24); do
  curl -fsS "https://$PUBLIC_HOST/health" >/dev/null && break
  sleep 5
done
curl -fsS "https://$PUBLIC_HOST/health" >/dev/null
make deploy
make seed
BASE="https://$PUBLIC_HOST" make smoke
REMOTE

umask 077
ssh "$ADMIN@$ip" "cd ~/classledger && grep -E '^(TEACHER|STUDENT1|STUDENT2)_PASSWORD=' .env" \
  > scripts/azure/.demo_credentials
chmod 600 scripts/azure/.demo_credentials
echo "Deployed — open https://$host/"
echo "Demo credentials saved locally in scripts/azure/.demo_credentials (git-ignored)."
