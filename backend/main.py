"""
Missed Call SOS - backend

One FastAPI app that does four things:
  1. Answers Twilio's incoming-call webhook with <Reject/> so the call is never
     picked up. The caller is not charged and neither are you - the ring itself
     is the signal.
  2. Turns (dialed number -> severity) and (caller number -> location) into a row.
  3. Stores rows in SQLite.
  4. Pushes every new row to the dashboard over a WebSocket.

Run:  uvicorn main:app --reload --port 8000
"""

import asyncio
import hashlib
import json
import random
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "calls.db"
CONFIG_PATH = BASE_DIR / "config.json"

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
SEVERITY_BY_NUMBER = CONFIG["severity_by_number"]     # dialed number -> level
SEVERITY_LABELS = CONFIG["severity_labels"]           # level -> {en, bn}
CALLER_REGISTRY = CONFIG["caller_registry"]           # caller number -> place
PLACES = CONFIG["places"]                             # place id -> {name, lat, lng, district}


def normalise(number: str) -> str:
    """Strip spaces/dashes so +880 1712-345678 and +8801712345678 match."""
    return "".join(ch for ch in (number or "") if ch.isdigit() or ch == "+")


def severity_for(dialed: str) -> int:
    """Map the number that was dialed to a severity level. Only used if you
    later add Twilio numbers back in alongside the single Teletalk line."""
    dialed = normalise(dialed)
    if dialed in SEVERITY_BY_NUMBER:
        return SEVERITY_BY_NUMBER[dialed]
    tail = dialed[-4:]
    for configured, level in SEVERITY_BY_NUMBER.items():
        if normalise(configured).endswith(tail):
            return level
    return 1


# --------------------------------------------------------------------------
# Repeat-call severity (single-number mode)
#
# With one real SIM there's only one number to dial, so severity comes from
# how many times in a row someone calls, not which number they called.
# Call once = water rising. Call again within the window = escalate.
# Three or more = need rescue. This mirrors the existing "call twice so I
# know it's really you" missed-call habit - we're just giving that pattern
# somewhere to land.
# --------------------------------------------------------------------------

CALL_WINDOW_SECONDS = CONFIG.get("repeat_window_seconds", 90)
_repeat_lock = threading.Lock()
_repeat_calls: dict[str, list[float]] = {}


def bucket_severity(caller: str) -> int:
    caller = normalise(caller)
    now = time.time()
    with _repeat_lock:
        window = _repeat_calls.setdefault(caller, [])
        window[:] = [t for t in window if now - t < CALL_WINDOW_SECONDS]
        window.append(now)
        count = len(window)
    return min(count, 3)


def locate(caller: str) -> dict:
    """
    Resolve a caller to a place.

    Registered numbers (community volunteers who signed up once, by SMS or in
    person) resolve to their real union/upazila. Anyone else - including a judge
    dialling in for the first time - is assigned a place deterministically from a
    hash of their number, and flagged as unregistered so the map never pretends
    that pin is verified.
    """
    caller = normalise(caller)
    place_ids = list(PLACES.keys())

    if caller in CALLER_REGISTRY:
        place_id = CALLER_REGISTRY[caller]
        registered = True
    else:
        digest = hashlib.sha256(caller.encode()).hexdigest()
        place_id = place_ids[int(digest[:8], 16) % len(place_ids)]
        registered = False

    place = PLACES[place_id]
    # Small jitter so several calls from one upazila don't stack into one dot.
    rng = random.Random(caller)
    return {
        "place_id": place_id,
        "upazila": place["name"],
        "district": place["district"],
        "lat": place["lat"] + rng.uniform(-0.035, 0.035),
        "lng": place["lng"] + rng.uniform(-0.035, 0.035),
        "registered": registered,
    }


def mask(number: str) -> str:
    """Never show a full caller number on a screen that faces a room."""
    number = normalise(number)
    if len(number) <= 4:
        return number
    return number[:4] + "*" * (len(number) - 8) + number[-4:]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

_db_lock = threading.Lock()
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.execute(
    """
    CREATE TABLE IF NOT EXISTS calls (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        call_sid      TEXT,
        caller        TEXT NOT NULL,
        caller_masked TEXT NOT NULL,
        dialed        TEXT NOT NULL,
        severity      INTEGER NOT NULL,
        place_id      TEXT NOT NULL,
        upazila       TEXT NOT NULL,
        district      TEXT NOT NULL,
        lat           REAL NOT NULL,
        lng           REAL NOT NULL,
        registered    INTEGER NOT NULL,
        source        TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )
    """
)
_db.commit()


def record_call(caller: str, dialed: str, level: int, call_sid: str | None, source: str) -> dict:
    place = locate(caller)
    row = {
        "call_sid": call_sid,
        "caller": normalise(caller),
        "caller_masked": mask(caller),
        "dialed": normalise(dialed),
        "severity": level,
        "place_id": place["place_id"],
        "upazila": place["upazila"],
        "district": place["district"],
        "lat": round(place["lat"], 5),
        "lng": round(place["lng"], 5),
        "registered": 1 if place["registered"] else 0,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _db_lock:
        cur = _db.execute(
            """INSERT INTO calls
               (call_sid, caller, caller_masked, dialed, severity, place_id,
                upazila, district, lat, lng, registered, source, created_at)
               VALUES (:call_sid, :caller, :caller_masked, :dialed, :severity,
                       :place_id, :upazila, :district, :lat, :lng, :registered,
                       :source, :created_at)""",
            row,
        )
        _db.commit()
        row["id"] = cur.lastrowid
    row.pop("caller")  # the raw number stays in the DB, never on the wire
    row["label"] = SEVERITY_LABELS[str(level)]
    return row


def recent_calls(limit: int = 300) -> list[dict]:
    with _db_lock:
        rows = _db.execute(
            "SELECT * FROM calls ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("caller")
        d["label"] = SEVERITY_LABELS[str(d["severity"])]
        out.append(d)
    return out


def stats() -> dict:
    with _db_lock:
        total = _db.execute("SELECT COUNT(*) c FROM calls").fetchone()["c"]
        by_sev = _db.execute(
            "SELECT severity, COUNT(*) c FROM calls GROUP BY severity"
        ).fetchall()
        places = _db.execute(
            "SELECT COUNT(DISTINCT place_id) c FROM calls"
        ).fetchone()["c"]
        callers = _db.execute("SELECT COUNT(DISTINCT caller) c FROM calls").fetchone()["c"]
    return {
        "total": total,
        "by_severity": {str(r["severity"]): r["c"] for r in by_sev},
        "places": places,
        "callers": callers,
    }


# --------------------------------------------------------------------------
# WebSocket fan-out
# --------------------------------------------------------------------------

class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.clients.add(ws)

    async def leave(self, ws: WebSocket) -> None:
        async with self.lock:
            self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self.lock:
            targets = list(self.clients)
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                await self.leave(ws)


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Missed Call SOS", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+",
    allow_origins=["*"],  # fallback: covers ngrok, judges' networks, etc.
    allow_methods=["*"],
    allow_headers=["*"],
)


async def publish(row: dict) -> None:
    await hub.broadcast({"type": "call", "call": row, "stats": stats()})


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.post("/voice")
async def voice_webhook(
    request: Request,
    From: str = Form(default=""),
    To: str = Form(default=""),
    CallSid: str = Form(default=""),
):
    """
    Twilio hits this the moment a call arrives.

    <Reject/> means Twilio never answers. The caller hears a busy tone, hangs up
    having spent nothing, and we already have everything we need: who rang, which
    number they rang, and when.
    """
    level = severity_for(To)
    row = record_call(caller=From, dialed=To, level=level, call_sid=CallSid, source="twilio")
    await publish(row)
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response><Reject reason="busy"/></Response>'
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/mobile-call")
async def mobile_call(payload: dict):
    """
    Fired by a MacroDroid macro running on a real Android phone holding a real
    SIM (e.g. Teletalk). The macro watches for 'Incoming Call: Ringing', posts
    here with the caller's number and which physical line rang, then rejects
    the call so the caller is never kept waiting and is never charged.

    Expected body: {"caller": "+8801XXXXXXXXX", "severity": 1|2|3}

    If you're running with a single phone/SIM for the whole demo, hardcode
    "severity" to whichever level that phone represents, or omit it entirely -
    it defaults to 3 so a bare ring still shows up as the most visible pin.
    """
    caller = payload.get("caller", "")
    if not caller:
        raise HTTPException(status_code=400, detail="caller is required")
    severity = int(payload.get("severity", 3))
    if severity not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="severity must be 1, 2 or 3")

    dialed = next(
        (num for num, lvl in SEVERITY_BY_NUMBER.items() if lvl == severity),
        f"teletalk-line-{severity}",
    )
    row = record_call(caller=caller, dialed=dialed, call_sid=None, source="mobile")
    await publish(row)
    return row


@app.post("/api/simulate")
async def simulate(payload: dict):
    """
    Fire a call without a phone. This is the demo safety net: if the venue wifi
    dies, Twilio rate-limits you, or nobody wants to dial an international
    number, the dashboard still fills up.
    """
    severity = int(payload.get("severity", 1))
    if severity not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="severity must be 1, 2 or 3")
    caller = payload.get("caller") or f"+8801{random.randint(100000000, 999999999)}"
    row = record_call(
        caller=caller, dialed="simulated", level=severity, call_sid=None, source="simulated"
    )
    await publish(row)
    return row


@app.get("/api/macrodroid")
@app.post("/api/macrodroid")
async def macrodroid_call(request: Request, caller: str = ""):
    """
    MacroDroid hits this every time your Teletalk phone shows a missed call.

    Severity comes from repeat-call bucketing: the same number calling again
    inside CALL_WINDOW_SECONDS escalates the level automatically, so a real
    caller on a real network gets exactly the same experience the pitch
    describes - call once, call again if it's worse, call a third time if
    you need rescuing.

    Accepts the caller's number either as a query string (?caller=...) for a
    plain GET action, or as form/JSON body for a POST action - whichever is
    easier to configure in your MacroDroid version.
    """
    if not caller:
        # Some MacroDroid configurations post form data instead of query params.
        try:
            form = await request.form()
            caller = form.get("caller", "")
        except Exception:
            pass
    if not caller:
        try:
            body = await request.json()
            caller = body.get("caller", "")
        except Exception:
            pass
    if not caller:
        raise HTTPException(status_code=400, detail="missing caller number")

    level = bucket_severity(caller)
    row = record_call(caller=caller, dialed="teletalk", level=level, call_sid=None, source="teletalk")
    await publish(row)
    return row


@app.get("/api/calls")
async def get_calls(limit: int = 300):
    return {"calls": recent_calls(limit), "stats": stats(), "config": public_config()}


@app.delete("/api/calls")
async def clear_calls():
    """Reset between demo runs."""
    with _db_lock:
        _db.execute("DELETE FROM calls")
        _db.commit()
    with _repeat_lock:
        _repeat_calls.clear()
    await hub.broadcast({"type": "reset", "stats": stats()})
    return {"ok": True}


def public_config() -> dict:
    return {
        "severity_labels": SEVERITY_LABELS,
        "single_number": CONFIG.get("teletalk_number", "not configured"),
        "repeat_window_seconds": CALL_WINDOW_SECONDS,
    }


@app.get("/api/config")
async def get_config():
    return public_config()


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "calls": stats()["total"]})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.join(ws)
    try:
        await ws.send_json({"type": "hello", "stats": stats()})
        while True:
            await ws.receive_text()  # keeps the socket open; we ignore content
    except WebSocketDisconnect:
        await hub.leave(ws)
    except Exception:
        await hub.leave(ws)