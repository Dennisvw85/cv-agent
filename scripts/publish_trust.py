"""Zet de evaluatie- en red-team-resultaten om naar trust.json voor de sectie "Vertrouwen" op de site.

Leest evals/results/latest.json (eigen evaluatie) en evals/results/red_team.json (AI Red Teaming Agent).
Publiceert alleen samenvattingen: geen vragen of antwoorden uit de aanvalsscan.
    uv run scripts/publish_trust.py
"""

import collections
import datetime
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = pathlib.Path(os.environ.get("WEBSITE_SRC", ROOT.parent / "website" / "src"))
RESULTS = ROOT / "evals" / "results"
LABELS = {"cv": "Feiten uit het CV", "repo": "Projecten (File Search)", "off_topic": "Buiten het onderwerp",
          "privacy": "Privacy", "future": "Speculatie", "jailbreak": "Jailbreaks"}


def evaluation() -> dict:
    rows = json.loads((RESULTS / "latest.json").read_text())
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["category"]][0] += r["passed"]
        per[r["category"]][1] += 1
    return {
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "categories": [{"name": LABELS.get(k, k), "passed": v[0], "total": v[1]} for k, v in per.items()],
    }


def red_team() -> dict | None:
    path = RESULTS / "red_team.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    card = data.get("scorecard") or data.get("redteaming_scorecard") or {}
    summary = (card.get("risk_category_summary") or [{}])[0]
    techniques = (card.get("attack_technique_summary") or [{}])[0]
    rows = data.get("attack_details") or data.get("redteaming_data") or []
    return {
        "attacks": len(rows),
        "overall_asr": summary.get("overall_asr"),
        "per_risk": {k.replace("_asr", ""): v for k, v in summary.items() if k.endswith("_asr") and k != "overall_asr"},
        "per_complexity": {k.replace("_asr", ""): v for k, v in techniques.items() if k.endswith("_asr")},
    }


def main() -> None:
    trust = {"updated": datetime.date.today().isoformat(), "evaluation": evaluation(), "red_team": red_team()}
    (SITE / "trust.json").write_text(json.dumps(trust, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(trust, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
