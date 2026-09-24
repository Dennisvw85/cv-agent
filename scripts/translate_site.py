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


def main() -> None:
    page = (SITE / "index.html").read_text()
    head, body_start, rest = page.partition("<body>")
    body, body_end, tail = rest.partition("</body>")

    # Scripts niet laten vertalen: eruit halen en er daarna weer in zetten.
    scripts = re.findall(r"<script[\s\S]*?</script>", body)
    for i, script in enumerate(scripts):
        body = body.replace(script, f"<!--SCRIPT{i}-->", 1)

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

    head = head.replace('<html lang="nl">', '<html lang="en">')
    title = re.search(r"<title>(.*?)</title>", head)
    if title:
        head = head.replace(title.group(0), f"<title>{translate([title.group(1)])[0]}</title>")
    (SITE / "en.html").write_text(head + body_start + translated + body_end + tail)
    print(f"en.html geschreven: {len(translated)} tekens, {sum(map(len, batches))} delen in {len(batches)} verzoek(en)")


if __name__ == "__main__":
    main()
