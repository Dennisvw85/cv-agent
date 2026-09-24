"""Zet de kennisbank en de prompt agent neer in het Foundry-project.

Agents en vector stores zijn geen Azure-resources maar data in het project, dus
Bicep kan ze niet aanmaken. Dit script doet dat, idempotent: elke run maakt een
nieuwe versie van de agent en een verse vector store, en ruimt de oude op.

Draait automatisch als azd-hook na `azd provision`, of los:
    uv run --env-file .azure/dev/.env scripts/deploy_agent.py
"""

import os
import pathlib
import tempfile
import urllib.request

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FileSearchTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_NAME = os.environ.get("AGENT_NAME", "cv-agent")
VECTOR_STORE_NAME = f"{AGENT_NAME}-kennis"

endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
model = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
openai = project.get_openai_client()


def download_sources() -> list[pathlib.Path]:
    """Haalt de publieke README's op die in knowledge/sources.txt staan."""
    urls = [
        line.strip()
        for line in (ROOT / "knowledge" / "sources.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    folder = pathlib.Path(tempfile.mkdtemp())
    files = []
    for url in urls:
        # Bestandsnaam = repo-naam, zodat de agent kan zeggen uit welke repo iets komt.
        repo = url.split("/")[4]
        target = folder / f"{repo}.md"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                target.write_bytes(response.read())
            files.append(target)
            print(f"  bron: {repo}")
        except OSError as error:
            print(f"  overgeslagen: {url} ({error})")
    return files


def rebuild_vector_store(files: list[pathlib.Path]) -> str:
    """Nieuwe vector store met de bronnen; oude met dezelfde naam gaan weg."""
    old = [vs.id for vs in openai.vector_stores.list() if vs.name == VECTOR_STORE_NAME]
    store = openai.vector_stores.create(name=VECTOR_STORE_NAME)
    for path in files:
        with path.open("rb") as handle:
            openai.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=handle)
    for store_id in old:
        openai.vector_stores.delete(store_id)
    print(f"  vector store {store.id}: {len(files)} bestanden, {len(old)} oude opgeruimd")
    return store.id


def main() -> None:
    print(f"Kennisbank opbouwen voor {AGENT_NAME}")
    store_id = rebuild_vector_store(download_sources())

    cv = (ROOT / "knowledge" / "cv.md").read_text()
    instructions = (ROOT / "agent" / "instructions.md").read_text().replace("{cv}", cv)

    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=model,
            instructions=instructions,
            temperature=0.3,
            tools=[FileSearchTool(vector_store_ids=[store_id], max_num_results=4)],
        ),
        description="Beantwoordt vragen over het CV en de publieke repo's van Dennis van Waas.",
    )
    print(f"Agent {agent.name} versie {agent.version} staat klaar op model {model}")


if __name__ == "__main__":
    main()
