#!/usr/bin/env bash
# Copy the repo to the VM and start the stack on port 80.
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/azure/config.sh
ip="$(cat scripts/azure/.vm_ip)"

# Push code only — never local secrets, keys, or chain data.
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude 'data' \
  --exclude 'network/data' --exclude 'network/networkFiles' \
  ./ "$ADMIN@$ip:~/classledger/"

ssh "$ADMIN@$ip" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/classledger
cp -n .env.example .env
grep -q '^WEB_PORT=' .env && sed -i 's/^WEB_PORT=.*/WEB_PORT=80/' .env || echo 'WEB_PORT=80' >> .env
make up
for i in $(seq 1 40); do curl -sf http://localhost/health >/dev/null && break; sleep 3; done
make deploy
make seed
REMOTE

echo "Deployed — open http://$ip/"
