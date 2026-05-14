# PentAGI - Makefile
# Unified command interface for development, testing, and deployment

.PHONY: help backend frontend docker test lint clean install dev dev-backend dev-frontend \
        test-backend test-frontend generate swagger docker-up docker-up-all docker-build \
        docker-down pre-commit env-check ci-check

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Backend ──────────────────────────────────────────────

install: ## Install all dependencies (backend + frontend)
	@echo "⏳ Installing backend dependencies..."
	cd backend && go mod download
	@echo "⏳ Installing frontend dependencies..."
	cd frontend && npm ci
	@echo "✅ All dependencies installed"

backend: ## Build backend binary
	cd backend && go build -trimpath -o pentagi ./cmd/pentagi

backend-linux: ## Build backend binary for Linux (Docker)
	cd backend && GOOS=linux GOARCH=amd64 go build -trimpath -o pentagi ./cmd/pentagi

dev-backend: ## Run backend in dev mode with live reload
	cd backend && go run ./cmd/pentagi

test-backend: ## Run all backend tests
	cd backend && go test ./... -v -count=1

test-backend-short: ## Run backend tests (short mode, skip integration)
	cd backend && go test ./... -short -count=1

test-backend-race: ## Run backend tests with race detector
	cd backend && go test ./... -race -count=1

lint-backend: ## Lint backend code
	cd backend && golangci-lint run --timeout=5m

# ─── Frontend ─────────────────────────────────────────────

frontend: ## Build frontend for production
	cd frontend && npm run build

dev-frontend: ## Run frontend dev server (http://localhost:8000)
	cd frontend && npm run dev

test-frontend: ## Run frontend tests
	cd frontend && npm run test

test-frontend-coverage: ## Run frontend tests with coverage
	cd frontend && npm run test:coverage

lint-frontend: ## Lint frontend code
	cd frontend && npm run lint

lint-frontend-fix: ## Auto-fix frontend lint issues
	cd frontend && npm run lint:fix

format-frontend: ## Format frontend code
	cd frontend && npm run prettier

format-frontend-fix: ## Auto-format frontend code
	cd frontend && npm run prettier:fix

# ─── Docker ───────────────────────────────────────────────

docker-up: ## Start core services (DB + app)
	docker compose up -d

docker-up-all: ## Start all services (core + monitoring)
	docker compose -f docker-compose.yml -f docker-compose-observability.yml up -d

docker-up-langfuse: ## Start core + Langfuse LLM analytics
	docker compose -f docker-compose.yml -f docker-compose-langfuse.yml up -d

docker-up-graphiti: ## Start core + knowledge graph
	docker compose -f docker-compose.yml -f docker-compose-graphiti.yml up -d

docker-build: ## Build Docker image
	docker build -t local/pentagi:latest .

docker-down: ## Stop all Docker services
	docker compose down

docker-down-all: ## Stop all Docker services (including volumes)
	docker compose down -v

docker-logs: ## Follow Docker logs
	docker compose logs -f

# ─── Code Generation ──────────────────────────────────────

generate-graphql: ## Regenerate GraphQL resolvers (after schema changes)
	cd backend && go run github.com/99designs/gqlgen --config ./gqlgen/gqlgen.yml

generate-swagger: ## Regenerate Swagger docs
	cd backend && swag init -g ../../pkg/server/router.go -o pkg/server/docs/ \
		--parseDependency --parseInternal --parseDepth 2 -d cmd/pentagi

generate-frontend-types: ## Regenerate frontend GraphQL types
	cd frontend && npm run graphql:generate

generate: generate-graphql generate-swagger generate-frontend-types ## Regenerate all code

# ─── Testing ──────────────────────────────────────────────

test: test-backend test-frontend ## Run all tests

lint: lint-backend lint-frontend ## Run all linters

ci-check: lint test ## Run all CI checks (lint + test)

# ─── Developer Tools ──────────────────────────────────────

dev: dev-backend ## Start backend dev server

dev-full: ## Start both backend and frontend dev servers
	@echo "Starting backend dev server..." && cd backend && go run ./cmd/pentagi & \
	echo "Starting frontend dev server..." && cd frontend && npm run dev

# ─── Security & Environment ───────────────────────────────

env-check: ## Validate .env file has required variables
	@echo "⏳ Checking environment configuration..."
	@if [ ! -f .env ]; then \
		echo "❌ .env file not found! Copy .env.example to .env first."; \
		exit 1; \
	fi
	@for key in DATABASE_URL; do \
		if ! grep -q "^$$key=" .env 2>/dev/null; then \
			echo "❌ Missing required env: $$key"; \
			exit 1; \
		fi; \
	done
	@echo "✅ Environment check passed"

env-template: ## Generate fresh .env.example from current .env (without secrets)
	@if [ -f .env ]; then \
		sed 's/=.*/=/' .env > .env.example; \
		echo "✅ Generated .env.example from .env"; \
	else \
		echo "❌ No .env file found"; \
		exit 1; \
	fi

pre-commit: ## Run pre-commit checks (lint + short tests)
	@echo "⏳ Running pre-commit checks..."
	@$(MAKE) lint-backend
	@$(MAKE) test-backend-short
	@echo "✅ Pre-commit checks passed"

pre-commit-install: ## Install git pre-commit hook
	@echo '#!/bin/sh' > .git/hooks/pre-commit
	@echo 'make pre-commit 2>&1 | head -50' >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✅ Pre-commit hook installed at .git/hooks/pre-commit"

# ─── Quick Start ─────────────────────────────────────────

quickstart: ## One-command setup for new users: check deps, create .env, launch
	@echo "⏳ 1/4 Checking prerequisites..."
	@command -v docker >/dev/null 2>&1 || { echo "❌ docker is required. Install from https://docs.docker.com/get-docker/"; exit 1; }
	@command -v docker compose >/dev/null 2>&1 || { echo "❌ docker compose is required."; exit 1; }
	@echo "✅ docker + docker compose found"
	@echo "⏳ 2/4 Checking .env..."
	@if [ ! -f .env ]; then \
		echo "⚠️  No .env found. Creating .env from template..."; \
		cp .env.example .env 2>/dev/null || true; \
		echo "" >> .env; \
		echo "# === LLM Configuration ====" >> .env; \
		echo "# Set ONE of the following:" >> .env; \
		echo "# OPEN_AI_KEY=sk-your-key" >> .env; \
		echo "# ANTHROPIC_API_KEY=sk-ant-your-key" >> .env; \
		echo "✅ .env created. Edit it to set your LLM API key before continuing."; \
		echo ""; \
		echo "Edit .env now, then re-run: make quickstart"; \
		exit 0; \
	fi
	@echo "✅ .env found"
	@echo "⏳ 3/4 Checking LLM config..."
	@grep -q "OPEN_AI_KEY\|ANTHROPIC_API_KEY\|GEMINI_API_KEY\|DEEPSEEK_API_KEY\|OLLAMA_SERVER_URL" .env 2>/dev/null || { \
		echo "⚠️  No LLM API key found in .env"; \
		echo "   Add one of: OPEN_AI_KEY, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY"; \
		echo "   Or set OLLAMA_SERVER_URL for local models"; \
		exit 0; \
	}
	@echo "✅ LLM configured"
	@echo "⏳ 4/4 Starting PentAGI..."
	@docker compose up -d
	@echo "✅ PentAGI is running at http://localhost:8080"

clean-backend: ## Clean backend build artifacts
	cd backend && rm -f pentagi

clean-frontend: ## Clean frontend build artifacts
	cd frontend && rm -rf dist

clean: clean-backend clean-frontend ## Clean all build artifacts
