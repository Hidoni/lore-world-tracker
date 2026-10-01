# Single entry point for humans and agents. Targets are documented in CLAUDE.md ("Commands") and
# docs/architecture/deployment.md §4. `make help` lists them.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

BACKEND := backend
DATA_DIR := $(CURDIR)/data
UV := uv --directory $(BACKEND)

# Prints a "not available yet" message for targets whose tooling arrives with a later issue.
define placeholder
	@echo "make $@: not available yet (arrives with $(1): https://github.com/Hidoni/lore-world-tracker/issues/$(patsubst #%,%,$(1)))"
endef

.PHONY: help setup dev check check-backend check-frontend test test-backend test-frontend \
	test-chronology e2e gen fmt docker sample-vault

help: ## List the targets
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-zA-Z0-9_-]*:.*## / { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup: ## Install backend (uv) and frontend (npm workspaces) deps and Playwright's Chromium
	$(UV) sync
	npm ci
	npx -w frontend playwright install chromium

dev: ## Backend on :8000 (reload) + Vite on :5173 (proxies /api); data in ./data; Ctrl-C stops both
	@mkdir -p $(DATA_DIR)
	@trap 'kill $$backend $$frontend 2>/dev/null || true; wait' INT TERM EXIT; \
	LORE_DATA_DIR=$(DATA_DIR) $(UV) run lore serve --reload & backend=$$!; \
	npm run dev -w frontend & frontend=$$!; \
	while kill -0 $$backend 2>/dev/null && kill -0 $$frontend 2>/dev/null; do sleep 1; done

check: check-backend check-frontend ## Everything CI runs except e2e/docker: lint, format, types, imports, tests, build

check-backend: ## Backend: ruff check, ruff format --check, mypy, lint-imports, pytest
	$(UV) run ruff check
	$(UV) run ruff format --check
	$(UV) run mypy
	$(UV) run lint-imports
	$(UV) run pytest

check-frontend: ## Frontend workspaces: eslint + prettier --check, tsc, vitest, build
	npm run lint
	npm run typecheck
	npm run test
	npm run build

test: test-backend test-frontend test-chronology ## All unit tests (backend, frontend, chronology conformance)

test-backend: ## pytest
	$(UV) run pytest

test-frontend: ## vitest in every npm workspace
	npm run test

test-chronology: ## Conformance vectors against both chronology engines
	$(call placeholder,#8)

e2e: ## Build the SPA, serve it from the backend on a temp data dir, run Playwright
	$(call placeholder,#6)

gen: ## Regenerate OpenAPI TS types and chronology JSON Schemas/TS types
	$(call placeholder,#4)

fmt: ## ruff format + prettier
	$(UV) run ruff format
	npm run fmt

docker: ## Build the image
	$(call placeholder,#7)

sample-vault: ## Generate the demo world into ./data (SIZE=small|medium|large)
	$(call placeholder,#43)
