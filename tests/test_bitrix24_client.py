import unittest

import httpx

from src.integrations.bitrix24.client import AsyncBitrix24


class AsyncBitrix24RedirectTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_redirect_keeps_post_method(self) -> None:
        requests: list[tuple[str, str, bytes]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = await request.aread()
            requests.append((request.method, str(request.url), body))
            if str(request.url) == "https://elixirpeptide.ru/local/api/giveaways.php":
                return httpx.Response(
                    301,
                    headers={"location": "https://elixirpeptide.com/local/api/giveaways.php"},
                    request=request,
                )

            self.assertEqual(str(request.url), "https://elixirpeptide.com/local/api/giveaways.php")
            self.assertEqual(request.method, "POST")
            return httpx.Response(200, json={"ok": True, "user_id": 321}, request=request)

        client = AsyncBitrix24(base_url="https://elixirpeptide.ru", token="secret", endpoint="/local/api/giveaways.php")
        client._client = httpx.AsyncClient(
            base_url=client.base_url,
            timeout=client.timeout,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            follow_redirects=False,
            transport=httpx.MockTransport(handler),
        )
        try:
            user_id = await client.get_user_id_by_email("user@example.com")
        finally:
            await client.close()

        self.assertEqual(user_id, 321)
        self.assertEqual(
            [(method, url) for method, url, _ in requests],
            [
                ("POST", "https://elixirpeptide.ru/local/api/giveaways.php"),
                ("POST", "https://elixirpeptide.com/local/api/giveaways.php"),
            ],
        )
        self.assertEqual(requests[0][2], requests[1][2])
