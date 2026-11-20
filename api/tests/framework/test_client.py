import httpx
import pytest
from healthmanager_api.client import ApiClient


def test_status_is_preserved_and_token_is_forwarded():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(403, json={"error": "denied"})
    client = ApiClient("https://example.invalid", "synthetic", httpx.MockTransport(handler))
    try:
        assert client.get("/health").status_code == 403
        assert requests[0].headers["Authorization"] == "Bearer synthetic"
        assert len(requests) == 1
        with pytest.raises(ValueError):
            client.get("https://other.invalid")
    finally:
        client.close()
