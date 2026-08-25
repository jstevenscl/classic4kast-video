"""Thin generic Dispatcharr API client -- ported verbatim from VOD & DVR
Manager's dispatcharr_client.py. Already has zero hardcoded VOD-specific (or
WeatherStar-specific) paths; takes url/token per instance, so it copies over
unchanged except for the no-arg constructor fallback (VOD Manager's pointed
at its single implicit connection via config.get_config() -- this product
has no such single-connection concept, every caller here always constructs
DispatcharrClient(connection["url"], connection["token"]) from a row in the
dispatcharr_connections table, so url/token are required)."""
import logging
import httpx

logger = logging.getLogger(__name__)


class DispatcharrClient:
    def __init__(self, url: str, token: str):
        self._base    = url.rstrip("/")
        self._headers = {"X-API-Key": token}

    async def get(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(f"{self._base}{path}", headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    async def post(self, path: str, data: dict):
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{self._base}{path}", headers=self._headers, json=data)
            if not r.is_success:
                logger.error("[DispatcharrClient] POST %s -> %d: %s", path, r.status_code, r.text[:500])
            r.raise_for_status()
            return r.json()

    async def patch(self, path: str, data: dict):
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(f"{self._base}{path}", headers=self._headers, json=data)
            r.raise_for_status()
            return r.json()

    async def delete(self, path: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.delete(f"{self._base}{path}", headers=self._headers)
            r.raise_for_status()
            return r.status_code

    async def get_bytes(self, path: str) -> tuple[bytes, dict]:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(f"{self._base}{path}", headers=self._headers)
            r.raise_for_status()
            return r.content, dict(r.headers)

    async def download_bytes(self, url: str) -> tuple[bytes, dict]:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content, dict(r.headers)
