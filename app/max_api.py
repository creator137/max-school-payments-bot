from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class MaxAPIError(RuntimeError):
    pass


class CursorStore(Protocol):
    async def load(self) -> int | None: ...

    async def save(self, marker: int) -> None: ...


class MaxClient:
    def __init__(self, token: str, base_url: str, verify: bool | str = True):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.verify = verify
        self.proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": token},
            verify=verify,
            timeout=httpx.Timeout(30, read=60),
            proxy=self.proxy,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        if response.is_error:
            raise MaxAPIError(f"MAX API {response.status_code}: {response.text[:300]}")
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/me")

    async def send_message(
        self,
        user_id: int,
        text: str,
        buttons: list[list[tuple[str, str]]] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if buttons:
            body["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [
                                {"type": "callback", "text": label, "payload": payload}
                                for label, payload in row
                            ]
                            for row in buttons
                        ]
                    },
                }
            ]
        return await self._request("POST", "/messages", params={"user_id": user_id}, json=body)

    async def answer_callback(self, callback_id: str, notification: str) -> None:
        await self._request(
            "POST",
            "/answers",
            params={"callback_id": callback_id},
            json={"notification": notification},
        )

    async def download(self, url: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(
            verify=self.verify, timeout=60, proxy=self.proxy, trust_env=False
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content, response.headers.get("content-type")

    async def send_file(
        self, user_id: int, path: Path, *, media_type: str = "file", caption: str = ""
    ) -> None:
        upload = await self._request("POST", "/uploads", params={"type": media_type})
        upload_url = upload["url"]
        async with httpx.AsyncClient(
            proxy=self.proxy, timeout=120, trust_env=False
        ) as upload_client:
            with path.open("rb") as stream:
                response = await upload_client.post(
                    upload_url, files={"data": (path.name, stream, "application/octet-stream")}
                )
            response.raise_for_status()
            result = response.json()
        token = result.get("token") or upload.get("token")
        if not token:
            raise MaxAPIError("MAX upload did not return attachment token")
        await self._request(
            "POST",
            "/messages",
            params={"user_id": user_id},
            json={
                "text": caption,
                "attachments": [{"type": media_type, "payload": {"token": token}}],
            },
        )

    async def get_updates(self, marker: int | None = None, timeout: int = 30) -> dict[str, Any]:
        params: dict[str, Any] = {
            "timeout": timeout,
            "types": "message_created,message_callback,bot_started",
        }
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def subscribe(self, url: str, secret: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/subscriptions",
            json={
                "url": url,
                "update_types": ["message_created", "message_callback", "bot_started"],
                "secret": secret,
            },
        )


async def poll_forever(
    handler: Any, client: MaxClient, cursor_store: CursorStore | None = None
) -> None:
    marker = await cursor_store.load() if cursor_store else None
    while True:
        try:
            result = await client.get_updates(marker)
            for update in result.get("updates", []):
                try:
                    await handler.handle(update)
                except Exception:
                    logger.exception(
                        "Failed to process MAX update type=%s", update.get("update_type")
                    )
            next_marker = result.get("marker")
            if next_marker is not None:
                marker = int(next_marker)
                if cursor_store:
                    await cursor_store.save(marker)
        except Exception:
            logger.exception("MAX polling iteration failed")
            await asyncio.sleep(3)
