import httpx


class ApiClient:
    """No implicit retries or response-body logging."""

    def __init__(self, base_url, token=None, transport=None):
        self.client = httpx.Client(
            base_url=base_url, timeout=20, follow_redirects=False,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            transport=transport,
        )

    def get(self, path):
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ValueError("Use an origin-relative API path")
        return self.client.get(path)

    def close(self):
        self.client.close()
