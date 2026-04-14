import json
import httpx

from datetime import datetime
from typing import Optional, Any

from config import BITRIX24_BASE_URL, BITRIX24_ENDPOINT, BITRIX24_TOKEN
from src.integrations.bitrix24.exceptions import BitrixAPIError
from src.integrations.bitrix24.review import Review


class AsyncBitrix24:
    def __init__(self, base_url: str = BITRIX24_BASE_URL, token: str = BITRIX24_TOKEN, timeout: float = 20.0, endpoint: str = BITRIX24_ENDPOINT):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        self._client: Optional[httpx.AsyncClient] = None

    async def __aexit__(self, exc_type, exc, tb) -> None: await self.close()
    async def __aenter__(self) -> "AsyncBitrix24":
        await self.open()
        return self

    async def open(self) -> None: self._client = self._client or httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers={"Content-Type": "application/json", "Accept": "application/json"}, follow_redirects=True)
    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None: raise RuntimeError("AsyncBitrix24 client is not opened. Use `async with` or call `open()`.")
        return self._client

    @staticmethod
    def _response_payload(res: httpx.Response, text: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "cmd": body.get("cmd"),
            "content_type": res.headers.get("content-type"),
            "status": res.status_code,
            "url": str(res.request.url),
            "text": text[:800],
        }

    async def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        client = self._require_client()
        try:
            res = await client.post(self.endpoint, json=body)
        except httpx.HTTPError as exc:
            raise BitrixAPIError(
                status_code=503,
                error="request_failed",
                payload={
                    "cmd": body.get("cmd"),
                    "url": f"{self.base_url}{self.endpoint}",
                    "message": str(exc),
                },
            ) from exc

        text = (res.text or "").strip()
        if not text:
            raise BitrixAPIError(status_code=res.status_code, error="empty_response", payload=self._response_payload(res, text, body))

        content_type = (res.headers.get("content-type") or "").lower()
        looks_like_json = "json" in content_type or text.startswith("{") or text.startswith("[")
        if not looks_like_json:
            error = "endpoint_not_found" if res.status_code == 404 else "unexpected_content_type"
            raise BitrixAPIError(status_code=res.status_code, error=error, payload=self._response_payload(res, text, body))

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            error = "endpoint_not_found" if res.status_code == 404 else "invalid_json"
            raise BitrixAPIError(status_code=res.status_code, error=error, payload=self._response_payload(res, text, body))

        if not isinstance(data, dict) or "ok" not in data:
            raise BitrixAPIError(status_code=res.status_code, error="bad_response_shape", payload={"data": data, **self._response_payload(res, text, body)})
        if data.get("ok"): return data
        raise BitrixAPIError(status_code=res.status_code, error=str(data.get("error") or "unknown_error"), payload=data)

    async def get_user_id_by_email(self, email: str) -> int:
        data = await self._post_json({"token": self.token,"cmd": "get_user_id", "email": email})
        user_id = data.get("user_id")
        if not isinstance(user_id, int): raise BitrixAPIError(status_code=200, error="missing_user_id", payload=data)
        return user_id

    async def find_reviews(self, user_id: int, start_date: datetime, min_grade: int, min_length: int) -> list[Review]:
        if not isinstance(user_id, int) or user_id <= 0: raise TypeError("user_id must be int > 0")
        start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S")
        if min_grade < 0: min_grade = 0
        elif min_grade > 5: min_grade = 5
        payload = {"token": self.token, "cmd": "find_review", "user_id": int(user_id), "start_date": start_date_str, "min_grade": int(min_grade), "min_length": int(min_length), "limit": int(5)}
        data = await self._post_json(payload)
        reviews = data.get("reviews")
        if not isinstance(reviews, list): raise BitrixAPIError(status_code=200, error="missing_reviews", payload=data)
        reviews = [Review.from_dict(r) for r in reviews if isinstance(r, dict)]
        return [r for r in reviews if r.length >= min_length]


bitrix24 = AsyncBitrix24()
