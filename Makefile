COMPOSE = docker compose -f network/docker-compose.yml

.PHONY: help genkeys up down deploy seed smoke test compile logs ps clean

help:
	@echo "make genkeys  - generate QBFT keys + genesis (once)"
	@echo "make up        - start the 4-validator Besu network + web app"
	@echo "make deploy    - compile-free deploy of ClassLedger + set class info"
	@echo "make seed      - enroll demo students + add one sample lecture"
	@echo "make smoke     - end-to-end check on the running network"
	@echo "make test      - run contract rule tests (in container)"
	@echo "make compile   - recompile the Solidity artifact (needs solc)"
	@echo "make logs      - tail all container logs"
	@echo "make down      - stop the network"
	@echo "make clean     - stop and remove generated keys/chain data"

genkeys:
	./scripts/network/generate.sh

up:
	@test -f .env || cp .env.example .env
	@test -f network/data/genesis.json || ./scripts/network/generate.sh
	$(COMPOSE) up -d --build --wait --wait-timeout 180

down:
	$(COMPOSE) down

deploy:
	$(COMPOSE) exec api python -m app.deploy

seed:
	$(COMPOSE) exec api python -m app.seed

smoke:
	./scripts/smoke.sh

test:
	$(COMPOSE) run --rm --no-deps --build api python -m pytest

compile:
	python3 scripts/compile.py

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

clean:
	$(COMPOSE) down -v
	rm -rf network/data network/networkFiles
