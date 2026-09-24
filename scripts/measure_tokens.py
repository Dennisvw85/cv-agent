"""Meet gemiddeld tokengebruik per agent over 6 representatieve vragen (Responses API `usage`).

Los draaien:
    uv run --env-file .azure/dev/.env scripts/measure_tokens.py <agent-naam> [<agent-naam> ...]
"""

import os
import sys
import time

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

QUESTIONS = [
    "Waar werkt Dennis op dit moment en sinds wanneer?",
    "Welke Azure-certificeringen heeft hij?",
    "Wat heeft hij gebouwd in zijn repo foundry-landing-zone?",
    "How does his landing zone deploy from GitHub without secrets?",
    "Wat is de hoofdstad van Australië?",
    "In welke plaats woont hij?",
]

endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
openai = project.get_openai_client(max_retries=10)


def measure(agent_name: str) -> None:
    print(f"\n=== {agent_name} ===")
    totals = []
    for q in QUESTIONS:
        for attempt in range(5):
            try:
                response = openai.responses.create(
                    input=q,
                    max_output_tokens=500,
                    extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
                )
                break
            except Exception as exc:  # noqa: BLE001
                if "429" in str(exc) and attempt < 4:
                    print("  429, 65s wachten")
                    time.sleep(65)
                    continue
                raise
        usage = response.usage
        total = (usage.input_tokens or 0) + (usage.output_tokens or 0)
        totals.append(total)
        print(f"  {q[:50]:<50} in={usage.input_tokens:<6} out={usage.output_tokens:<6} totaal={total}")
        time.sleep(16)
    avg = sum(totals) / len(totals)
    print(f"  gemiddeld: {avg:.0f} tokens over {len(totals)} vragen")
    return avg


if __name__ == "__main__":
    agents = sys.argv[1:] or ["cv-agent"]
    results = {}
    for name in agents:
        results[name] = measure(name)
    print("\n=== samenvatting ===")
    for name, avg in results.items():
        print(f"{name}: {avg:.0f}")
