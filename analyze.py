"""
analyze.py
収集したPixiv統計CSVを読み込んでHTMLレポートを生成し、ブラウザで表示する。
"""
from __future__ import annotations
import sys, webbrowser, textwrap, base64 as _b64
from pathlib import Path
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib import rcParams
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

rcParams["font.family"] = "MS Gothic"
rcParams["axes.unicode_minus"] = False

DATA_DIR   = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "report"
OUTPUT_DIR.mkdir(exist_ok=True)

COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
          "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------

def load_stats() -> pd.DataFrame:
    dfs = []
    for f in sorted(DATA_DIR.glob("stats_*.csv")):
        dfs.append(pd.read_csv(f, encoding="utf-8-sig", parse_dates=["timestamp"]))
    if not dfs:
        raise FileNotFoundError(f"{DATA_DIR} にstats_*.csvが見つかりません")
    df = pd.concat(dfs, ignore_index=True)
    df["date"] = df["timestamp"].dt.date
    df = df.sort_values("timestamp").drop_duplicates(subset=["date", "illust_id"], keep="last")
    return df


def load_followers() -> pd.DataFrame | None:
    p = DATA_DIR / "followers.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df.drop_duplicates(subset="date", keep="last").sort_values("date")


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def dedupe_titles(titles: list[str], n: int = 22) -> list[str]:
    """タイトルをn文字で切り詰め、重複には (1)(2) を付けて一意にする"""
    shortened = [t[:n] + ("…" if len(t) > n else "") for t in titles]
    counts = Counter(shortened)
    seen: dict[str, int] = {}
    result = []
    for s in shortened:
        if counts[s] > 1:
            seen[s] = seen.get(s, 0) + 1
            base = s[:-1] if s.endswith("…") else s
            result.append(f"{base}({seen[s]})")
        else:
            result.append(s)
    return result


def str_dates(dates) -> list[str]:
    """date オブジェクトのリストを MM/DD 文字列に変換"""
    return [d.strftime("%m/%d") for d in dates]


# ---------------------------------------------------------------------------
# グラフ: 推移系
# ---------------------------------------------------------------------------

def fig_followers(df_fol: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))
    xs = list(range(len(df_fol)))
    ys = df_fol["followers"].tolist()
    ax.plot(xs, ys, marker="o", color=COLORS[0], linewidth=2)
    ax.fill_between(xs, ys, alpha=0.15, color=COLORS[0])
    ax.set_xticks(xs)
    ax.set_xticklabels(str_dates(df_fol["date"]), rotation=45, ha="right")
    ax.set_title("フォロワー数推移", fontsize=14)
    ax.set_ylabel("フォロワー数")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    path = OUTPUT_DIR / "followers.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_daily_totals(df: pd.DataFrame) -> Path:
    daily = df.groupby("date")[["views", "bookmarks", "likes"]].sum().reset_index()

    # 作品数: 統計データに「初めて登場した日」ベースで累計→差分
    first_seen = df.groupby("illust_id")["date"].min()
    cumulative = [int((first_seen <= d).sum()) for d in daily["date"]]
    cumulative[0] = 0  # 初日は0ベース
    delta = [cumulative[0]] + [max(0, cumulative[i] - cumulative[i-1]) for i in range(1, len(cumulative))]
    daily["work_count"] = delta

    xs     = list(range(len(daily)))
    labels = str_dates(daily["date"])

    fig, ax = plt.subplots(figsize=(7, 5))
    ax2 = ax.twinx()

    lines = []
    for col, label, color in [
        ("views",     "閲覧数",   COLORS[0]),
        ("bookmarks", "BM数",    COLORS[1]),
        ("likes",     "いいね数", COLORS[2]),
    ]:
        ys = daily[col].tolist()
        l, = ax.plot(xs, ys, marker="o", color=color, linewidth=2, label=label)
        ax.fill_between(xs, ys, alpha=0.08, color=color)
        lines.append(l)

    wc = daily["work_count"].tolist()
    bars = ax2.bar(xs, wc, color="#aaaaaa", alpha=0.35, width=0.4, label="作品数")
    ax2.set_ylim(0, max(wc) * 3 if max(wc) > 0 else 10)  # 上限3倍で棒を下寄りに
    lines.append(bars)

    ax.set_ylabel("閲覧 / BM / いいね")
    ax.yaxis.set_major_formatter(
        ticker.FuncFormatter(lambda x, _: f"{x/1000:.1f}k" if x >= 1000 else str(int(x)))
    )
    ax2.set_ylabel("作品数（新規）")
    ax2.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title("日次合計推移（累計値）", fontsize=14)
    ax.grid(True, linestyle="--", alpha=0.5)
    legend_labels = [l.get_label() for l in lines[:-1]] + ["作品数（新規）"]
    ax.legend(lines, legend_labels, loc="upper left", fontsize=9)

    fig.tight_layout()
    fig.subplots_adjust(left=0.13)
    path = OUTPUT_DIR / "daily_totals.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# グラフ: ランキング系（共通ヘルパー）
# ---------------------------------------------------------------------------

def _barh(ax, titles: list[str], values, color: str, xlabel: str, fmt: str = "{}"):
    bars = ax.barh(titles, values, color=color, alpha=0.85)
    labels = [fmt.format(v) if isinstance(v, int) else f"{v:.1f}%" for v in values]
    ax.bar_label(bars, labels=labels, padding=3, fontsize=9)
    ax.set_xlabel(xlabel)
    ax.grid(True, axis="x", linestyle="--", alpha=0.5)


def fig_bm_ranking(df: pd.DataFrame) -> Path:
    latest = df[df["date"] == df["date"].max()].sort_values("bookmarks")
    titles = dedupe_titles(list(latest["title"]))
    fig, ax = plt.subplots(figsize=(10, max(5, len(titles) * 0.42)))
    _barh(ax, titles, latest["bookmarks"].tolist(), COLORS[1], "ブックマーク数", "{}")
    ax.set_title(f"BM数ランキング ({df['date'].max()})", fontsize=14)
    fig.tight_layout()
    path = OUTPUT_DIR / "bm_ranking.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_weighted_ranking(df: pd.DataFrame) -> Path:
    """重みづけスコア: 閲覧×1 + BM×10 + いいね×5"""
    latest = df[df["date"] == df["date"].max()].copy()
    latest["score"] = latest["views"] * 1 + latest["bookmarks"] * 10 + latest["likes"] * 5
    latest = latest.sort_values("score")
    titles = dedupe_titles(list(latest["title"]))
    fig, ax = plt.subplots(figsize=(10, max(5, len(titles) * 0.42)))
    _barh(ax, titles, latest["score"].tolist(), COLORS[0], "スコア", "{:,}")
    ax.set_title("重みづけスコアランキング（閲覧×1 + BM×10 + いいね×5）", fontsize=13)
    fig.tight_layout()
    path = OUTPUT_DIR / "weighted_ranking.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_muttsu_ranking(df: pd.DataFrame) -> Path:
    """むっつり度: (BM×2 + いいね) ÷ 閲覧 × 100 (%)"""
    latest = df[df["date"] == df["date"].max()].copy()
    latest = latest[latest["views"] >= 10]
    latest["muttsu"] = (latest["bookmarks"] * 2 + latest["likes"]) / latest["views"] * 100
    latest = latest.sort_values("muttsu")
    titles = dedupe_titles(list(latest["title"]))
    fig, ax = plt.subplots(figsize=(10, max(5, len(titles) * 0.42)))
    bars = ax.barh(titles, latest["muttsu"], color=COLORS[2], alpha=0.85)
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=9)
    ax.set_xlabel("むっつり度 (%)")
    ax.set_title("むっつり度ランキング（(BM×2 + いいね) ÷ 閲覧 × 100%）", fontsize=13)
    ax.grid(True, axis="x", linestyle="--", alpha=0.5)
    fig.tight_layout()
    path = OUTPUT_DIR / "muttsu_ranking.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_score_growth(df: pd.DataFrame) -> Path | None:
    """重みづけスコア前日比急成長 Top10（閲覧×1 + BM×10 + いいね×5）"""
    df2 = df.copy()
    df2["score"] = df2["views"] * 1 + df2["bookmarks"] * 10 + df2["likes"] * 5

    pivot = df2.pivot_table(index="illust_id", columns="date", values="score", aggfunc="max")
    if pivot.shape[1] < 2:
        return None

    latest_date = pivot.columns[-1]
    prev_date   = pivot.columns[-2]

    delta = pivot[latest_date].sub(pivot[prev_date], fill_value=0)
    delta = delta.fillna(0)

    top10_ids  = delta.nlargest(10).index
    title_map  = df2.groupby("illust_id")["title"].last()

    rows = []
    for iid in top10_ids:
        title   = title_map.get(iid, str(iid))
        growth  = int(delta[iid])
        prev_s  = int(pivot.loc[iid, prev_date]) if iid in pivot.index and prev_date in pivot.columns and not pd.isna(pivot.loc[iid, prev_date]) else 0
        is_new  = prev_s == 0
        rows.append((title, growth, is_new))

    # 昇順（barh で上が大きい）
    rows.sort(key=lambda x: x[1])
    titles = dedupe_titles([r[0] for r in rows])
    values = [r[1] for r in rows]
    is_new = [r[2] for r in rows]
    colors = [COLORS[4] if new else COLORS[3] for new in is_new]

    fig, ax = plt.subplots(figsize=(10, max(5, len(rows) * 0.52)))
    bars = ax.barh(titles, values, color=colors, alpha=0.85)
    ax.bar_label(bars, labels=[f"+{v:,}" for v in values], padding=3, fontsize=9)
    ax.set_xlabel("スコア増加量")
    ax.set_title(
        f"重みづけスコア急成長作品 Top10（{prev_date} → {latest_date}）\n"
        "スコア = 閲覧×1 + BM×10 + いいね×5",
        fontsize=12,
    )
    ax.grid(True, axis="x", linestyle="--", alpha=0.5)

    # 凡例（新着マーク）
    if any(is_new):
        from matplotlib.patches import Patch
        legend = [
            Patch(color=COLORS[3], alpha=0.85, label="既存作品"),
            Patch(color=COLORS[4], alpha=0.85, label="新着作品"),
        ]
        ax.legend(handles=legend, fontsize=9, loc="lower right")

    fig.tight_layout()
    path = OUTPUT_DIR / "score_growth.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_bm_heatmap(df: pd.DataFrame) -> Path:
    pivot = df.pivot_table(index="title", columns="date", values="bookmarks", aggfunc="max")
    diff  = pivot.diff(axis=1).fillna(pivot.iloc[:, :1])
    top20 = pivot.iloc[:, -1].nlargest(20).index
    diff  = diff.loc[top20]
    short_titles = dedupe_titles(list(diff.index))

    fig, ax = plt.subplots(figsize=(max(8, len(diff.columns) * 0.8), max(5, len(top20) * 0.45)))
    im = ax.imshow(diff.values, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(diff.columns)))
    ax.set_xticklabels(str_dates(diff.columns), rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(short_titles)))
    ax.set_yticklabels(short_titles, fontsize=9)
    ax.set_title("作品別 日次BM増加 ヒートマップ（上位20作品）", fontsize=13)
    fig.colorbar(im, ax=ax, label="BM増加数")
    fig.tight_layout()
    path = OUTPUT_DIR / "bm_heatmap.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# HTMLレポート
# ---------------------------------------------------------------------------

def build_html(df: pd.DataFrame, df_fol: pd.DataFrame | None) -> Path:
    today       = df["date"].max()
    latest      = df[df["date"] == today]
    days_count  = df["date"].nunique()
    total_views = int(latest["views"].sum())
    total_bm    = int(latest["bookmarks"].sum())
    total_likes = int(latest["likes"].sum())
    work_count  = df["illust_id"].nunique()
    followers   = int(df_fol["followers"].iloc[-1]) if df_fol is not None and len(df_fol) else 0

    lat_v = latest[latest["views"] >= 10].copy()
    if len(lat_v):
        lat_v["muttsu"] = (lat_v["bookmarks"] * 2 + lat_v["likes"]) / lat_v["views"] * 100
        muttsu_top     = lat_v.loc[lat_v["muttsu"].idxmax(), "title"]
        muttsu_top_val = lat_v["muttsu"].max()
    else:
        muttsu_top, muttsu_top_val = "N/A", 0.0

    lat2 = latest.copy()
    lat2["score"] = lat2["views"] + lat2["bookmarks"] * 10 + lat2["likes"] * 5
    score_top     = lat2.loc[lat2["score"].idxmax(), "title"]
    score_top_val = int(lat2["score"].max())

    print("  グラフ生成中...")
    imgs: dict[str, str] = {}

    if df_fol is not None and len(df_fol) > 1:
        imgs["followers"] = fig_followers(df_fol).name
        print("    フォロワー推移 ✓")

    if days_count > 1:
        imgs["daily"]   = fig_daily_totals(df).name
        imgs["heatmap"] = fig_bm_heatmap(df).name
        p = fig_score_growth(df)
        if p:
            imgs["score_growth"] = p.name
        print("    日次推移・ヒートマップ・急成長 ✓")

    imgs["bm_rank"]       = fig_bm_ranking(df).name
    imgs["weighted_rank"] = fig_weighted_ranking(df).name
    imgs["muttsu_rank"]   = fig_muttsu_ranking(df).name
    print("    ランキング3種 ✓")

    def img_sec(key: str, caption: str) -> str:
        if key not in imgs:
            return ""
        p = OUTPUT_DIR / imgs[key]
        if p.exists():
            data = _b64.b64encode(p.read_bytes()).decode()
            src  = f"data:image/png;base64,{data}"
        else:
            src = imgs[key]
        return (f"<figure><img src='{src}' alt='{caption}'>"
                f"<figcaption>{caption}</figcaption></figure>")

    def section(title: str, *keys_captions) -> str:
        inner = "".join(img_sec(k, c) for k, c in keys_captions)
        if not inner.strip():
            return ""
        return f"<h2 class='sec-title'>{title}</h2>{inner}"

    def section_2col(title: str, key1: str, cap1: str, key2: str, cap2: str) -> str:
        f1 = img_sec(key1, cap1)
        f2 = img_sec(key2, cap2)
        if not f1 and not f2:
            return ""
        inner = f"<div class='fig-row'>{f1}{f2}</div>"
        return f"<h2 class='sec-title'>{title}</h2>{inner}"

    rows_html = ""
    for _, r in latest.sort_values("bookmarks", ascending=False).iterrows():
        muttsu = (r["bookmarks"] * 2 + r["likes"]) / r["views"] * 100 if r["views"] >= 10 else 0
        score  = int(r["views"] + r["bookmarks"] * 10 + r["likes"] * 5)
        rows_html += (
            f"<tr><td>{r['title']}</td><td>{r['create_date']}</td>"
            f"<td class='num'>{int(r['views']):,}</td>"
            f"<td class='num'>{int(r['bookmarks']):,}</td>"
            f"<td class='num'>{int(r['likes']):,}</td>"
            f"<td class='num'>{int(r['comments']):,}</td>"
            f"<td class='num'>{muttsu:.1f}%</td>"
            f"<td class='num'>{score:,}</td></tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8">
<title>Pixiv統計レポート {today}</title>
<style>
  body {{ font-family:"Meiryo","MS Gothic",sans-serif; margin:0; background:#f5f5f5; color:#333; }}
  header {{ background:#009cf5; color:#fff; padding:20px 32px; }}
  header h1 {{ margin:0; font-size:1.5rem; }}
  header p  {{ margin:4px 0 0; font-size:.9rem; opacity:.85; }}
  main {{ max-width:1200px; margin:24px auto; padding:0 16px; }}
  .kpi {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px; }}
  .kpi-card {{ background:#fff; border-radius:8px; padding:16px 24px; flex:1; min-width:120px;
               box-shadow:0 1px 4px rgba(0,0,0,.12); }}
  .kpi-card .label {{ font-size:.75rem; color:#888; }}
  .kpi-card .value {{ font-size:1.6rem; font-weight:bold; margin-top:4px; line-height:1.2; }}
  .kpi-card .sub   {{ font-size:.7rem; color:#aaa; margin-top:2px; overflow:hidden;
                      text-overflow:ellipsis; white-space:nowrap; }}
  .sec-title {{ font-size:1.1rem; font-weight:bold; color:#555; border-left:4px solid #009cf5;
                padding-left:10px; margin:32px 0 12px; }}
  figure {{ background:#fff; border-radius:8px; padding:16px; margin:0 0 20px;
            box-shadow:0 1px 4px rgba(0,0,0,.12); }}
  figure img {{ width:100%; }}
  figcaption {{ text-align:center; font-size:.8rem; color:#888; margin-top:6px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px;
           box-shadow:0 1px 4px rgba(0,0,0,.12); overflow:hidden; font-size:.82rem; }}
  th {{ background:#009cf5; color:#fff; padding:9px 10px; text-align:left; }}
  td {{ padding:7px 10px; border-bottom:1px solid #eee; }}
  tr:last-child td {{ border-bottom:none; }}
  tr:hover td {{ background:#f0f8ff; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .fig-row {{ display:flex; gap:16px; flex-wrap:wrap; }}
  .fig-row figure {{ flex:1; min-width:320px; }}
</style>
<script data-goatcounter="https://maom.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
</head><body>
<header>
  <h1>Pixiv 統計レポート</h1>
  <p>生成日: {today} ／ 集計開始からの日数: {days_count}日 ／ 作品数: {work_count}</p>
</header>
<main>

<div class="kpi">
  <div class="kpi-card">
    <div class="label">フォロワー数</div>
    <div class="value" style="color:#009cf5">{followers:,}</div>
  </div>
  <div class="kpi-card">
    <div class="label">総閲覧数</div>
    <div class="value">{total_views:,}</div>
  </div>
  <div class="kpi-card">
    <div class="label">総BM数</div>
    <div class="value" style="color:#f28e2b">{total_bm:,}</div>
  </div>
  <div class="kpi-card">
    <div class="label">総いいね数</div>
    <div class="value" style="color:#e15759">{total_likes:,}</div>
  </div>
  <div class="kpi-card">
    <div class="label">むっつり度TOP</div>
    <div class="value" style="color:#b07aa1">{muttsu_top_val:.1f}%</div>
    <div class="sub">{muttsu_top}</div>
  </div>
  <div class="kpi-card">
    <div class="label">スコアTOP</div>
    <div class="value" style="color:#59a14f">{score_top_val:,}</div>
    <div class="sub">{score_top}</div>
  </div>
</div>

{section_2col("推移", "followers", "フォロワー数推移", "daily", "日次合計推移（累計値）")}
{section("ランキング",
    ("score_growth", "重みづけスコア急成長作品 Top10（前日比）"),
    ("bm_rank",       "BM数ランキング"),
    ("weighted_rank", "重みづけスコアランキング（閲覧×1 + BM×10 + いいね×5）"),
    ("muttsu_rank",   "むっつり度ランキング（(BM×2+いいね) ÷ 閲覧 × 100%）"))}
{section("ヒートマップ", ("heatmap","作品別 日次BM増加 ヒートマップ"))}

<h2 class="sec-title">作品一覧</h2>
<table>
<thead><tr>
  <th>作品タイトル</th><th>投稿日</th>
  <th class="num">閲覧</th><th class="num">BM</th>
  <th class="num">♥</th><th class="num">コメ</th>
  <th class="num">むっつり度</th><th class="num">スコア</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>

</main></body></html>"""

    out = OUTPUT_DIR / f"report_{today}.html"
    out.write_text(html, encoding="utf-8")
    (OUTPUT_DIR.parent / "index.html").write_text(html, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------

def main():
    no_browser = "--no-browser" in sys.argv

    print("データ読み込み中...")
    df     = load_stats()
    df_fol = load_followers()
    print(f"  {df['date'].nunique()}日分 × {df['illust_id'].nunique()}作品")

    print("レポート生成中...")
    html_path = build_html(df, df_fol)
    print(f"レポート保存: {html_path}")

    if not no_browser:
        webbrowser.open(html_path.as_uri())
        print("ブラウザで開きました")


if __name__ == "__main__":
    main()
