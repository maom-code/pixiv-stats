import json
from pathlib import Path
from playwright.sync_api import sync_playwright

cfg = json.loads(Path(r"C:\Users\kniiy\Desktop\pixiv_stats\config.json").read_text(encoding="utf-8"))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://accounts.pixiv.net/login", wait_until="networkidle")
    page.fill('input[autocomplete*="username"]', cfg["username"])
    page.fill('input[autocomplete*="current-password"]', cfg["password"])
    page.click('button:has-text("ログイン")')
    page.wait_for_timeout(8000)
    print("URL:", page.url)
    page.screenshot(path=r"C:\Users\kniiy\Desktop\pixiv_login_debug.png")
    browser.close()
