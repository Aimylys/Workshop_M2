"""Accès à l'API Docker UNIQUEMENT via le proxy à droits limités (jamais le socket directement).
Le proxy autorise : lister/inspecter les conteneurs, et stop/restart/kill (ALLOW_RESTARTS)."""
import json

import httpx


class DockerAPI:
    def __init__(self, host: str, project: str):
        self.client = httpx.Client(base_url=host.replace("tcp://", "http://"), timeout=70)
        self.project = project

    def _find(self, service: str):
        filters = {
            "label": [
                f"com.docker.compose.service={service}",
                f"com.docker.compose.project={self.project}",
            ]
        }
        r = self.client.get("/containers/json", params={"all": "true", "filters": json.dumps(filters)})
        r.raise_for_status()
        items = r.json()
        return items[0]["Id"] if items else None

    def state(self, service: str) -> dict:
        cid = self._find(service)
        if not cid:
            return {"present": False}
        r = self.client.get(f"/containers/{cid}/json")
        r.raise_for_status()
        st = r.json()["State"]
        return {
            "present": True,
            "status": st.get("Status"),
            "health": (st.get("Health") or {}).get("Status"),
        }

    def restart(self, service: str) -> None:
        cid = self._find(service)
        if not cid:
            raise LookupError(f"conteneur introuvable : {service}")
        self.client.post(f"/containers/{cid}/restart", params={"t": 5}).raise_for_status()

    def signal(self, service: str, sig: str) -> None:
        cid = self._find(service)
        if not cid:
            raise LookupError(f"conteneur introuvable : {service}")
        self.client.post(f"/containers/{cid}/kill", params={"signal": sig}).raise_for_status()
