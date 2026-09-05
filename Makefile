.PHONY: dev backend frontend test lint fmt seed demo install

UV ?= uv
BACKEND := $(UV) run --project backend

install:
	$(UV) sync --project backend
	cd frontend && npm ci   # frontend/ is owned by W5

## Both servers: backend on :8000, frontend on :3000.
dev:
	$(BACKEND) python -m uvicorn backend.app:app --reload --port 8000 & \
	cd frontend && npm run dev

backend:
	$(BACKEND) python -m uvicorn backend.app:app --reload --port 8000

frontend:
	cd frontend && npm run dev

## cd backend so pytest's testpaths (tests, ../evaluators, ../scripts) resolve.
test:
	cd backend && $(UV) run python -m pytest

lint:
	$(BACKEND) ruff check backend contracts scripts evaluators agents
	$(BACKEND) ruff format --check backend contracts scripts evaluators agents

fmt:
	$(BACKEND) ruff check --fix backend contracts scripts evaluators agents
	$(BACKEND) ruff format backend contracts scripts evaluators agents

## Placeholder: W4 seeds the evaluators, W3 generates a v0 agent.
seed:
	@echo "seed: not implemented yet (W3 architect + W4 evaluators)"

## Placeholder: W12 wires the demo script (PLAN.md 0.6).
demo:
	@echo "demo: not implemented yet (W12) -- see DEMO.md"
