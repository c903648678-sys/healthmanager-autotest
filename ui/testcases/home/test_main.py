import json
import os
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.mark.smoke
def test_configured_homepage():
    config = json.loads((Path(__file__).resolve().parents[3] / "config.local.json").read_text(encoding="utf-8"))
    assert config["base_url"] and config["expected_title"], "UI config is incomplete"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.getenv("HM_HEADED") != "1")
        try:
            page = browser.new_page()
            response = page.goto(config["base_url"], wait_until="domcontentloaded")
            assert response is not None and response.ok
            expect(page).to_have_title(config["expected_title"])
        finally:
            browser.close()
