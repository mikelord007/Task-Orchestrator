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

## Full evidence pipeline: preflight -> domain-a -> domain-b -> summary
## (scripts/demo_run.py). Needs the backend already running in another
## terminal (`make backend`) and a populated .env (LLM + GitHub creds, see
## .env.example). Idempotent: pass DOMAIN_A_AGENT_ID=<id> and/or
## DOMAIN_B_AGENT_ID=<id> to reuse the corresponding domain's agent.
demo:
	$(BACKEND) python scripts/demo_run.py demo \
		$(if $(DOMAIN_A_AGENT_ID),--domain-a-agent-id $(DOMAIN_A_AGENT_ID),) \
		$(if $(DOMAIN_B_AGENT_ID),--domain-b-agent-id $(DOMAIN_B_AGENT_ID),)
