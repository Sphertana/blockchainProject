COMPOSE = docker compose --env-file .env -f network/docker-compose.yml

.PHONY: help genkeys up down deploy seed demo smoke compliance test verify compile logs ps clean

help:
	@echo "make genkeys    - générer les clés QBFT et le genesis"
	@echo "make up         - démarrer les 4 validateurs et l'application"
	@echo "make deploy     - déployer ou réutiliser le contrat ClassLedger"
	@echo "make seed       - inscrire les comptes démo et ajouter un cours"
	@echo "make demo       - lancer toute la démonstration locale"
	@echo "make smoke      - exécuter le parcours E2E"
	@echo "make compliance - tester la réplication P2P et le quorum QBFT"
	@echo "make test       - exécuter les tests contrat et sécurité"
	@echo "make verify     - exécuter toutes les suites de tests"
	@echo "make compile    - recompiler le contrat Solidity"
	@echo "make logs       - suivre les journaux des conteneurs"
	@echo "make down       - arrêter le réseau sans supprimer les données"
	@echo "make clean      - supprimer la chaîne et les clés générées"

genkeys:
	./scripts/network/generate.sh

up:
	@test -f .env || cp .env.example .env
	@test -f network/data/genesis.json || ./scripts/network/generate.sh
	$(COMPOSE) up -d --build --wait --wait-timeout 180

down:
	$(COMPOSE) down

deploy:
	$(COMPOSE) exec -T --interactive=false api python -m app.deploy

seed:
	$(COMPOSE) exec -T --interactive=false api python -m app.seed

demo: up deploy seed

smoke:
	./scripts/smoke.sh

compliance:
	./scripts/compliance.sh

verify: test smoke compliance

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
