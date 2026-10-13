import httpx
from urllib.parse import quote


class ToolClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def _get(self, path: str) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base_url}{path}", headers=headers)
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool) or not isinstance(result.get("data"), dict):
            raise ValueError("Invalid Tool Result")
        return result

    async def get_product(self, product_id: str) -> dict:
        return await self._get(f"/internal/v1/tools/products/{quote(product_id, safe='')}")

    async def get_product_stock(self, product_id: str) -> dict:
        return await self._get(f"/internal/v1/tools/products/{quote(product_id, safe='')}/stock")

    async def get_product_price(self, product_id: str) -> dict:
        return await self._get(f"/internal/v1/tools/products/{quote(product_id, safe='')}/price")
