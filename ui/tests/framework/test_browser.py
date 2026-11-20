from playwright.sync_api import sync_playwright, expect


def test_browser_runtime():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content('<title>Framework check</title><button>Ready</button>')
            expect(page.get_by_role("button", name="Ready")).to_be_visible()
            expect(page).to_have_title("Framework check")
        finally:
            browser.close()
