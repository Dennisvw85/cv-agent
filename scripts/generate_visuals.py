"""Projectbeelden voor de website, gemaakt en gecontroleerd met vier Foundry-diensten.

Per project in visuals/projects.json:
1. FLUX.2-pro maakt een beeld (beeldgeneratie).
2. Azure AI Content Safety controleert het beeld (verantwoorde AI voor beeld).
3. Phi-4-multimodal schrijft een Engelse alt-tekst (multimodaal begrip, klein model).
4. Azure Translator zet de alt-tekst om naar het Nederlands.

Daarna schrijft het script de beelden en de sectie "Projecten" in de website-repo.
Alles keyless: één Entra-token via DefaultAzureCredential.

Draaien (vanuit de root van cv-agent, website-repo ernaast):
    uv run --env-file .azure/dev/.env scripts/generate_visuals.py [--force]
"""

import base64
import html
import json
import os
import pathlib
import sys
import time

import requests
from azure.identity import DefaultAzureCredential

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = pathlib.Path(os.environ.get("WEBSITE_SRC", ROOT.parent / "website" / "src"))
ACCOUNT = os.environ["FOUNDRY_ACCOUNT_NAME"]
MAX_SEVERITY = 0  # alles boven "veilig" wordt afgekeurd en opnieuw gegenereerd
FORCE = "--force" in sys.argv

credential = DefaultAzureCredential()


def headers(scope: str) -> dict:
    return {"Authorization": f"Bearer {credential.get_token(scope).token}", "Content-Type": "application/json"}


def post(url: str, scope: str, body, attempts: int = 5) -> dict:
    """POST met herhaalpogingen: de vision-deployments hebben bewust weinig capaciteit (429)."""
    for attempt in range(attempts):
        try:
            response = requests.post(url, headers=headers(scope), json=body, timeout=120)
        except requests.Timeout:
            print(f"    time-out bij {url.split('/')[-1].split('?')[0]}, opnieuw")
            continue
        if response.status_code == 429 and attempt < attempts - 1:
            wait = int(response.headers.get("retry-after", 20))
            print(f"    429, {wait} s wachten")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("onbereikbaar")


def generate(prompt: str) -> str:
    data = post(
        f"https://{ACCOUNT}.services.ai.azure.com/providers/blackforestlabs/v1/flux-2-pro?api-version=preview",
        "https://cognitiveservices.azure.com/.default",
        {"prompt": prompt, "n": 1, "width": 1024, "height": 576, "output_format": "jpeg", "model": "flux-2-pro"},
    )
    return data["data"][0]["b64_json"]


def is_safe(image_b64: str) -> tuple[bool, list]:
    data = post(
        f"https://{ACCOUNT}.cognitiveservices.azure.com/contentsafety/image:analyze?api-version=2024-09-01",
        "https://cognitiveservices.azure.com/.default",
        {"image": {"content": image_b64}},
    )
    scores = [(c["category"], c["severity"]) for c in data["categoriesAnalysis"]]
    return all(severity <= MAX_SEVERITY for _, severity in scores), scores


def describe(image_b64: str) -> str:
    data = post(
        f"https://{ACCOUNT}.services.ai.azure.com/openai/v1/chat/completions",
        "https://ai.azure.com/.default",
        {
            "model": "phi-4-multimodal",
            "temperature": 0,
            "max_tokens": 80,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "Write alt text for this image in English, one sentence, at most 20 words, "
                                         "following WCAG: describe what is visible, do not start with 'image of'."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]}],
        },
    )
    return data["choices"][0]["message"]["content"].strip().strip('"')


def translate(text: str) -> str:
    data = post(
        f"https://{ACCOUNT}.cognitiveservices.azure.com/translator/text/v3.0/translate?api-version=3.0&from=en&to=nl",
        "https://cognitiveservices.azure.com/.default",
        [{"text": text}],
    )
    return data[0]["translations"][0]["text"]


def render(projects: list[dict]) -> str:
    cards = []
    for p in projects:
        tags = "".join(f"<span>{html.escape(t)}</span>" for t in p["tags"])
        cards.append(f'''        <a class="project reveal" href="{html.escape(p["url"])}" rel="noopener">
          <img src="img/projects/{p["slug"]}.jpg" alt="{html.escape(p["alt_nl"])}" width="1024" height="576" loading="lazy" />
          <div class="project-text">
            <h3>{html.escape(p["title"])}</h3>
            <p>{html.escape(p["description"])}</p>
            <div class="project-tags">{tags}</div>
          </div>
        </a>''')
    return "\n".join(cards)


def main() -> None:
    projects = json.loads((ROOT / "visuals" / "projects.json").read_text())
    cache_file = ROOT / "visuals" / "generated.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    img_dir = SITE / "img" / "projects"
    img_dir.mkdir(parents=True, exist_ok=True)

    for p in projects:
        target = img_dir / f"{p['slug']}.jpg"
        if target.exists() and p["slug"] in cache and not FORCE:
            p.update(cache[p["slug"]])
            print(f"{p['slug']}: bestaat al (gebruik --force om opnieuw te maken)")
            continue
        print(f"{p['slug']}:")
        for attempt in range(3):
            image = generate(p["prompt"])
            safe, scores = is_safe(image)
            print(f"  1-2 beeld gemaakt en gecontroleerd: {scores}")
            if safe:
                break
            print("  afgekeurd door Content Safety, opnieuw")
        else:
            raise RuntimeError(f"{p['slug']}: geen veilig beeld na 3 pogingen")
        target.write_bytes(base64.b64decode(image))
        alt_en = describe(image)
        alt_nl = translate(alt_en)
        print(f"  3 alt-tekst (Phi-4): {alt_en}\n  4 vertaald (Translator): {alt_nl}")
        cache[p["slug"]] = {"alt_en": alt_en, "alt_nl": alt_nl, "safety": scores}
        p.update(cache[p["slug"]])

    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")

    index = SITE / "index.html"
    page = index.read_text()
    start, end = "<!-- PROJECTS:START -->", "<!-- PROJECTS:END -->"
    before, _, rest = page.partition(start)
    _, _, after = rest.partition(end)
    index.write_text(f"{before}{start}\n{render(projects)}\n        {end}{after}")
    print(f"Website bijgewerkt: {index}")


if __name__ == "__main__":
    main()
