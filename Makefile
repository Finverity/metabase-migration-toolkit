.PHONY: help install install-dev clean test test-cov lint format type-check security pre-commit build publish-test publish docs

# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := python3
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
BLACK := $(PYTHON) -m black
RUFF := $(PYTHON) -m ruff
MYPY := $(PYTHON) -m mypy
BANDIT := $(PYTHON) -m bandit
SAFETY := $(PYTHON) -m safety

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install package in production mode
	$(PIP) install --upgrade pip
	$(PIP) install -e .

install-dev: ## Install package with development dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	pre-commit install

clean: ## Clean up build artifacts and cache files
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

test: ## Run tests
	$(PYTEST) -v

test-cov: ## Run tests with coverage report
	$(PYTEST) -v --cov=lib --cov-report=html --cov-report=term-missing --cov-report=xml
	@echo ""
	@echo "Coverage report generated in htmlcov/index.html"

test-fast: ## Run tests without slow tests
	$(PYTEST) -v -m "not slow"

test-unit: ## Run unit tests only (exclude integration tests)
	$(PYTEST) -v -m "not integration"

test-integration: ## Run integration tests with Docker Compose
	@echo "Starting integration tests with Docker Compose..."
	@bash scripts/run_integration_tests.sh

test-integration-only: ## Run integration tests (assumes Docker services are already running)
	$(PYTEST) tests/integration/test_e2e_export_import.py -v -s -m integration

docker-up: ## Start Docker Compose services for integration tests
	docker-compose -f docker-compose.test.yml up -d
	@echo "Waiting for services to be ready (this may take 2-3 minutes)..."
	@sleep 30
	@echo "Services started. Check status with: make docker-status"

docker-down: ## Stop Docker Compose services
	docker-compose -f docker-compose.test.yml down -v

docker-status: ## Show status of Docker Compose services
	docker-compose -f docker-compose.test.yml ps

docker-logs: ## Show logs from Docker Compose services
	docker-compose -f docker-compose.test.yml logs -f

docker-clean: ## Clean up Docker volumes and containers
	docker-compose -f docker-compose.test.yml down -v
	docker volume prune -f

# =============================================================================
# E2E Demo targets (v57)
# =============================================================================

demo-up: ## Start v57 Docker services for E2E demo
	docker compose -f docker-compose.test.v57.yml up -d
	@echo "Waiting for Metabase services to be ready (this may take 2-3 minutes)..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24; do \
		if curl -sf http://localhost:3002/api/health > /dev/null 2>&1 && \
		   curl -sf http://localhost:3003/api/health > /dev/null 2>&1; then \
			echo "✓ Both Metabase instances are healthy!"; \
			break; \
		fi; \
		echo "  Waiting... ($$i/24)"; \
		sleep 5; \
	done
	@echo ""
	@echo "Services started:"
	@echo "  Source Metabase: http://localhost:3002"
	@echo "  Target Metabase: http://localhost:3003"

demo-down: ## Stop v57 Docker services
	docker compose -f docker-compose.test.v57.yml down -v

demo-status: ## Show status of v57 Docker services
	docker compose -f docker-compose.test.v57.yml ps

demo-logs: ## Show logs from v57 Docker services
	docker compose -f docker-compose.test.v57.yml logs -f

demo-setup: demo-up ## Start v57 services and setup test data
	@echo ""
	@echo "Setting up test data..."
	$(PYTHON) scripts/setup_e2e_demo.py

demo-export: ## Export from source Metabase (v57)
	@echo "Exporting from source Metabase..."
	$(PYTHON) export_metabase.py \
		--source-url http://localhost:3002 \
		--source-username admin@example.com \
		--source-password 'Admin123!' \
		--export-dir e2e_export \
		--include-dashboards \
		--metabase-version v57 \
		--log-level INFO

demo-import: ## Import to target Metabase (v57)
	@echo "Importing to target Metabase..."
	$(PYTHON) import_metabase.py \
		--target-url http://localhost:3003 \
		--target-username admin@example.com \
		--target-password 'Admin123!' \
		--export-dir e2e_export \
		--db-map e2e_export/db_map.json \
		--metabase-version v57 \
		--log-level INFO

demo-migrate: demo-export demo-import ## Run full export then import (v57)
	@echo ""
	@echo "✅ Migration complete!"
	@echo ""
	@echo "View results:"
	@echo "  Source: http://localhost:3002"
	@echo "  Target: http://localhost:3003"
	@echo "  Credentials: admin@example.com / Admin123!"

demo-verify: ## Verify migration results (model reference remapping)
	@echo "Verifying migration results..."
	$(PYTHON) scripts/verify_e2e_demo.py

demo: demo-setup demo-migrate demo-verify ## Full E2E demo: start services, setup data, run migration, verify
	@echo ""
	@echo "============================================================"
	@echo "E2E DEMO COMPLETE!"
	@echo "============================================================"
	@echo ""
	@echo "Source Metabase: http://localhost:3002"
	@echo "Target Metabase: http://localhost:3003"
	@echo "Credentials: admin@example.com / Admin123!"
	@echo ""
	@echo "Key items to verify:"
	@echo "  - Collections migrated with hierarchy"
	@echo "  - Cards/Questions with correct field mappings"
	@echo "  - Models migrated"
	@echo "  - SQL cards referencing models (ID remapping)"
	@echo "  - Dashboards with filters"
	@echo ""
	@echo "Containers are still running. Stop with: make demo-down"

lint: ## Run all linters
	@echo "Running ruff..."
	$(RUFF) check lib/ tests/ scripts/ *.py --fix
	@echo ""
	@echo "Running black check..."
	$(BLACK) --check --diff lib/ tests/ *.py
	@echo ""
	@echo "All linting checks passed!"

format: ## Format code with black and ruff
	@echo "Running mypy type checker..."
	$(BLACK) lib/ tests/ *.py
	@echo ""
	@echo "Sorting imports with ruff..."
	$(RUFF) check --select I --fix lib/ tests/ *.py

format-check: ## Check code formatting without making changes
	$(BLACK) --check lib/ tests/ *.py
	$(PYTHON) -m isort --check-only lib/ tests/ *.py

type-check: ## Run type checking with mypy
	@echo "Running mypy type checker..."
	$(MYPY) lib/ --ignore-missing-imports
	@echo ""
	@echo "Type checking complete!"

security: ## Run security checks
	@echo "Running bandit security scan..."
	$(BANDIT) -r lib/ -f screen
	@echo ""
	@echo "Checking dependencies for vulnerabilities..."
	$(SAFETY) check || true
	@echo ""
	@echo "Security checks complete!"

pre-commit: ## Run pre-commit hooks on all files
	pre-commit run --all-files

pre-commit-update: ## Update pre-commit hooks
	pre-commit autoupdate

quality: lint type-check security ## Run all quality checks

build: clean ## Build distribution packages
	$(PYTHON) -m build
	@echo ""
	@echo "Build complete! Packages in dist/"

build-check: build ## Build and check package with twine
	$(PYTHON) -m twine check dist/*

publish-test: build-check ## Publish to TestPyPI
	@echo "Publishing to TestPyPI..."
	$(PYTHON) -m twine upload --repository testpypi dist/*
	@echo ""
	@echo "Published to TestPyPI!"
	@echo "Install with: pip install --index-url https://test.pypi.org/simple/ metabase-migration-toolkit"

publish: build-check ## Publish to PyPI (use with caution!)
	@echo "⚠️  WARNING: This will publish to PyPI!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(PYTHON) -m twine upload dist/*; \
		echo ""; \
		echo "Published to PyPI!"; \
	else \
		echo "Cancelled."; \
	fi

docs: ## Generate documentation (placeholder)
	@echo "Documentation generation not yet implemented"
	@echo "Consider using Sphinx or MkDocs"

version: ## Show current version
	@$(PYTHON) -c "from lib import __version__; print(f'Version: {__version__}')"

check-deps: ## Check for outdated dependencies
	$(PIP) list --outdated

update-deps: ## Update all dependencies (use with caution!)
	$(PIP) install --upgrade pip
	$(PIP) list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1 | xargs -n1 $(PIP) install -U

dev-setup: install-dev ## Complete development environment setup
	@echo ""
	@echo "✅ Development environment setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Copy .env.example to .env and configure"
	@echo "  2. Run 'make test' to verify setup"
	@echo "  3. Run 'make pre-commit' to check code quality"

ci: lint type-check test-cov ## Run all CI checks locally
	@echo ""
	@echo "✅ All CI checks passed!"

all: clean install-dev quality test-cov build ## Run everything (clean, install, quality checks, tests, build)
	@echo ""
	@echo "✅ All tasks completed successfully!"
