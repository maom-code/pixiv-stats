"""
pixiv_stats.py
Pixivの自分の全作品統計 + フォロワー数を日次でCSVに保存する。
- ログイン: Playwright (headless=False)
- データ取得: requests + Pixiv Ajax API
"""
from __future__ import annotations
import json
import csv
import re
import sys
import time
from datetime import datetime, date
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR   = Path(__file__).parent
CONFIG       = json.loads((SCRIPT_DIR / "config.json").read_text(encoding="utf-8"))
DATA_DIR     = SCRIPT_DIR / CONFIG["data_dir"]
SESSION_FILE = SCRIPT_DIR / "session.json"
DATA_DIR.mkdir(exist_ok=True)

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://www.pixiv.net/",
}


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------

def do_login() -> tuple[dict, str]:
    """Playwrightでログインしてcookiesとuser_idを返す (headless=False で bot検知回避)"""
    print("ログイン中... (ブラウザウィンドウが開きます)")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        page = browser.new_page()
        page.goto("https://accounts.pixiv.net/login", wait_until="networkidle")
        page.fill('input[autocomplete*="username"]', CONFIG["username"])
        page.fill('input[autocomplete*="current-password"]', CONFIG["password"])
        page.click('button:has-text("ログイン")')
        for _ in range(120):
            page.wait_for_timeout(1000)
            if "accounts.pixiv.net" not in page.url:
                break

        if "accounts.pixiv.net" in page.url:
            browser.close()
            raise RuntimeError("ログイン失敗。username/passwordを確認してください。")

        page.wait_for_timeout(2000)
        html    = page.content()
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        browser.close()

    m = re.search(r'"userId":"(\d+)"', html)
    if not m:
        raise RuntimeError("userIdが取得できませんでした")
    user_id = m.group(1)

    SESSION_FILE.write_text(
        json.dumps({"cookies": cookies, "user_id": user_id}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"ログイン完了 (userId={user_id})")
    return cookies, user_id


def load_session() -> tuple[dict, str] | None:
    if not SESSION_FILE.exists():
        return None
    data    = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    cookies = data.get("cookies", {})
    user_id = data.get("user_id", "")
    r = requests.get(
        f"https://www.pixiv.net/ajax/user/{user_id}/profile/all",
        headers={**HEADERS_BASE, "x-user-id": user_id},
        cookies=cookies,
        timeout=10,
    )
    if r.status_code == 200 and not r.json().get("error"):
        print(f"セッション復元OK (userId={user_id})")
        return cookies, user_id
    return None


def get_session() -> tuple[dict, str]:
    session = load_session()
    if session:
        return session
    return do_login()


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

def get_follower_count(user_id: str, cookies: dict) -> int:
    r = requests.get(
        f"https://www.pixiv.net/ajax/user/{user_id}/followers?offset=0&limit=1&rest=show",
        headers={**HEADERS_BASE, "x-user-id": user_id},
        cookies=cookies,
        timeout=10,
    )
    return r.json().get("body", {}).get("total", 0)


def get_all_illust_ids(user_id: str, cookies: dict) -> list[str]:
    r = requests.get(
        f"https://www.pixiv.net/ajax/user/{user_id}/profile/all",
        headers={**HEADERS_BASE, "x-user-id": user_id},
        cookies=cookies,
        timeout=10,
    )
    return list(r.json().get("body", {}).get("illusts", {}).keys())


def get_illust_stats(illust_id: str, user_id: str, cookies: dict) -> dict:
    r = requests.get(
        f"https://www.pixiv.net/ajax/illust/{illust_id}",
        headers={**HEADERS_BASE, "x-user-id": user_id},
        cookies=cookies,
        timeout=10,
    )
    body = r.json().get("body", {})
    return {
        "illust_id":  illust_id,
        "title":      body.get("illustTitle", ""),
        "create_date": body.get("createDate", "")[:10],
        "page_count": body.get("pageCount", 0),
        "views":      body.get("viewCount", 0),
        "bookmarks":  body.get("bookmarkCount", 0),
        "likes":      body.get("likeCount", 0),
        "comments":   body.get("commentCount", 0),
    }


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def already_collected_today(today_str: str) -> bool:
    """同日データが既にあるか確認"""
    csv_path = DATA_DIR / f"stats_{today_str}.csv"
    if not csv_path.exists():
        return False
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            return True  # 1行でもあれば収集済み
    return False


def save_stats_csv(rows: list[dict], timestamp: str) -> Path:
    today    = timestamp[:10]
    csv_path = DATA_DIR / f"stats_{today}.csv"
    fieldnames = ["timestamp", "illust_id", "title", "create_date",
                  "page_count", "views", "bookmarks", "likes", "comments"]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        for row in rows:
            w.writerow({"timestamp": timestamp, **row})
    return csv_path


def save_followers_csv(followers: int, timestamp: str) -> Path:
    csv_path   = DATA_DIR / "followers.csv"
    fieldnames = ["date", "followers"]
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow({"date": timestamp[:10], "followers": followers})
    return csv_path


# ---------------------------------------------------------------------------
# サマリ表示
# ---------------------------------------------------------------------------

def print_summary(rows: list[dict], followers: int):
    print(f"\n{'='*52}")
    print(f"フォロワー数: {followers:,}")
    print(f"{'作品タイトル':<25} {'閲覧':>6} {'BM':>5} {'♥':>5} {'コメ':>4}")
    print("-" * 52)
    for r in sorted(rows, key=lambda x: x["bookmarks"], reverse=True):
        title = r["title"][:23]
        print(f"{title:<25} {r['views']:>6} {r['bookmarks']:>5} {r['likes']:>5} {r['comments']:>4}")
    print("=" * 52)
    print(f"合計: 閲覧={sum(r['views'] for r in rows):,}  "
          f"BM={sum(r['bookmarks'] for r in rows):,}  "
          f"♥={sum(r['likes'] for r in rows):,}")


# ---------------------------------------------------------------------------

def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = timestamp[:10]
    print(f"[{timestamp}] Pixiv統計取得開始")

    if already_collected_today(today_str):
        print(f"本日({today_str})のデータは既に収集済みです。スキップします。")
        print("強制再収集する場合は data/stats_{today}.csv を削除してください。")
        return

    cookies, user_id = get_session()

    followers = get_follower_count(user_id, cookies)
    print(f"フォロワー数: {followers:,}")

    illust_ids = get_all_illust_ids(user_id, cookies)
    print(f"作品数: {len(illust_ids)}")

    rows = []
    for i, iid in enumerate(illust_ids, 1):
        stats = get_illust_stats(iid, user_id, cookies)
        rows.append(stats)
        print(f"  [{i}/{len(illust_ids)}] {stats['title'][:30]} 閲覧={stats['views']} BM={stats['bookmarks']}")
        time.sleep(0.3)

    stats_path = save_stats_csv(rows, timestamp)
    followers_path = save_followers_csv(followers, timestamp)
    print(f"\n作品統計CSV: {stats_path}")
    print(f"フォロワーCSV: {followers_path}")
    print_summary(rows, followers)


if __name__ == "__main__":
    main()
