"""個別作品APIと管理ページAPIで統計フィールドを確認する"""
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright
import requests

cfg = json.loads(Path(r"C:\Users\kniiy\Desktop\pixiv_stats\config.json").read_text(encoding="utf-8"))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://accounts.pixiv.net/login", wait_until="networkidle")
    page.fill('input[autocomplete*="username"]', cfg["username"])
    page.fill('input[autocomplete*="current-password"]', cfg["password"])
    with page.expect_navigation(timeout=30000):
        page.click('button:has-text("ログイン")')
    page.wait_for_timeout(2000)
    html = page.content()
    m = re.search(r'"userId":"(\d+)"', html)
    user_id = m.group(1) if m else None
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    browser.close()

print("userID:", user_id)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.pixiv.net/",
    "x-user-id": user_id,
}

# 全作品ID取得
r = requests.get(f"https://www.pixiv.net/ajax/user/{user_id}/profile/all", headers=headers, cookies=cookies)
illust_ids = list(r.json().get("body", {}).get("illusts", {}).keys())
print(f"作品数: {len(illust_ids)}, IDs: {illust_ids[:3]}")

# 個別作品エンドポイントの統計確認
test_id = illust_ids[0]
r2 = requests.get(f"https://www.pixiv.net/ajax/illust/{test_id}", headers=headers, cookies=cookies)
body = r2.json().get("body", {})
print(f"\n=== /ajax/illust/{test_id} の統計系フィールド ===")
for k, v in body.items():
    if any(word in k.lower() for word in ["count", "view", "book", "like", "comment", "stat"]):
        print(f"  {k}: {v}")

# 管理ページが使うAPIを探す（ネットワーク傍受）
print("\n=== /ajax/user/{id}/works/latest を試す ===")
r3 = requests.get(f"https://www.pixiv.net/ajax/user/{user_id}/works/latest", headers=headers, cookies=cookies)
print("status:", r3.status_code)
if r3.status_code == 200:
    b3 = r3.json().get("body", {})
    first = next(iter(b3.values()), {}) if b3 else {}
    for k, v in first.items():
        if not isinstance(v, (dict, list)):
            print(f"  {k}: {v}")
