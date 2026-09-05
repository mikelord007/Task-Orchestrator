"""Toy lookup tool: returns the stored record for a ticket id."""

import json

TOOL = {
    "name": "lookup_ticket",
    "description": (
        "Return the stored record for a ticket id as JSON. Use it once per ticket "
        "before answering. It does not classify the ticket for you."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"ticket_id": {"type": "string"}},
        "required": ["ticket_id"],
    },
}

_RECORDS = {
    "t1": {"ticket_id": "t1", "text": "invoice charged twice", "customer_tier": "pro"},
    "t2": {"ticket_id": "t2", "text": "app crashes on windows", "customer_tier": "free"},
    "t3": {"ticket_id": "t3", "text": "please add dark mode", "customer_tier": "free"},
}


def run(input: dict) -> str:
    ticket_id = str(input.get("ticket_id", ""))
    record = _RECORDS.get(ticket_id)
    if record is None:
        return json.dumps({"error": f"no such ticket: {ticket_id}"})
    return json.dumps(record)
