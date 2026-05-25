.PHONY: ci dev fmt install

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install: $(VENV)/bin/python
	$(PIP) install -e ../shared
	$(PIP) install -e ".[dev]"

$(VENV)/bin/python:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

ci: install
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/pytest -q

dev: install
	$(VENV)/bin/uvicorn dispatcher.app:create_app --factory --host 127.0.0.1 --port 8765 --reload

fmt: install
	$(VENV)/bin/ruff format src tests
	$(VENV)/bin/ruff check --fix src tests
