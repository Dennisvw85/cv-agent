"""Zet de vacature-matcher neer: een tweede prompt agent met structured output (JSON-schema).

Los van de CV-agent, zodat een wijziging hier de chat op de site niet raakt.
    uv run --env-file .azure/dev/.env scripts/deploy_matcher.py
"""

import datetime
import os
import pathlib

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_NAME = "cv-matcher"

REQUIREMENT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirement", "status", "evidence"],
    "properties": {
        "requirement": {"type": "string"},
        "status": {"type": "string", "enum": ["met", "partial", "gap"]},
        "evidence": {"type": "string", "description": "Kort bewijs uit het CV, of waarom het ontbreekt"},
    },
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_job_description", "job_title", "score", "summary", "requirements", "interview_questions"],
    "properties": {
        "is_job_description": {"type": "boolean"},
        "job_title": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "requirements": {"type": "array", "items": REQUIREMENT},
        "interview_questions": {"type": "array", "items": {"type": "string"}},
    },
}

project = AIProjectClient(endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"], credential=DefaultAzureCredential())
cv = (ROOT / "knowledge" / "cv.md").read_text()
instructions = (
    (ROOT / "agent" / "matcher_instructions.md").read_text()
    .replace("{cv}", cv)
    .replace("{today}", datetime.date.today().isoformat())
)

# Dezelfde kennisbank als de CV-agent (README's van de repo's + LinkedIn), op naam opgezocht.
openai = project.get_openai_client()
store_id = next(vs.id for vs in openai.vector_stores.list() if vs.name == "cv-agent-kennis")

agent = project.agents.create_version(
    agent_name=AGENT_NAME,
    definition=PromptAgentDefinition(
        model="cv-match",  # eigen deployment met eigen TPM-limiet
        instructions=instructions,
        temperature=0.1,
        tools=[FileSearchTool(vector_store_ids=[store_id], max_num_results=4)],
        text={"format": {"type": "json_schema", "name": "job_match", "schema": SCHEMA, "strict": True}},
    ),
    description="Vergelijkt een vacature met het CV van Dennis van Waas en geeft een onderbouwde match.",
)
print(f"Agent {agent.name} versie {agent.version} staat klaar")
