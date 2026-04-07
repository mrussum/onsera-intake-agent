# Onsera Health — Developer Makefile
#
# Targets:
#   make dev          — start local development stack (hot-reload)
#   make prod         — start production stack (nginx + TLS)
#   make down         — stop all running containers
#   make test         — run all unit tests (no API keys needed)
#   make test-int     — run integration tests (requires .env with API keys)
#   make lint         — lint Python code with ruff
#   make build        — build both Docker images (dev)
#   make build-prod   — build production Docker images
#   make k8s-apply    — apply Kubernetes manifests (dry-run by default)
#   make k8s-deploy   — apply Kubernetes manifests for real
#   make logs         — tail logs from all running containers
#   make db-shell     — open SQLite shell on the running DB
#   make clean        — remove build artefacts and __pycache__

.PHONY: dev prod down test test-int lint build build-prod \
        k8s-apply k8s-deploy logs db-shell clean help

# ── Colours ──────────────────────────────────────────────────────────────────
CYAN  := \033[0;36m
RESET := \033[0m

# ── Development ───────────────────────────────────────────────────────────────

dev:
	@echo "$(CYAN)Starting development stack…$(RESET)"
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	@echo "$(CYAN)Running unit tests (no API keys needed)…$(RESET)"
	cd backend && python3 -m pytest tests/ -v

test-int:
	@echo "$(CYAN)Running integration tests (requires .env with API keys)…$(RESET)"
	python3 test_pipeline.py

lint:
	@echo "$(CYAN)Linting Python code…$(RESET)"
	ruff check backend/ test_pipeline.py --config pyproject.toml

# ── Docker builds ─────────────────────────────────────────────────────────────

build:
	docker compose build

build-prod:
	@echo "$(CYAN)Building production images…$(RESET)"
	docker compose -f deploy/docker-compose.prod.yml build

# ── Production stack ─────────────────────────────────────────────────────────

prod:
	@echo "$(CYAN)Starting production stack…$(RESET)"
	@echo "  Make sure TLS certs are at deploy/nginx/certs/"
	docker compose -f deploy/docker-compose.prod.yml up -d
	@echo "$(CYAN)Stack started. View logs: make logs-prod$(RESET)"

prod-down:
	docker compose -f deploy/docker-compose.prod.yml down

logs-prod:
	docker compose -f deploy/docker-compose.prod.yml logs -f

# ── Kubernetes ────────────────────────────────────────────────────────────────

k8s-apply:
	@echo "$(CYAN)Dry-run — no changes applied. Use 'make k8s-deploy' to apply for real.$(RESET)"
	kubectl apply -k deploy/k8s/ --dry-run=client

k8s-deploy:
	@echo "$(CYAN)Applying Kubernetes manifests…$(RESET)"
	@echo "  Note: apply deploy/k8s/secret.yaml separately (not in kustomization)"
	kubectl apply -k deploy/k8s/

k8s-status:
	kubectl get all -n onsera

k8s-logs-backend:
	kubectl logs -n onsera -l app=onsera-backend -f

# ── Utilities ─────────────────────────────────────────────────────────────────

db-shell:
	@echo "$(CYAN)Opening SQLite shell on running backend container…$(RESET)"
	docker compose exec backend sqlite3 /tmp/onsera_intake.db

clean:
	@echo "$(CYAN)Cleaning build artefacts…$(RESET)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist backend/.pytest_cache

help:
	@echo ""
	@echo "$(CYAN)Onsera Health — Available make targets:$(RESET)"
	@echo ""
	@echo "  Development:"
	@echo "    make dev          Start dev stack with hot-reload"
	@echo "    make down         Stop dev stack"
	@echo "    make logs         Tail dev stack logs"
	@echo ""
	@echo "  Testing:"
	@echo "    make test         Unit tests (no API keys needed)"
	@echo "    make test-int     Integration tests (needs .env)"
	@echo "    make lint         Ruff linter"
	@echo ""
	@echo "  Production:"
	@echo "    make prod         Start production stack (Docker)"
	@echo "    make build-prod   Build production Docker images"
	@echo ""
	@echo "  Kubernetes:"
	@echo "    make k8s-apply    Dry-run manifest apply"
	@echo "    make k8s-deploy   Apply manifests for real"
	@echo "    make k8s-status   Show pod/service status"
	@echo ""
	@echo "  Utilities:"
	@echo "    make db-shell     SQLite shell on running container"
	@echo "    make clean        Remove build artefacts"
	@echo ""
