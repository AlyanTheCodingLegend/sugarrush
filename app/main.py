from __future__ import annotations
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import WA_APP_SECRET, WA_VERIFY_TOKEN
from app.db import SessionLocal, Report, Run, init_db
from app import pipeline, send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

VALID_COMMANDS = {"scout", "alerts", "competitors", "campaigns", "opportunities", "pricing", "content", "help"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("DB initialised")
    yield


app = FastAPI(title="Sugar Rush Scout Agent", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_command(body: str) -> str:
    word = body.strip().lower().split()[0] if body.strip() else "help"
    return word if word in VALID_COMMANDS else "help"


def _verify_meta_signature(raw_body: bytes, signature_header: str) -> bool:
    """Validate X-Hub-Signature-256 from Meta using App Secret."""
    if not WA_APP_SECRET:
        return True  # skip validation when App Secret not configured
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(WA_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def webhook_verify(request: Request):
    """Meta webhook verification handshake (one-time setup step)."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        logger.info("Webhook verified by Meta")
        return PlainTextResponse(challenge)

    logger.warning("Webhook verification failed: mode=%s token=%s", mode, token)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Meta WhatsApp Cloud API inbound webhook."""
    raw_body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not _verify_meta_signature(raw_body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    # Walk the nested Meta payload to extract message + sender
    try:
        entry = data["entry"][0]
        change = entry["changes"][0]["value"]
        message = change["messages"][0]
        body_text = message.get("text", {}).get("body", "")
        sender = message["from"]  # E.164 number, e.g. "923001234567"
    except (KeyError, IndexError):
        # Status updates / delivery receipts — ack with 200, ignore
        return JSONResponse({"status": "ok"})

    command = _parse_command(body_text)
    logger.info("Webhook: command=%r from=%s", command, sender)

    background_tasks.add_task(_run_and_reply, command, sender)
    return JSONResponse({"status": "ok"})


def _run_and_reply(command: str, sender: str) -> None:
    try:
        report = pipeline.run(command)
        send.send_whatsapp(sender, report)
    except Exception as exc:
        logger.error("Background pipeline failed for command %r: %s", command, exc)
        try:
            send.send_whatsapp(
                sender,
                f"Sorry, the scout agent hit an error: {type(exc).__name__}. Please try again shortly.",
            )
        except Exception:
            pass


@app.post("/scout")
async def scout_endpoint():
    """Shorthand for POST /run/scout."""
    return await run_command("scout")


@app.post("/run/{command}")
async def run_command(command: str):
    """
    Run any command via HTTP — no WhatsApp needed.
    Valid commands: scout, alerts, competitors, campaigns, opportunities, pricing, content, help
    Returns JSON: {report, command, run_id, findings_count}

    Examples:
      curl -X POST http://localhost:8000/run/scout
      curl -X POST http://localhost:8000/run/alerts
      curl -X POST http://localhost:8000/run/opportunities
    """
    command = command.lower().strip()
    if command not in VALID_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown command '{command}'. Valid: {sorted(VALID_COMMANDS)}",
        )
    try:
        report = pipeline.run(command)
        with SessionLocal() as db:
            latest_run = (
                db.query(Run)
                .filter(Run.status.in_(["ok", "partial"]))
                .order_by(Run.finished_at.desc())
                .first()
            )
            run_id = latest_run.id if latest_run else None
            finding_count = latest_run.finding_count if latest_run else 0
        return JSONResponse({
            "report": report,
            "command": command,
            "run_id": run_id,
            "findings_count": finding_count,
        })
    except Exception as exc:
        logger.error("/run/%s error: %s", command, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/report/latest")
async def latest_report(command: str = "scout"):
    """Return the most recent stored report for a given command."""
    with SessionLocal() as db:
        report = (
            db.query(Report)
            .filter(Report.command == command)
            .order_by(Report.created_at.desc())
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail=f"No report found for command '{command}'")
    return JSONResponse({
        "command": report.command,
        "report_text": report.report_text,
        "created_at": str(report.created_at),
        "run_id": report.run_id,
    })
