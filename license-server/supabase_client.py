import httpx
from fastapi import HTTPException


class SupabaseClient:
    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/")
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=30)

    def _url(self, table: str) -> str:
        return f"{self.base}/rest/v1/{table}"

    def _raise(self, e: httpx.HTTPError, action: str):
        msg = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                msg = e.response.text[:200]
            except Exception:
                pass
        raise HTTPException(status_code=502, detail=f"Supabase {action} thất bại: {msg}")

    def get(self, table, select="*", filters=None, order=None, limit=None):
        params = {"select": select}
        if filters:
            for k, v in filters.items():
                params[k] = v
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        try:
            r = self._client.get(self._url(table), params=params, headers=self.headers)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._raise(e, "đọc")

    def get_one(self, table, filters):
        rows = self.get(table, filters=filters, limit=1)
        return rows[0] if rows else None

    def count(self, table, filters=None):
        params = {"select": "count"}
        if filters:
            params.update(filters)
        try:
            r = self._client.get(self._url(table), params=params, headers=self.headers)
            r.raise_for_status()
            data = r.json()
            return int(data[0]["count"]) if data else 0
        except httpx.HTTPError as e:
            self._raise(e, "đếm")

    def insert(self, table, rows):
        try:
            r = self._client.post(
                self._url(table),
                json=rows,
                headers={**self.headers, "Prefer": "return=representation"},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._raise(e, "thêm")

    def update(self, table, data, filters):
        try:
            r = self._client.patch(
                self._url(table),
                params=filters,
                json=data,
                headers={**self.headers, "Prefer": "return=representation"},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._raise(e, "cập nhật")

    def delete(self, table, filters):
        try:
            r = self._client.delete(
                self._url(table),
                params=filters,
                headers={**self.headers, "Prefer": "return=representation"},
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            self._raise(e, "xóa")