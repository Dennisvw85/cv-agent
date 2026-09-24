"""API achter de CV-site, als Container App.

Static Web Apps stuurt /api door naar deze app (linked backend); alleen de site kan hem bereiken.
- POST /api/chat   tekst-chat met de Foundry-agent (Responses API)
- POST /api/voice  WebRTC-handshake voor een spraakgesprek met dezelfde agent (Voice Live)

Bij spraak loopt de audio rechtstreeks tussen de browser en Azure. Deze app opent alleen het
controlekanaal naar Voice Live, met zijn managed identity, en sluit het na MAX_VOICE_SECONDS:
daarmee eindigt het gesprek. Zo krijgt de browser nooit een token te zien.
"""

import asyncio
import json
import logging
import os
import time
from urllib.parse import urlencode

import openai
import websockets
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cv-agent-api")

AGENT_NAME = os.environ.get("AGENT_NAME", "cv-agent")
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
FOUNDRY_ACCOUNT = PROJECT_ENDPOINT.split("//")[1].split(".")[0]
PROJECT_NAME = PROJECT_ENDPOINT.rstrip("/").rsplit("/", 1)[1]

MAX_MESSAGE_LENGTH = 500
MAX_VOICE_SECONDS = int(os.environ.get("MAX_VOICE_SECONDS", "180"))
MAX_VOICE_SESSIONS = int(os.environ.get("MAX_VOICE_SESSIONS", "2"))
VOICE_API_VERSION = "2026-01-01-preview"
VOICE = os.environ.get("VOICE_NAME", "en-US-AvaMultilingualNeural")

BLOCKED_ANSWER = (
    "Die vraag kan ik niet beantwoorden. Ik help je graag met vragen over de ervaring, "
    "certificeringen en projecten van Dennis. / I can't answer that, but I'm happy to help "
    "with questions about Dennis' experience, certifications and projects."
)

credential = DefaultAzureCredential()  # managed identity via AZURE_CLIENT_ID
project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)
openai_client = project.get_openai_client()
voice_slots = asyncio.Semaphore(MAX_VOICE_SESSIONS)
AVATAR_TOKEN_CLIENT_ID = os.environ.get("BROWSER_TOKEN_CLIENT_ID")
active_calls: dict[str, object] = {}  # sessie-ID -> open controlekanaal

app = FastAPI()


def error(status: int, text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(request: Request):
    try:
        data = await request.json()
    except ValueError:
        return error(400, "Verwacht JSON.")

    message = str(data.get("message", "")).strip()
    if not message:
        return error(400, "Stel een vraag.")
    if len(message) > MAX_MESSAGE_LENGTH:
        return error(400, f"Houd je vraag korter dan {MAX_MESSAGE_LENGTH} tekens.")

    kwargs = {
        "input": message,
        "max_output_tokens": 500,
        "extra_body": {"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
    }
    previous = data.get("previous_response_id")
    if isinstance(previous, str) and previous.startswith("resp_") and len(previous) < 100:
        kwargs["previous_response_id"] = previous

    try:
        response = await asyncio.to_thread(openai_client.responses.create, **kwargs)
    except openai.BadRequestError as exc:
        # De content filter van Foundry blokkeerde de vraag (bijvoorbeeld een jailbreak-poging).
        if "content_filter" in str(exc):
            log.warning("Vraag geblokkeerd door de content filter")
            return {"answer": BLOCKED_ANSWER, "response_id": None}
        log.exception("Ongeldig verzoek aan de agent")
        return error(502, "De assistent is even niet bereikbaar.")
    except openai.RateLimitError:
        return error(429, "Het is even druk, probeer het over een minuut opnieuw.")
    except Exception:  # noqa: BLE001 - details naar de logs, de bezoeker krijgt een nette melding
        log.exception("Agent-aanroep mislukt")
        return error(502, "De assistent is even niet bereikbaar.")

    return {"answer": response.output_text, "response_id": response.id}


async def hold_control_channel(ws, session_id: str) -> None:
    """Houdt het controlekanaal open tot het gesprek klaar is of de tijd op is, en sluit dan af."""
    started = time.monotonic()
    try:
        while time.monotonic() - started < MAX_VOICE_SECONDS:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            event = json.loads(raw)
            if event.get("type") in ("error", "rtc.call.error"):
                log.warning("Voice Live-fout in sessie %s: %s", session_id, event.get("error"))
    except websockets.ConnectionClosed:
        pass
    finally:
        active_calls.pop(session_id, None)
        await ws.close()
        voice_slots.release()
        log.info("Spraaksessie %s beëindigd na %.0f s", session_id, time.monotonic() - started)


@app.post("/api/voice")
async def voice(request: Request):
    try:
        data = await request.json()
    except ValueError:
        return error(400, "Verwacht JSON.")
    offer = data.get("sdp_offer")
    if not isinstance(offer, str) or not offer.startswith("v=0") or len(offer) > 20_000:
        return error(400, "Ongeldige SDP-offer.")

    # Kostenrem: maximaal MAX_VOICE_SESSIONS gesprekken tegelijk.
    if voice_slots.locked():
        return error(429, "Er lopen al gesprekken. Probeer het over een paar minuten opnieuw.")
    await voice_slots.acquire()

    try:
        token = (await asyncio.to_thread(credential.get_token, "https://ai.azure.com/.default")).token
        query = urlencode({
            "api-version": VOICE_API_VERSION,
            "agent-name": AGENT_NAME,
            "agent-project-name": PROJECT_NAME,
        })
        url = f"wss://{FOUNDRY_ACCOUNT}.services.ai.azure.com/voice-live/realtime/calls?{query}"
        ws = await websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {token}"}, subprotocols=["realtime"]
        )
        await ws.send(json.dumps({
            "type": "rtc.call.sdp.create",
            "sdp_offer": offer,
            "session": {
                "voice": {"name": VOICE, "type": "azure-standard"},
                "turn_detection": {"type": "azure_semantic_vad_multilingual", "silence_duration_ms": 600},
                "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
                "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            },
        }))
        session_id = "?"
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            kind = event.get("type")
            if kind == "session.created":
                session_id = event.get("session", {}).get("id", "?")
            elif kind == "rtc.call.sdp.created":
                break
            elif kind in ("error", "rtc.call.error"):
                raise RuntimeError(event.get("error"))
    except Exception:  # noqa: BLE001
        voice_slots.release()
        log.exception("Starten van spraaksessie mislukt")
        return error(502, "Spraak is even niet beschikbaar.")

    log.info("Spraaksessie %s gestart", session_id)
    active_calls[session_id] = ws
    asyncio.create_task(hold_control_channel(ws, session_id))
    return {"sdp_answer": event["sdp_answer"], "session_id": session_id, "max_seconds": MAX_VOICE_SECONDS}


@app.post("/api/voice/stop")
async def voice_stop(request: Request):
    """De bezoeker stopt: controlekanaal sluiten, zodat het gesprek en de plek meteen vrijkomen."""
    try:
        session_id = str((await request.json()).get("session_id", ""))
    except ValueError:
        return error(400, "Verwacht JSON.")
    ws = active_calls.get(session_id)
    if ws is not None:
        await ws.close()
    return {"stopped": ws is not None}


@app.post("/api/avatar/token")
async def avatar_token():
    """Token voor het live avatar-gesprek, volgens het patroon van Microsofts voice-live-avatar-sample.

    Een avatar werkt niet met het WebRTC-controlekanaal van /api/voice, dus hier praat de browser
    zelf met Voice Live. Het token komt van een aparte identiteit met alleen de twee rollen die
    Voice Live nodig heeft. Alleen bereikbaar via de site, dus alleen voor wie het wachtwoord heeft.
    """
    if not AVATAR_TOKEN_CLIENT_ID:
        return error(503, "Avatar is niet geconfigureerd.")
    token = await asyncio.to_thread(
        ManagedIdentityCredential(client_id=AVATAR_TOKEN_CLIENT_ID).get_token, "https://ai.azure.com/.default"
    )
    log.info("Avatar-token uitgegeven, geldig tot %s", time.strftime("%H:%M", time.gmtime(token.expires_on)))
    return {
        "token": token.token,
        "expires_on": token.expires_on,
        "endpoint": f"https://{FOUNDRY_ACCOUNT}.services.ai.azure.com/",
        "agent_name": AGENT_NAME,
        "project_name": PROJECT_NAME,
        "max_seconds": MAX_VOICE_SECONDS,
    }


# ---------------------------------------------------------------------------
# v2: vacature-matcher
# Content Understanding maakt van een PDF markdown; de agent "cv-matcher" vergelijkt die met het CV
# en geeft structured output (JSON-schema) terug. Eigen deployment "cv-match" = eigen kostenrem.
# ---------------------------------------------------------------------------
import base64
import httpx

MATCH_AGENT = "cv-matcher"
MAX_JOB_CHARS = 12_000
MAX_PDF_BYTES = 4 * 1024 * 1024
CU_URL = f"https://{FOUNDRY_ACCOUNT}.services.ai.azure.com/contentunderstanding"
match_slots = asyncio.Semaphore(2)


async def pdf_to_markdown(pdf: bytes) -> str:
    """Content Understanding (GA 2025-11-01), prebuilt-layout: OCR + layout naar markdown."""
    token = (await asyncio.to_thread(credential.get_token, "https://cognitiveservices.azure.com/.default")).token
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        start = await client.post(
            f"{CU_URL}/analyzers/prebuilt-layout:analyzeBinary?api-version=2025-11-01",
            headers={**headers, "Content-Type": "application/pdf"},
            content=pdf,
        )
        start.raise_for_status()
        location = start.headers["Operation-Location"]
        for _ in range(20):
            await asyncio.sleep(1)
            result = (await client.get(location, headers=headers)).json()
            if result["status"] == "Succeeded":
                return result["result"]["contents"][0]["markdown"]
            if result["status"] not in ("Running", "NotStarted"):
                raise RuntimeError(f"Content Understanding: {result['status']}")
    raise TimeoutError("Content Understanding duurde te lang")


@app.post("/api/match")
async def match(request: Request):
    try:
        data = await request.json()
    except ValueError:
        return error(400, "Verwacht JSON.")

    if match_slots.locked():
        return error(429, "Er lopen al matches. Probeer het over een minuut opnieuw.")
    async with match_slots:
        source = "tekst"
        try:
            if data.get("pdf_base64"):
                pdf = base64.b64decode(str(data["pdf_base64"]), validate=True)
                if len(pdf) > MAX_PDF_BYTES or not pdf.startswith(b"%PDF"):
                    return error(400, "Upload een PDF van maximaal 4 MB.")
                job = await pdf_to_markdown(pdf)
                source = "pdf"
            else:
                job = str(data.get("text", "")).strip()
        except Exception:  # noqa: BLE001
            log.exception("PDF verwerken mislukt")
            return error(502, "De PDF kon niet worden gelezen.")

        if len(job) < 80:
            return error(400, "Plak een volledige vacaturetekst of upload een PDF.")
        job = job[:MAX_JOB_CHARS]

        try:
            response = await asyncio.to_thread(
                openai_client.responses.create,
                input=job,
                extra_body={"agent_reference": {"name": MATCH_AGENT, "type": "agent_reference"}},
            )
            result = json.loads(response.output_text)
        except openai.RateLimitError:
            return error(429, "Het is even druk, probeer het over een minuut opnieuw.")
        except openai.BadRequestError as exc:
            if "content_filter" in str(exc):
                return error(400, "Deze tekst kan ik niet beoordelen.")
            log.exception("Matcher: ongeldig verzoek")
            return error(502, "De matcher is even niet bereikbaar.")
        except Exception:  # noqa: BLE001
            log.exception("Matcher mislukt")
            return error(502, "De matcher is even niet bereikbaar.")

    result["source"] = source
    return result
