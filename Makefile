.PHONY: all setup run lint build clean deps bump-patch bump-minor bump-major

APP_NAME := StreamManager

all: setup

setup:
	uv sync --all-groups
	@[ -f .env ] || (cp .env.example .env && echo "Created .env -- fill in your credentials before running")
	uv run pre-commit install
	@echo "Setup complete. Run 'make run' to start the app."

run:
	uv run python -m streammanager.main

lint:
	uv run ruff format .
	uv run ruff check --fix .
	uv run mypy src/

build:
	uv run pyinstaller StreamManager.spec
	@echo "Built: dist/$(APP_NAME).app"

deps:
	bash scripts/install-deps.sh

bump-patch:
	@bash scripts/bump-version.sh patch

bump-minor:
	@bash scripts/bump-version.sh minor

bump-major:
	@bash scripts/bump-version.sh major

clean:
	rm -rf dist/ build/ .venv/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +
