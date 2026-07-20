import logging
import re
import httpx

from typing import Any, Literal

from src.integrations.amocrm.cfg import AmoCfg
from src.integrations.amocrm.lead import Lead
from src.integrations.amocrm.statuses import WonStatuses, LossStatuses


class AsyncAmoCRM:
    def __init__(self, config: AmoCfg = AmoCfg()):
        self.__config = config
        self.__client: httpx.AsyncClient | None = None
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

    def api_url(self, path: str) -> str: return f"{self.__config.base_url.rstrip('/')}{path}"
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

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        if not self.__config.access_token:
            raise RuntimeError("Missing AMOCRM_ACCESS_TOKEN")
        headers = kwargs.pop("headers", {})
        headers = {**headers, **self.__auth_headers()}
        url = self.api_url(path)
        client = await self.__get_client()
        self.__logger.debug("HTTP %s %s | params=%s", method, path, kwargs.get("params"))
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
