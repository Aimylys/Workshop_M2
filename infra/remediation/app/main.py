import os
import secrets
import threading
import time
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from prometheus_client import make_asgi_app

from .docker_api import DockerAPI
from .engine import Engine
from .normalize import normalize


def load_config():
    with open(os.getenv("CONFIG_PATH", "/app/config.yaml")) as f:
        return yaml.safe_load(f)


def read_token():
    path = os.getenv("WEBHOOK_TOKEN_FILE", "/run/secrets/webhook_token")
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def create_app(engine=None, token=None, poll=True):
    cfg = engine.cfg if engine else load_config()
    if engine is None:
        engine = Engine(cfg, DockerAPI(os.getenv("DOCKER_HOST", "tcp://docker-proxy:2375"), cfg["project"]))
    expected = token if token is not None else read_token()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()

        def loop():
            while not stop.is_set():
                engine.refresh_states()
                stop.wait(5)

        if poll:
            threading.Thread(target=loop, daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="Orchestrateur de remédiation", lifespan=lifespan)
    app.mount("/metrics", make_asgi_app())

    def auth(authorization):
        if not expected:
            raise HTTPException(503, "jeton non configuré")
        got = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(got, expected):
            raise HTTPException(401, "non autorisé")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhook/alert")
    async def webhook(request: Request, authorization: str = Header(None)):
        auth(authorization)
        payload = await request.json()
        results = [engine.submit(i) for i in normalize(cfg, payload)]
        return {"received": len(results), "results": results}

    # Lecture seule : alimente le tableau de bord (aucune action possible via ces routes)
    @app.get("/api/state")
    def state():
        return {"now": round(time.time(), 3), "components": engine.states, "active": engine.active}

    @app.get("/api/events")
    def events(limit: int = 100):
        return list(engine.events)[-max(1, min(limit, 500)):]

    @app.get("/api/incidents")
    def incidents():
        return sorted(engine.incidents.values(), key=lambda i: i["started"], reverse=True)[:50]

    return app


app = create_app() if os.getenv("ORCH_AUTOSTART", "1") == "1" else None
