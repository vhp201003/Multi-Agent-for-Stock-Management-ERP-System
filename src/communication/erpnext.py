import logging
from typing import Any, Dict, Optional

import httpx

from config.settings import get_erpnext_api_key, get_erpnext_api_secret, get_erpnext_url

logger = logging.getLogger(__name__)

_erpnext_instance: Optional["ERPNextConnectionManager"] = None
_lock = __import__("threading").Lock()


def get_erpnext_connection():
    global _erpnext_instance

    if _erpnext_instance is not None:
        return _erpnext_instance

    with _lock:
        if _erpnext_instance is not None:
            return _erpnext_instance
        try:
            _erpnext_instance = ERPNextConnectionManager(
                host=get_erpnext_url(),
                api_key=get_erpnext_api_key(),
                api_secret=get_erpnext_api_secret(),
            )
            return _erpnext_instance

        except Exception as e:
            logger.error(f"ERPNext connection failed: {e}")
            _erpnext_instance = None
            raise


class ERPNextConnectionManager:
    def __init__(self, host: str, api_key: str, api_secret: str):
        self.host = host.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.headers = {
            "Authorization": f"token {self.api_key}:{self.api_secret}",
            "Accept": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.host,
            headers=self.headers,
            timeout=30.0,
            verify=False,
        )

    async def health_check(self) -> bool:
        try:
            response = await self.client.get("/api/method/frappe.auth.get_logged_user")
            if response.status_code == 200:
                return True
            logger.warning(
                f"Health check failed: {response.status_code} - {response.text}"
            )
            return False
        except Exception as e:
            logger.error(f"Health check error: {e}")
            return False

    async def get_doc(self, doctype: str, name: str) -> Dict[str, Any]:
        try:
            response = await self.client.get(f"/api/resource/{doctype}/{name}")
            response.raise_for_status()
            return response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"Error fetching {doctype} {name}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching {doctype} {name}: {e}")
            raise

    async def create_doc(self, doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await self.client.post(f"/api/resource/{doctype}", json=data)
            response.raise_for_status()
            return response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"Error creating {doctype}: {e.response.text}")
            raise

    async def update_doc(
        self, doctype: str, name: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            response = await self.client.put(
                f"/api/resource/{doctype}/{name}", json=data
            )
            response.raise_for_status()
            return response.json().get("data", {})
        except httpx.HTTPStatusError as e:
            logger.error(f"Error updating {doctype} {name}: {e.response.text}")
            raise

    async def delete_doc(self, doctype: str, name: str) -> None:
        try:
            response = await self.client.delete(f"/api/resource/{doctype}/{name}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"Error deleting {doctype} {name}: {e.response.text}")
            raise

    async def get_list(
        self,
        doctype: str,
        fields: Optional[list] = None,
        filters: Optional[list] = None,
        limit_start: int = 0,
        limit_page_length: int = 20,
        order_by: Optional[str] = None,
    ) -> list:
        params = {
            "fields": str(fields) if fields else '["name"]',
            "filters": str(filters) if filters else None,
            "limit_start": limit_start,
            "limit_page_length": limit_page_length,
            "order_by": order_by,
        }
        params = {k: v for k, v in params.items() if v is not None}

        try:
            response = await self.client.get(f"/api/resource/{doctype}", params=params)
            response.raise_for_status()
            return response.json().get("data", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"Error listing {doctype}: {e.response.text}")
            raise

    async def call_method(
        self,
        method_url: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        try:
            params = params or {}
            body = body or {}
            request_kwargs = {
                "method": method,
                "url": f"/api/method/{method_url}",
                "params": params,
            }
            if method.upper() != "GET":
                request_kwargs["json"] = body

            response = await self.client.request(**request_kwargs)
            response.raise_for_status()
            return response.json().get("message")
        except httpx.HTTPStatusError as e:
            logger.error(f"Error calling method {method_url}: {e.response.text}")
            raise

    async def close(self):
        await self.client.aclose()
