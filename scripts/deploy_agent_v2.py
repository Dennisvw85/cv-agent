"""Zet een zuinigere variant van de agent neer: cv-agent-v2.

Kosten-experiment (zie README, tabel "v2-agent"): dezelfde instructies en dezelfde
kennisbank als cv-agent, maar met minder File Search-resultaten per vraag. Bouwt de
vector store NIET opnieuw op, dat blijft van cv-agent (`deploy_agent.py`): dit script
zoekt de bestaande store "cv-agent-kennis" op naam en hergebruikt hem.

Los draaien:
    uv run --env-file .azure/dev/.env scripts/deploy_agent_v2.py [--max-num-results N]
"""

import argparse
import os
import pathlib

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_NAME = os.environ.get("AGENT_NAME_V2", "cv-agent-v2")
VECTOR_STORE_NAME = "cv-agent-kennis"  # zelfde kennisbank als cv-agent, niet opnieuw opbouwen

endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
model = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
openai = project.get_openai_client()


def find_vector_store() -> str:
    matches = [vs for vs in openai.vector_stores.list() if vs.name == VECTOR_STORE_NAME]
    if not matches:
        raise SystemExit(f"Geen vector store gevonden met naam '{VECTOR_STORE_NAME}'. Draai eerst deploy_agent.py.")
    return matches[0].id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-num-results", type=int, default=2)
    args = parser.parse_args()

    print(f"Kennisbank hergebruiken voor {AGENT_NAME}")
    store_id = find_vector_store()
    print(f"  vector store: {store_id}")

    cv = (ROOT / "knowledge" / "cv.md").read_text()
    # instructions-v2.md is instructions.md + een expliciete regel om File Search over te slaan
    # bij vragen die de CV al beantwoordt (kostenexperiment, zie README).
    instructions = (ROOT / "agent" / "instructions-v2.md").read_text().replace("{cv}", cv)

    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=model,
            instructions=instructions,
            temperature=0.3,
            tools=[FileSearchTool(vector_store_ids=[store_id], max_num_results=args.max_num_results)],
        ),
        description="Zuinigere variant van cv-agent (minder File Search-resultaten per vraag).",
    )
    print(f"Agent {agent.name} versie {agent.version} staat klaar op model {model} (max_num_results={args.max_num_results})")


if __name__ == "__main__":
    main()
