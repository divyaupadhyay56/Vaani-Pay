
import json

import httpx
import pytest

from app.tabby_client import TabbyAPIError, TabbyClient

PUBLIC_KEY = "pk_test_dummy"
SECRET_KEY = "sk_test_dummy"
MERCHANT_CODE = "xx"


def make_client(handler):
    """Builds a TabbyClient whose internal httpx.Client uses a mock transport."""
    client = TabbyClient(public_key=PUBLIC_KEY, secret_key=SECRET_KEY, merchant_code=MERCHANT_CODE)
    client._client = httpx.Client(base_url=client.base_url, transport=httpx.MockTransport(handler))
    return client


def json_response(status_code: int, body: dict):
    return httpx.Response(status_code, json=body)


def test_create_checkout_session_uses_public_key_and_correct_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return json_response(200, {"id": "sess_123", "status": "created"})

    client = make_client(handler)
    payment = {"amount": "100", "currency": "AED", "description": "test", "buyer": {"phone": "500000001"}}
    result = client.create_checkout_session(payment, lang="en", merchant_urls={"success": "https://x.test"})

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v2/checkout"
    assert captured["auth"] == f"Bearer {PUBLIC_KEY}"  # per the collection: checkout uses the PUBLIC key
    assert captured["body"]["payment"] == payment
    assert captured["body"]["merchant_code"] == MERCHANT_CODE
    assert captured["body"]["lang"] == "en"
    assert captured["body"]["merchant_urls"] == {"success": "https://x.test"}
    assert result["id"] == "sess_123"


def test_create_checkout_session_merchant_code_override():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return json_response(200, {})

    client = make_client(handler)
    client.create_checkout_session({"amount": "1"}, merchant_code="other_code")
    assert captured["body"]["merchant_code"] == "other_code"



def test_get_payment_uses_secret_key():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        return json_response(200, {"id": "pay_1", "status": "AUTHORIZED"})

    client = make_client(handler)
    result = client.get_payment("pay_1")

    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v2/payments/pay_1"
    assert captured["auth"] == f"Bearer {SECRET_KEY}"
    assert result["status"] == "AUTHORIZED"


def test_update_payment_body_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return json_response(200, {"id": "pay_1"})

    client = make_client(handler)
    client.update_payment("pay_1", "ORDER-42")

    assert captured["method"] == "PUT"
    assert captured["path"] == "/api/v2/payments/pay_1"
    assert captured["body"] == {"order": {"reference_id": "ORDER-42"}}


def test_capture_payment_body_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return json_response(200, {"status": "CLOSED"})

    client = make_client(handler)
    client.capture_payment("pay_1", "100.00")

    assert captured["path"] == "/api/v2/payments/pay_1/captures"
    assert captured["body"] == {"amount": "100.00"}


def test_close_payment_no_body_required():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        return json_response(200, {"status": "CLOSED"})

    client = make_client(handler)
    client.close_payment("pay_1")

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v2/payments/pay_1/close"


def test_refund_payment_body_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return json_response(200, {"status": "REFUNDED"})

    client = make_client(handler)
    client.refund_payment("pay_1", "100")

    assert captured["path"] == "/api/v2/payments/pay_1/refunds"
    assert captured["body"] == {"amount": "100"}


def test_list_payments_query_params():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return json_response(200, {"results": []})

    client = make_client(handler)
    client.list_payments(created_at_gte="2026-01-01", created_at_lte="2026-02-01", limit=10, offset=0)

    assert captured["path"] == "/api/v2/payments"
    assert captured["params"] == {
        "created_at__gte": "2026-01-01", "created_at__lte": "2026-02-01", "limit": "10", "offset": "0",
    }


def test_list_payments_no_params_when_omitted():
    captured = {}

    def handler(request: httpx.Request):
        captured["params"] = dict(request.url.params)
        return json_response(200, {"results": []})

    client = make_client(handler)
    client.list_payments()
    assert captured["params"] == {}



def test_register_webhook_sends_merchant_code_header_and_body():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["merchant_code_header"] = request.headers.get("x-merchant-code")
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return json_response(201, {"id": "wh_1", "url": "https://x.test/webhook"})

    client = make_client(handler)
    result = client.register_webhook("https://x.test/webhook", is_test=True, header={"title": "X-Test", "value": "1"})

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/webhooks"
    assert captured["merchant_code_header"] == MERCHANT_CODE
    assert captured["auth"] == f"Bearer {SECRET_KEY}"
    assert captured["body"] == {"url": "https://x.test/webhook", "is_test": True, "header": {"title": "X-Test", "value": "1"}}
    assert result["id"] == "wh_1"


def test_register_webhook_without_optional_header_field():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return json_response(201, {"id": "wh_1"})

    client = make_client(handler)
    client.register_webhook("https://x.test/webhook", is_test=False)
    assert captured["body"] == {"url": "https://x.test/webhook", "is_test": False}
    assert "header" not in captured["body"]


def test_list_webhooks():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["merchant_code_header"] = request.headers.get("x-merchant-code")
        return json_response(200, {"results": []})

    client = make_client(handler)
    client.list_webhooks()
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/webhooks"
    assert captured["merchant_code_header"] == MERCHANT_CODE


def test_get_webhook():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        return json_response(200, {"id": "wh_1"})

    client = make_client(handler)
    client.get_webhook("wh_1")
    assert captured["path"] == "/api/v1/webhooks/wh_1"


def test_update_webhook_partial_body():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return json_response(200, {"id": "wh_1"})

    client = make_client(handler)
    client.update_webhook("wh_1", url="https://new.test/webhook")

    assert captured["method"] == "PUT"
    assert captured["path"] == "/api/v1/webhooks/wh_1"
    assert captured["body"] == {"url": "https://new.test/webhook"}  # is_test omitted since not provided


def test_delete_webhook():
    captured = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["merchant_code_header"] = request.headers.get("x-merchant-code")
        return httpx.Response(204)

    client = make_client(handler)
    client.delete_webhook("wh_1")
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/webhooks/wh_1"
    assert captured["merchant_code_header"] == MERCHANT_CODE



def test_error_response_raises_tabby_api_error_with_details():
    def handler(request: httpx.Request):
        return json_response(404, {"error": "payment not found"})

    client = make_client(handler)
    with pytest.raises(TabbyAPIError) as exc_info:
        client.get_payment("pay_nonexistent")

    assert exc_info.value.status_code == 404
    assert "not found" in str(exc_info.value)
    assert exc_info.value.response_body == {"error": "payment not found"}


def test_401_error_raised_for_bad_credentials():
    def handler(request: httpx.Request):
        return json_response(401, {"error": "invalid credentials"})

    client = make_client(handler)
    with pytest.raises(TabbyAPIError) as exc_info:
        client.list_payments()
    assert exc_info.value.status_code == 401


def test_credentials_never_appear_in_request_body():
    """Sanity check: secret_key must only ever go in the Authorization header, never the JSON body."""
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = json.loads(request.content) if request.content else {}
        return json_response(200, {})

    client = make_client(handler)
    client.register_webhook("https://x.test/webhook")
    body_str = json.dumps(captured["body"])
    assert SECRET_KEY not in body_str
    assert PUBLIC_KEY not in body_str
