"""Loopbaan in één beeld: een build-time script dat de Code Interpreter-tool van Microsoft Foundry
een tijdlijngrafiek laat tekenen op basis van knowledge/cv.md.

Werkwijze:
1. Werkgevers en jaren uit cv.md halen (regex op de "### Titel, Werkgever (jaar tot jaar)"-koppen).
2. Eén responses.create-aanroep op de bestaande cv-chat-deployment (geen nieuwe agent, geen nieuwe
   deployment) met de Code Interpreter-tool: het model schrijft matplotlib-code en tekent de grafiek
   in een ephemeral container.
3. Het gegenereerde PNG-bestand (container_file_citation) downloaden naar website/src/img/timeline.png.
4. Een alt-tekst schrijven (deterministisch, uit de zelfde geparste data: geen extra modelaanroep nodig).
5. Een klein blok in de sectie Ervaring van index.html bijwerken (tussen TIMELINE:START/END-markers).

Draaien:
    uv run --env-file .azure/dev/.env scripts/generate_timeline.py
"""

import datetime
import os
import pathlib
import re

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = pathlib.Path(os.environ.get("WEBSITE_SRC", ROOT.parent / "website" / "src"))
DEPLOYMENT = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]  # cv-chat: geen extra deployment nodig

JOB_RE = re.compile(r"^### (.+?), (.+?) \(([^)]+)\)\s*$", re.MULTILINE)
MONTHS = {m: i + 1 for i, m in enumerate([
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
])}
MIN_SPAN = 0.6  # jaar: zichtbare minimumbreedte voor een balk van één jaar


def jobs() -> list[dict]:
    cv = (ROOT / "knowledge" / "cv.md").read_text()
    work, _, _ = cv.partition("## Certifications")
    rows = []
    for title, org, period in JOB_RE.findall(work):
        rows.append({"title": title.strip(), "org": org.strip(), "period": period.strip()})
    if not rows:
        raise RuntimeError("Geen werkervaring gevonden in knowledge/cv.md")
    return rows


def parse_point(text: str, today: datetime.date) -> tuple[float, str]:
    """"March 2026" -> (2026.17, "mrt 2026"); "2024" -> (2024.0, "2024"); "present" -> (vandaag, "nu")."""
    text = text.strip()
    if text.lower() == "present":
        return today.year + (today.month - 1) / 12, "nu"
    parts = text.split()
    if len(parts) == 2 and parts[0].lower() in MONTHS:
        month = MONTHS[parts[0].lower()]
        year = int(parts[1])
        return year + (month - 1) / 12, f"{parts[0][:3].lower()} {year}"
    year = int(text)
    return float(year), str(year)


def numeric_rows(rows: list[dict], today: datetime.date) -> list[dict]:
    """Voegt start/eind als getal (jaar met maandfractie) en een korte weergavelabel toe."""
    out = []
    for r in rows:
        start_text, sep, end_text = r["period"].partition(" to ")
        start, start_label = parse_point(start_text, today)
        if sep:
            end, end_label = parse_point(end_text, today)
            label = f"{start_label} – {end_label}"
        else:
            end, end_label = start, start_label  # één jaar, geen "to" in de tekst (bijv. "2024")
            label = start_label
        display_end = max(end, start + MIN_SPAN)  # zichtbare minimumbreedte, het label blijft correct
        out.append({**r, "start": round(start, 3), "end": round(display_end, 3), "label": label})
    return out


COLORS = ["#8fb3a3", "#c99b8f", "#9aa6c9", "#c9b98f", "#a893c2"]


def render_prompt(rows: list[dict]) -> str:
    """Geeft het model bijna-kant-en-klare matplotlib-code (met exacte, al uitgerekende getallen), zodat het
    alleen nog hoeft uit te voeren via de Code Interpreter. Eerdere, vrijere prompts leverden onleesbare of
    kapotte grafieken op (tekst over de balken, of vervormde vormen door een rounded-corner-poging)."""
    items = []
    for i, r in enumerate(reversed(rows)):  # oudste eerst = onderaan bij barh met y oplopend
        items.append(
            f'    {{"y": {i}, "start": {r["start"]}, "end": {r["end"]}, "color": "{COLORS[i % len(COLORS)]}", '
            f'"title": {r["title"]!r}, "sub": {(short_org(r["org"]) + " · " + r["label"])!r}}}'
        )
    data = ",\n".join(items)
    return (
        "Voer deze matplotlib-code exact uit via de Code Interpreter, zonder de opzet te veranderen (kleuren "
        "of kleine stijldetails mag je aanpassen, de structuur niet: platte rechthoeken, geen rounded corners, "
        "geen tekst binnen de balken). Sla op als timeline.png en geef verder geen uitleg terug.\n\n"
        "```python\n"
        "import matplotlib.pyplot as plt\n\n"
        f"rows = [\n{data}\n]\n\n"
        "fig, ax = plt.subplots(figsize=(11, 4.5), dpi=150)\n"
        "for r in rows:\n"
        "    ax.barh(r['y'], r['end'] - r['start'], left=r['start'], height=0.5, color=r['color'], "
        "edgecolor='none', zorder=2)\n"
        "    ax.text(r['start'], r['y'] + 0.32, r['title'], fontsize=9, fontweight='bold', va='bottom', "
        "ha='left', color='#333333')\n"
        "    ax.text(r['start'], r['y'] - 0.32, r['sub'], fontsize=8, va='top', ha='left', color='#666666')\n\n"
        "ax.set_yticks([])\n"
        "for spine in ('left', 'top', 'right'):\n"
        "    ax.spines[spine].set_visible(False)\n"
        "ax.set_xlabel('Jaar', fontsize=9, color='#666666')\n"
        "ax.tick_params(axis='x', labelsize=8, colors='#666666')\n"
        "ax.set_title('Loopbaan in beeld', fontsize=11, loc='left', color='#333333')\n"
        f"ax.set_xlim({min(r['start'] for r in rows) - 0.4}, {max(r['end'] for r in rows) + 0.4})\n"
        f"ax.set_ylim(-0.6, {len(rows) - 1 + 0.6})\n"
        "plt.tight_layout()\n"
        "plt.savefig('timeline.png', transparent=True, bbox_inches='tight')\n"
        "```"
    )


def find_image(response) -> tuple[str, str] | None:
    """Zoekt de container_file_citation met een echte .png-bestandsnaam in de output.

    Er komen soms twee annotaties voor hetzelfde bestand terug: één interne placeholder
    (filename = "cfile_....png", start_index == end_index == 0) en één met de bestandsnaam
    die in de prompt is gevraagd ("timeline.png"). Alleen die laatste is bruikbaar.
    """
    candidates = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            for ann in getattr(content, "annotations", None) or []:
                if getattr(ann, "type", None) == "container_file_citation":
                    candidates.append(ann)
    if not candidates:
        return None
    named = [a for a in candidates if not a.filename.startswith("cfile_")]
    best = named[0] if named else candidates[0]
    return best.container_id, best.file_id


def short_org(org: str) -> str:
    return re.split(r"[,|]", org)[0].strip()


def alt_text(rows: list[dict]) -> str:
    orgs = ", ".join(short_org(r["org"]) for r in reversed(rows))
    return f"Tijdlijngrafiek van de loopbaan van Dennis van Waas, chronologisch: {orgs}."


def main() -> None:
    rows = numeric_rows(jobs(), datetime.date.today())
    print(f"{len(rows)} functies gevonden in cv.md")

    project = AIProjectClient(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"], credential=DefaultAzureCredential()
    )
    openai = project.get_openai_client()

    print("Code Interpreter aan het werk zetten…")
    response = openai.responses.create(
        model=DEPLOYMENT,
        input=render_prompt(rows),
        tools=[{"type": "code_interpreter", "container": {"type": "auto"}}],
        tool_choice="required",  # anders schrijft het model soms alleen matplotlib-code als tekst, zonder hem te draaien
    )

    found = find_image(response)
    if not found:
        raise RuntimeError(
            "Geen gegenereerd bestand gevonden in de response. Ruwe output:\n"
            + (response.output_text or "(leeg)")
        )
    container_id, file_id = found
    print(f"  gevonden: container {container_id}, bestand {file_id}")

    img_dir = SITE / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    target = img_dir / "timeline.png"
    content = openai.containers.files.content.retrieve(file_id, container_id=container_id)
    content.write_to_file(target)
    print(f"  opgeslagen: {target} ({target.stat().st_size} bytes)")

    alt = alt_text(rows)
    print(f"  alt-tekst: {alt}")

    index = SITE / "index.html"
    page = index.read_text()
    start, end = "<!-- TIMELINE:START -->", "<!-- TIMELINE:END -->"
    block = (
        f'{start}\n'
        f'        <figure class="timeline-img reveal">\n'
        f'          <img src="img/timeline.png" alt="{alt}" loading="lazy" />\n'
        f'          <figcaption>Loopbaan in één beeld, getekend door de Code Interpreter-tool van Microsoft Foundry.</figcaption>\n'
        f'        </figure>\n'
        f'        {end}'
    )
    if start in page and end in page:
        before, _, rest = page.partition(start)
        _, _, after = rest.partition(end)
        page = f"{before}{block}{after}"
    else:
        page = page.replace("</ol>\n    </section>", f"</ol>\n\n        {block}\n    </section>", 1)
    index.write_text(page)
    print(f"Website bijgewerkt: {index}")


if __name__ == "__main__":
    main()
