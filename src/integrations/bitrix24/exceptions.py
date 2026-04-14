from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BitrixAPIError(Exception):
    status_code: int
    error: str
    payload: dict[str, Any] | None = None

    def __str__(self) -> str: return f"BitrixAPIError(status={self.status_code}, error={self.error})"
