from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings


class TabbyAPIError(Exception):

    def __init__(self, status_code: int, message: str, response_body: Any = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Tabby API error {status_code}: {message}")


@dataclass
class TabbyClient:

    public_key: str = field(default_factory=lambda: settings.TABBY_PUBLIC_KEY)
    secret_key: str = field(default_factory=lambda: settings.TABBY_SECRET_KEY)
    merchant_code: str = field(default_factory=lambda: settings.TABBY_MERCHANT_CODE)
    base_url: str = field(default_factory=lambda: settings.TABBY_BASE_URL)
    timeout: float = 15.0
    _client: httpx.Client | None = field(default=None, repr=False)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, *, bearer: str, extra_headers: dict | None = None,
                 json_body: dict | None = None, params: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {bearer}"}
        if extra_headers:
            headers.update(extra_headers)

        response = self._http().request(method, path, headers=headers, json=json_body, params=params)

        try:
            body = response.json() if response.content else None
        except ValueError:
            body = response.text

        if response.status_code >= 400:
            message = body.get("error") if isinstance(body, dict) else str(body)
            raise TabbyAPIError(response.status_code, message or "request failed", body)

        return body


    def create_checkout_session(self, payment: dict, lang: str = "en", merchant_urls: dict | None = None,
                                 merchant_code: str | None = None) -> dict:
        body = {
            "payment": payment,
            "lang": lang,
            "merchant_code": merchant_code or self.merchant_code,
            "merchant_urls": merchant_urls or {},
        }
        return self._request("POST", "/api/v2/checkout", bearer=self.public_key, json_body=body)


    def get_payment(self, payment_id: str) -> dict:
        return self._request("GET", f"/api/v2/payments/{payment_id}", bearer=self.secret_key)

    def update_payment(self, payment_id: str, reference_id: str) -> dict:
        body = {"order": {"reference_id": reference_id}}
        return self._request("PUT", f"/api/v2/payments/{payment_id}", bearer=self.secret_key, json_body=body)

    def capture_payment(self, payment_id: str, amount: str) -> dict:
        body = {"amount": amount}
        return self._request("POST", f"/api/v2/payments/{payment_id}/captures", bearer=self.secret_key, json_body=body)

    def close_payment(self, payment_id: str) -> dict:
        return self._request("POST", f"/api/v2/payments/{payment_id}/close", bearer=self.secret_key)

    def refund_payment(self, payment_id: str, amount: str) -> dict:
        return self._request("POST", f"/api/v2/payments/{payment_id}/refunds", bearer=self.secret_key, json_body=body)

    def list_payments(self, created_at_gte: str | None = None, created_at_lte: str | None = None,
                       limit: int | None = None, offset: int | None = None) -> dict:
        params = {}
        if created_at_gte is not None:
            params["created_at__gte"] = created_at_gte
        if created_at_lte is not None:
            params["created_at__lte"] = created_at_lte
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._request("GET", "/api/v2/payments", bearer=self.secret_key, params=params)


    def register_webhook(self, url: str, is_test: bool = True, header: dict | None = None) -> dict:
        body: dict = {"url": url, "is_test": is_test}
        if header is not None:
            body["header"] = header
        return self._request(
            "POST", "/api/v1/webhooks", bearer=self.secret_key,
            extra_headers={"X-Merchant-Code": self.merchant_code}, json_body=body,
        )

    def list_webhooks(self) -> dict:
        """GET /api/v1/webhooks"""
        return self._request(
            "GET", "/api/v1/webhooks", bearer=self.secret_key,
            extra_headers={"X-Merchant-Code": self.merchant_code},
        )

    def get_webhook(self, webhook_id: str) -> dict:
        return self._request(
            "GET", f"/api/v1/webhooks/{webhook_id}", bearer=self.secret_key,
            extra_headers={"X-Merchant-Code": self.merchant_code},
        )

    def update_webhook(self, webhook_id: str, url: str | None = None, is_test: bool | None = None) -> dict:
        body: dict = {}
        if url is not None:
            body["url"] = url
        if is_test is not None:
            body["is_test"] = is_test
        return self._request(
            "PUT", f"/api/v1/webhooks/{webhook_id}", bearer=self.secret_key,
            extra_headers={"X-Merchant-Code": self.merchant_code}, json_body=body,
        )

    def delete_webhook(self, webhook_id: str) -> None:
        return self._request(
            "DELETE", f"/api/v1/webhooks/{webhook_id}", bearer=self.secret_key,
            extra_headers={"X-Merchant-Code": self.merchant_code},
        )
