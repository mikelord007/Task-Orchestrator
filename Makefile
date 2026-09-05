.PHONY: dev backend frontend test lint fmt seed demo install

UV ?= uv
BACKEND := $(UV) run --project backend

install:
	$(UV) sync --project backend
	cd frontend && npm ci

## Both servers: backend on :8000, frontend on :3000.
dev:
	$(BACKEND) python -m uvicorn backend.app:app --reload --port 8000 & \
	cd frontend && npm run dev

backend:
	$(BACKEND) python -m uvicorn backend.app:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	$(BACKEND) python -m pytest backend/tests

lint:
	$(BACKEND) ruff check backend contracts scripts
	$(BACKEND) ruff format --check backend contracts scripts
	cd frontend && npx tsc --noEmit

fmt:
	$(BACKEND) ruff check --fix backend contracts scripts
	$(BACKEND) ruff format backend contracts scripts

## Placeholder: W4 seeds the evaluators, W3 generates a v0 agent.
seed:
	@echo "seed: not implemented yet (W3 architect + W4 evaluators)"

## Placeholder: W12 wires the demo script (PLAN.md 0.6).
demo:
	@echo "demo: not implemented yet (W12) -- see DEMO.md"
