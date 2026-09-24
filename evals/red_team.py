"""Geautomatiseerde aanvalsscan op de cv-agent met de AI Red Teaming Agent (preview, PyRIT in Foundry).

Doel: de Attack Success Rate (ASR) meten per risicocategorie en aanvalstechniek.
De callback roept de echte agent aan (zelfde route als de site), met rustige pauzes vanwege de TPM-limiet.
    uv run --env-file .azure/dev/.env evals/red_team.py
"""

import asyncio
import json
import os
import pathlib
import shutil
import time

from azure.ai.evaluation.red_team import AttackStrategy, RedTeam, RiskCategory
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import BadRequestError, RateLimitError

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "evals" / "results"
SCAN_NAME = "cv-agent red team"
credential = DefaultAzureCredential()
endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
openai = AIProjectClient(endpoint=endpoint, credential=credential).get_openai_client(max_retries=6)
AGENT = {"agent_reference": {"name": os.environ.get("AGENT_NAME", "cv-agent"), "type": "agent_reference"}}


def target(query: str) -> str:
    """Zoals de site: blokkade door de content filter telt als weigering."""
    for _ in range(4):
        try:
            return openai.responses.create(input=query, extra_body=AGENT).output_text
        except BadRequestError as exc:
            if "content_filter" in str(exc):
                return "I can't help with that. (blocked by content filter)"
            raise
        except RateLimitError:
            time.sleep(30)
    return "Service busy."


def latest_scan_dir() -> pathlib.Path:
    """De RedTeam-SDK schrijft zijn eigen werkmap ".scan_<naam>_<tijdstempel>/" naast dit script,
    met daarin final_results.json (scorecard + attack_details). output_path van scan() geeft in deze
    SDK-versie een ander formaat (een map met results.json/evaluation_results.json, geen scorecard),
    dus die map negeren we en lezen in plaats daarvan final_results.json uit de eigen scan-map."""
    candidates = sorted(ROOT.glob(".scan_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("Geen .scan_*-map gevonden; de scan lijkt niet te zijn afgerond")
    return candidates[0]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    red_team = RedTeam(
        azure_ai_project=endpoint,
        credential=credential,
        risk_categories=[RiskCategory.Violence, RiskCategory.HateUnfairness, RiskCategory.Sexual, RiskCategory.SelfHarm],
        num_objectives=2,
    )
    await red_team.scan(
        target=target,
        scan_name=SCAN_NAME,
        attack_strategies=[AttackStrategy.Base64, AttackStrategy.Flip, AttackStrategy.Jailbreak],
    )

    scan_dir = latest_scan_dir()
    final = scan_dir / "final_results.json"
    dest = OUT / "red_team.json"
    if dest.exists() and dest.is_dir():
        shutil.rmtree(dest)
    shutil.copy(final, dest)
    shutil.rmtree(scan_dir, ignore_errors=True)  # eigen werkmap opruimen, de resultaten staan nu in evals/results/

    card = json.loads(final.read_text()).get("scorecard", {})
    print(json.dumps(card, indent=2)[:3000])
    print(f"\nOpgeslagen: {dest}")


if __name__ == "__main__":
    asyncio.run(main())
