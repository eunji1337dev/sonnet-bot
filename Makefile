.PHONY: run test lint check format help

# Default target
help:
	@echo "Sonnet Bot Development Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make run      - Run the bot in development mode"
	@echo "  make test     - Run pytest with coverage"
	@echo "  make lint     - Run ruff static analysis"
	@echo "  make check    - Run mypy strict type checking"
	@echo "  make format   - Run ruff auto-formatter"
	@echo "  make scan     - Run security scanners (bandit, semgrep)"
	@echo "  make audit    - Run all checks (lint, check, test, scan)"

run:
	python3 main.py

test:
	python3 -m pytest tests/ -v --cov=core --cov=handlers --cov=modules --cov-report=term-missing

lint:
	python3 -m ruff check .

check:
	python3 -m mypy .

format:
	python3 -m ruff check --fix .
	python3 -m ruff format .

scan:
	python3 -m bandit -r . -x ./tests
	# semgrep scan --error --config auto .

audit: format lint check scan test
