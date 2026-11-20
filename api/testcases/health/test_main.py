import json
import os
from pathlib import Path
import pytest
from healthmanager_api.client import ApiClient


@pytest.mark.smoke
def test_configured_health_endpoint():
    config = json.loads((Path(__file__).resolve().parents[3] / "config.local.json").read_text(encoding="utf-8"))
    assert config["api_base_url"] and config["health_path"], "API config is incomplete"
    client = ApiClient(config["api_base_url"], os.getenv("HM_API_TOKEN"))
    try:
        assert client.get(config["health_path"]).status_code == 200
    finally:
        client.close()
