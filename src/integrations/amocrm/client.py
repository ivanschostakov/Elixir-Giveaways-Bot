import asyncio
import logging
import re
import httpx

from typing import Any, Literal
from urllib.parse import urlparse, parse_qs
from os import environ
from dotenv import set_key

from config import ENV_FILE
from src.integrations.amocrm.cfg import AmoCfg
from src.integrations.amocrm.lead import Lead
from src.integrations.amocrm.statuses import WonStatuses, LossStatuses


class AsyncAmoCRM:
    def __init__(self, config: AmoCfg = AmoCfg()):
        self.__config = config
        self.__client: httpx.AsyncClient | None = None
        self.__refresh_lock = asyncio.Lock()
        self.__logger = logging.getLogger(self.__class__.__name__)

    @property
    def won_statuses(self) -> WonStatuses: return self.__config.won_statuses
    @property
    def loss_statuses(self) -> LossStatuses: return self.__config.loss_statuses
    @property
    def won_statuses_list(self): return self.__config.won_statuses_list
    @property
    def loss_statuses_list(self): return self.__config.loss_statuses_list
    @property
    def inverted_statuses(self):
        inverted = self.won_statuses.inverted
        inverted.update(self.loss_statuses.inverted)
        return inverted

    def token_url(self) -> str: return f"https://{self.__config.base_domain}/oauth2/access_token"
    def api_url(self, path: str) -> str: return f"https://{self.__config.base_domain}{path}"
    def __auth_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.__config.access_token: h["Authorization"] = f"Bearer {self.__config.access_token}"
        return h

    async def __get_client(self) -> httpx.AsyncClient:
        if self.__client is None:
            self.__logger.info("Creating shared httpx.AsyncClient (timeout=%s)", self.__config.timeout)
            self.__client = httpx.AsyncClient(timeout=self.__config.timeout)
        return self.__client

    async def aclose(self) -> None:
        if self.__client is None: return
        self.__logger.info("Closing shared httpx.AsyncClient")
        await self.__client.aclose()
        self.__client = None

    def __save_credentials_to_env(self, access_token: str | None, refresh_token: str | None) -> None:
        env_file = str(ENV_FILE)
        updated_keys: list[str] = []

        def _save(key: str, value: str | None) -> None:
            if not value:
                return
            try:
                set_key(env_file, key, value)
                environ[key] = value
                updated_keys.append(key)
            except Exception as e:
                self.__logger.error("Failed to save %s to ENV_FILE: %s", key, e)

        _save("AMOCRM_ACCESS_TOKEN", access_token)
        _save("AMOCRM_REFRESH_TOKEN", refresh_token)

        if updated_keys:
            self.__logger.info("Saved amoCRM credentials to ENV_FILE")
        else:
            self.__logger.warning("Token response did not contain new credentials to save")

    async def __request_token(self, grant_type: str, *, code: str | None = None) -> None:
        cfg = self.__config
        payload: dict[str, Any] = {
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "redirect_uri": cfg.redirect_uri,
            "grant_type": grant_type,
        }
        if grant_type == "authorization_code":
            if not code: raise RuntimeError("No authorization code provided.")
            payload["code"] = code

        elif grant_type == "refresh_token":
            if not cfg.refresh_token: raise RuntimeError("No refresh_token; cannot refresh.")
            payload["refresh_token"] = cfg.refresh_token

        else: raise ValueError(f"Unknown grant_type={grant_type!r}")

        client = await self.__get_client()
        r = await client.post(self.token_url(), json=payload)
        if r.status_code != 200: self.__logger.error("Token request failed: grant_type=%s status=%s body=%r", grant_type, r.status_code, (r.text or "")[:500])
        r.raise_for_status()
        data = r.json()

        cfg.access_token = data.get("access_token")
        cfg.refresh_token = data.get("refresh_token")
        self.__save_credentials_to_env(cfg.access_token, cfg.refresh_token)
        self.__logger.info("Tokens updated (grant_type=%s)", grant_type)

    async def __get_new_auth_code(self) -> str:
        cfg = self.__config
        login_email = getattr(cfg, "login_email", None)
        login_password = getattr(cfg, "login_password", None)
        account_id = getattr(cfg, "account_id", None)
        headless = bool(getattr(cfg, "playwright_headless", True))

        if not login_email or not login_password or not account_id: raise RuntimeError("Playwright auth requires cfg.login_email, cfg.login_password, cfg.account_id")
        auth_url = f"https://www.amocrm.ru/oauth?client_id={cfg.client_id}&redirect_uri={cfg.redirect_uri}&response_type=code"
        self.__logger.warning("Launching Playwright to obtain new AUTH_CODE (headless=%s)", headless)

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()
            await page.goto(auth_url)

            try:
                await page.wait_for_selector('input[name="username"]', timeout=7000)
                await page.fill('input[name="username"]', login_email)
                await page.fill('input[name="password"]', login_password)
                await page.click('button[type="submit"]')
                self.__logger.info("Logged into amoCRM")
            except Exception: self.__logger.info("Login form not shown (maybe already logged in)")

            await page.wait_for_selector("select.js-accounts-list", timeout=20000)
            await page.select_option("select.js-accounts-list", value=str(account_id))
            await page.click("button.js-accept")
            self.__logger.info("Account selected + accepted")
            await page.wait_for_url(f"{cfg.redirect_uri}*", timeout=30000)
            final_url = page.url
            await browser.close()

        code = parse_qs(urlparse(final_url).query).get("code", [None])[0]
        if not code: raise RuntimeError("Failed to extract AUTH_CODE from redirect URL.")
        self.__logger.info("Got new AUTH_CODE")
        return code

    async def authorize(self) -> None:
        code = await self.__get_new_auth_code()
        await self.__request_token("authorization_code", code=code)

    async def _refresh_tokens(self) -> None:
        async with self.__refresh_lock:
            self.__logger.info("Refreshing amoCRM token...")
            try:
                await self.__request_token("refresh_token")
                self.__logger.info("Token refreshed successfully")
                return
            except Exception as e: self.__logger.error("Refresh failed: %s", e)

            self.__logger.warning("Falling back to Playwright authorization...")
            await self.authorize()
            self.__logger.info("Re-authorized successfully (Playwright)")

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers = {**headers, **self.__auth_headers()}
        url = self.api_url(path)
        client = await self.__get_client()
        self.__logger.debug("HTTP %s %s | params=%s", method, path, kwargs.get("params"))
        r = await client.request(method, url, headers=headers, **kwargs)
        if r.status_code == 401:
            self.__logger.warning("401 Unauthorized for %s %s, refreshing/reauthorizing and retrying once", method, path)
            await self._refresh_tokens()
            headers = {**headers, **self.__auth_headers()}
            r = await client.request(method, url, headers=headers, **kwargs)

        if r.status_code >= 400: self.__logger.error("HTTP error %s for %s %s | body=%r", r.status_code, method, path, (r.text or "")[:500])
        r.raise_for_status()
        return r.json() if (r.text or "").strip() else {}

    async def get(self, path: str, **kwargs) -> dict[str, Any]:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> dict[str, Any]:
        return await self._request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs) -> dict[str, Any]:
        return await self._request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> dict[str, Any]:
        return await self._request("DELETE", path, **kwargs)

    async def get_lead(self, order_code: str | int, source: Literal["telegram", "website"] | None = None) -> Lead | None:
        cfg = self.__config
        code_str = str(order_code).strip()
        needle = f"Заказ №{code_str} "
        rx = re.compile(rf"Заказ №{re.escape(code_str)}\s")
        expected_name_suffix = None
        if source == "telegram": expected_name_suffix = "с Приложения ТГ"
        elif source == "website": expected_name_suffix = "Новый сайт"
        self.__logger.info("Searching lead | order_code=%s | pipeline_id=%s | source=%s", code_str, cfg.pipeline_id, source)
        for page in range(1, cfg.max_pages + 1):
            self.__logger.debug("Lead search page=%d/%d | needle=%r", page, cfg.max_pages, needle)
            data = await self.get("/api/v4/leads", params={"query": needle, "limit": cfg.limit, "page": page, "with": "contacts"})

            leads = ((data.get("_embedded") or {}).get("leads") or [])
            if not leads:
                self.__logger.info("No leads on page=%d (stop searching)", page)
                break

            for lead in leads:
                name = lead.get("name") or ""
                if not rx.search(name): continue
                if expected_name_suffix and not name.rstrip().endswith(expected_name_suffix): continue
                if cfg.pipeline_id is not None and lead.get("pipeline_id") != cfg.pipeline_id: continue
                lead_id = lead.get("id")
                status_id = lead.get("status_id")
                self.__logger.info("Lead found | lead_id=%s | status_id=%s | name=%r", lead_id, status_id, name)
                emb = lead.setdefault("_embedded", {})
                contacts = emb.get("contacts") or []
                if not isinstance(contacts, list): contacts = []
                emb["contacts"] = contacts
                main_contact: dict[str, Any] | None = None
                for c in contacts:
                    if isinstance(c, dict) and c.get("is_main"):
                        main_contact = c
                        break

                if main_contact is None: main_contact = contacts[0] if contacts else None
                if isinstance(main_contact, dict):
                    cid = main_contact.get("id")
                    if cid and not main_contact.get("custom_fields_values"):
                        self.__logger.info("Fetching full contact for lead | contact_id=%s", cid)
                        contact = await self.get(f"/api/v4/contacts/{cid}")
                        emb["contacts"] = [contact]

                return Lead.from_dict(lead)

        self.__logger.warning("Lead not found | order_code=%s", code_str)
        raise LookupError(f"Lead not found for order_code={code_str!r}")

    def is_won_status(self, status_id: int | None) -> bool: return bool(status_id and status_id in self.won_statuses_list)
    def is_loss_status(self, status_id: int | None) -> bool: return bool(status_id and status_id in self.loss_statuses_list)
    def get_status_name(self, status_id: int) -> str: return self.inverted_statuses.get(status_id, None)

async def main() -> None:
    client = AsyncAmoCRM()
    result = await client.get_lead("30-4M8WI")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
