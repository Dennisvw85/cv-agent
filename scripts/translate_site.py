"""Engelse versie van de website met Azure Translator (Foundry Tools), keyless.

Vertaalt de <body> van index.html als HTML (textType=html): opmaak blijft staan, elementen met
class="notranslate" worden overgeslagen. Schrijft en.html naast index.html, zodat alle paden kloppen.
    uv run --env-file .azure/dev/.env scripts/translate_site.py
"""

import os
import pathlib
import re

import requests
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = pathlib.Path(os.environ.get("WEBSITE_SRC", ROOT.parent / "website" / "src"))
ACCOUNT = os.environ["FOUNDRY_ACCOUNT_NAME"]
URL = f"https://{ACCOUNT}.cognitiveservices.azure.com/translator/text/v3.0/translate?api-version=3.0&from=nl&to=en&textType=html"
MAX_CHARS = 45_000  # Translator accepteert maximaal 50.000 tekens per verzoek

token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token


def translate(chunks: list[str]) -> list[str]:
    response = requests.post(
        URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=[{"text": c} for c in chunks],
        timeout=120,
    )
    response.raise_for_status()
    return [item["translations"][0]["text"] for item in response.json()]


def translate_attrs(html: str) -> str:
    """De Translator vertaalt in HTML-mode alleen tekstknopen, geen attributen.
    aria-label, placeholder, title en alt (beschrijvende afbeeldingen) alsnog los vertalen."""
    pattern = re.compile(r'\b(aria-label|placeholder|title|alt)="([^"]+)"')
    matches = list(pattern.finditer(html))
    if not matches:
        return html
    values = [m.group(2) for m in matches]
    translated_values = translate(values)
    for m, new_value in zip(reversed(matches), reversed(translated_values)):
        html = html[: m.start(2)] + new_value + html[m.end(2) :]
    return html


def main() -> None:
    page = (SITE / "index.html").read_text()
    head, body_start, rest = page.partition("<body>")
    body, body_end, tail = rest.partition("</body>")

    # Scripts niet laten vertalen: eruit halen en er daarna weer in zetten.
    scripts = re.findall(r"<script[\s\S]*?</script>", body)
    for i, script in enumerate(scripts):
        body = body.replace(script, f"<!--SCRIPT{i}-->", 1)

    # <main> apart houden: de sectie-split hieronder snijdt er middenin, en de Translator sluit
    # of laat losse open/dicht-tags dan stilzwijgend vallen (gaf een verplaatste </main>).
    main_open = re.search(r"<main[^>]*>", body)
    main_close = body.rfind("</main>")
    if main_open and main_close != -1:
        body = body[: main_open.start()] + "<!--MAINOPEN-->" + body[main_open.end() : main_close] + "<!--MAINCLOSE-->" + body[main_close + len("</main>") :]

    # Per sectie vertalen, binnen de tekenlimiet.
    parts = re.split(r"(?=<section|<footer)", body)
    batches, current = [], []
    for part in parts:
        if current and sum(map(len, current)) + len(part) > MAX_CHARS:
            batches.append(current)
            current = []
        current.append(part)
    batches.append(current)
    translated = "".join("".join(translate(batch)) for batch in batches)

    for i, script in enumerate(scripts):
        translated = translated.replace(f"<!--SCRIPT{i}-->", script)
    if main_open and main_close != -1:
        translated = translated.replace("<!--MAINOPEN-->", main_open.group(0)).replace("<!--MAINCLOSE-->", "</main>")

    head = head.replace('<html lang="nl">', '<html lang="en">')
    title = re.search(r"<title>(.*?)</title>", head)
    if title:
        head = head.replace(title.group(0), f"<title>{translate([title.group(1)])[0]}</title>")

    full = head + body_start + translated + body_end + tail
    full = translate_attrs(full)
    # svg-attributen komen uit de HTML-mode vertaling soms verlaagd terug (viewbox i.p.v. viewBox);
    # browsers herstellen dit zelf bij het parsen, maar netter om het in de bron te fixen.
    full = full.replace('viewbox="', 'viewBox="')
    # Bekende Translator-eigenaardigheid: "agent" (de AI-agent) wordt soms "officer".
    full = re.sub(r"\bofficer\b", "agent", full)
    full = re.sub(r"\bOfficer\b", "Agent", full)
    # Taalwissel-link op de EN-pagina moet terug naar de NL-versie wijzen, niet naar zichzelf.
    full = full.replace(
        '<a class="lang notranslate" href="en.html" hreflang="en" lang="en">EN</a>',
        '<a class="lang notranslate" href="index.html" hreflang="nl" lang="nl">NL</a>',
    )
    (SITE / "en.html").write_text(full)
    print(f"en.html geschreven: {len(translated)} tekens, {sum(map(len, batches))} delen in {len(batches)} verzoek(en)")


if __name__ == "__main__":
    main()
