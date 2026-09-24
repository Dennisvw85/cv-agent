"""HTTP-API tussen de CV-site en de Foundry-agent.

De site roept POST /api/chat aan. Static Web Apps stuurt dat door naar deze
Function App (linked backend), die met zijn managed identity inlogt bij Foundry.
De bezoeker krijgt dus nooit een token of key te zien.
"""

import json
import logging
import os

import azure.functions as func
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

MAX_MESSAGE_LENGTH = 500
AGENT_REFERENCE = {"agent_reference": {"name": os.environ.get("AGENT_NAME", "cv-agent"), "type": "agent_reference"}}

# Anoniem op Functions-niveau: de linked backend zorgt dat alleen de site ons kan bereiken.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_openai = None


def openai_client():
    """Eén client per instance; DefaultAzureCredential pakt de managed identity via AZURE_CLIENT_ID."""
    global _openai
    if _openai is None:
        project = AIProjectClient(
            endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
            credential=DefaultAzureCredential(),
        )
        _openai = project.get_openai_client()
    return _openai


def reply(status: int, body: dict) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body), status_code=status, mimetype="application/json")


@app.route(route="chat", methods=["POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except ValueError:
        return reply(400, {"error": "Verwacht JSON."})

    message = str(data.get("message", "")).strip()
    if not message:
        return reply(400, {"error": "Stel een vraag."})
    if len(message) > MAX_MESSAGE_LENGTH:
        return reply(400, {"error": f"Houd je vraag korter dan {MAX_MESSAGE_LENGTH} tekens."})

    request = {"input": message, "max_output_tokens": 500, "extra_body": AGENT_REFERENCE}
    previous = data.get("previous_response_id")
    if isinstance(previous, str) and previous.startswith("resp_") and len(previous) < 100:
        request["previous_response_id"] = previous

    try:
        response = openai_client().responses.create(**request)
    except Exception as error:  # noqa: BLE001 - de bezoeker krijgt een nette melding, de details gaan naar App Insights
        logging.exception("Agent-aanroep mislukt: %s", error)
        status = 429 if "429" in str(error) else 502
        text = "Het is even druk, probeer het over een minuut opnieuw." if status == 429 else "De assistent is even niet bereikbaar."
        return reply(status, {"error": text})

    return reply(200, {"answer": response.output_text, "response_id": response.id})
