#!/usr/bin/env bash
# Copy the repo to the VM and start the stack on port 80.
set -euo pipefail
cd "$(dirname "$0")/../.."
source scripts/azure/config.sh
ip="$(cat scripts/azure/.vm_ip)"

# Push code only — never local secrets, keys, or chain data.
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '.env' --exclude '.github/skills' \
  --exclude 'data' \
  --exclude 'network/data' --exclude 'network/networkFiles' \
  ./ "$ADMIN@$ip:~/classledger/"

ssh "$ADMIN@$ip" 'bash -s' <<'REMOTE'
set -euo pipefail
sudo cloud-init status --wait
cd ~/classledger
if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s/^SESSION_SECRET=.*/SESSION_SECRET=$(openssl rand -hex 32)/" .env
  sed -i "s/^TEACHER_PASSWORD=.*/TEACHER_PASSWORD=$(openssl rand -hex 8)/" .env
  sed -i "s/^STUDENT1_PASSWORD=.*/STUDENT1_PASSWORD=$(openssl rand -hex 8)/" .env
  sed -i "s/^STUDENT2_PASSWORD=.*/STUDENT2_PASSWORD=$(openssl rand -hex 8)/" .env
fi
grep -q '^WEB_PORT=' .env && sed -i 's/^WEB_PORT=.*/WEB_PORT=80/' .env || echo 'WEB_PORT=80' >> .env
make up
curl -fsS http://localhost/health >/dev/null
make deploy
make seed
REMOTE

ssh "$ADMIN@$ip" "cd ~/classledger && grep -E '^(TEACHER|STUDENT1|STUDENT2)_PASSWORD=' .env" \
  | tee scripts/azure/.demo_credentials
chmod 600 scripts/azure/.demo_credentials
echo "Deployed — open http://$ip/"
echo "Demo credentials saved locally in scripts/azure/.demo_credentials (git-ignored)."
