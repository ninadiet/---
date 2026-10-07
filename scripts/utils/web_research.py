# -*- coding: utf-8 -*-
"""web_research.py — 今日の話題の「裏取り」を1か所で行う（2026-09-09 新設）

⚠️ このファイルは ③アフィリ / ④ホグ の両キットで**バイト単位で同一**にすること。

なぜ在るか
──────────────────────────────────────────────────────────
リサーチ層が集めていたのは YouTube のタイトルと RSS の見出しだけで、
**本文の取得も裏取りもしていなかった**。その結果ブリーフィングは「話題の一覧」にしかならず、
投稿は「読者がすでに知っている一般論」で埋まっていた（実測：3ジャンル7日で確認）。
さらに素材帳が空の利用者では、書ける具体が何も無いのに
「固有名詞と具体的数字を入れろ」と要求される状態になり、
数字を作る圧力＝架空の実績を生む構造になっていた。

ここでネット検索して裏の取れた具体（手順・番手・頻度）を材料として渡す。
これは創作ではなく、出典のある事実なので、
CLAUDE.md の「書いてよい数字」②一次ソースのある数字 ③ファクトチェック済みの値 に当たる。

守っていること
──────────────────────────────────────────────────────────
1. **引用0件は使わない。** モデルは検索せず自分の記憶で答えることがある（実測12回中2回）。
   それを裏取り済みとして扱うと「裏を取ったつもりの捏造」になる。
2. **落ちても生成を止めない。** 検索が使えない日も従来どおりブリーフィングを作る。
   ただし無音にはしない（台帳に「本日は裏取りなし」と残す）。
3. **生ソースをそのまま台帳に残す。** 要約だけ残すと後から追跡できない
   （CLAUDE.md の3層設計①）。出典URLは期限つきのリダイレクトなので**取得日が必須**。
"""

import os
import datetime

from utils.gemini_client import call_gemini_grounded
from loguru import logger

JST = datetime.timezone(datetime.timedelta(hours=9))

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(_SCRIPT_DIR, "..", "operation", "research")


def _today() -> str:
    return datetime.datetime.now(JST).strftime("%Y-%m-%d")


def build_query(theme: str, genre: str, headlines=None) -> str:
    """検索させる問いを組み立てる。

    ⚠️ 「〇〇について教えて」だと一般論が返ってきて意味がない。
       **読者がその日に実行できる粒度**（手順・数値・つまずき）を名指しで要求する。
    """
    topic = (theme or "").strip() or (genre or "").strip()
    hint = ""
    if headlines:
        picked = [h for h in headlines if h][:5]
        if picked:
            hint = "参考までに、今この分野で話題になっている見出しは次のとおり：" \
                   + " / ".join(picked[:5]) + "。ただしこの見出しの真偽は保証されないので、必ず裏を取ること。"
    return (
        f"「{topic}」について、読者が今日そのまま実行できる具体を調べてください。{hint}\n"
        "次の3つを、出典のある情報だけで答えてください：\n"
        "1. 具体的な手順（どの画面・どの道具・どの順番か。名前で書く）\n"
        "2. 数値（頻度・時間・分量・番手など。出典に書かれている値だけ。無ければ「記載なし」と書く）\n"
        "3. つまずきやすい点と、その回避方法\n"
        "⚠️ 憶測や一般論は書かないでください。検索して確認できたことだけを書いてください。"
    )


def _ledger_path(date_str: str) -> str:
    return os.path.join(RESEARCH_DIR, f"{date_str}.md")


def _write_ledger(date_str: str, query: str, result: dict) -> str:
    """生ソースをそのまま台帳に残す（LLMで要約し直さない）"""
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    lines = [
        f"# リサーチ台帳 {date_str}",
        "",
        "> このファイルは機械が自動で書きます。あとから「その数字はどこから来たか」を",
        "> 追えるようにするためのものです。編集しなくて構いません。",
        "",
        "## 投げた問い",
        "",
        "```",
        query.strip(),
        "```",
        "",
    ]
    if not result.get("ok"):
        reason = {
            "no_citation": "検索の引用が1件も取れなかった（モデルが検索せず記憶で答えた可能性）",
            "all_failed": "全モデルが応答しなかった（枠切れ・障害など）",
            "no_key": "APIキーが設定されていない",
        }.get(result.get("reason", ""), result.get("reason", "不明"))
        lines += [
            "## 結果：**本日は裏取りなし**",
            "",
            f"- 理由: {reason}",
            "- 投稿は従来どおり（YouTube／RSSの見出しと声定義）で作られます。",
            "- **この日の投稿に出典つきの数字は入りません。**",
            "",
        ]
    else:
        lines += [
            f"## 使ったモデル: `{result.get('model', '')}`",
            "",
            "## モデルが実際に投げた検索クエリ",
            "",
        ]
        lines += [f"- {q}" for q in (result.get("queries") or [])] or ["- （取得できず）"]
        lines += [
            "",
            "## 裏の取れた内容（そのまま・要約し直していません）",
            "",
            result.get("text", "").strip(),
            "",
            "## 出典",
            "",
            "| # | 区分 | ドメイン | 取得日 | URL |",
            "|---|---|---|---|---|",
        ]
        for i, s in enumerate(result.get("sources") or [], 1):
            lines.append(
                f"| {i} | {s.get('kind','')} | {s.get('domain','')} | {date_str} | {s.get('uri','')} |")
        lines += [
            "",
            "> ⚠️ 上のURLは検索サービスが発行する**期限つきのリダイレクト**で、",
            "> おおよそ30日で開けなくなります。だから取得日を必ず一緒に残しています。",
            "> あとから追う時は「ドメイン＋取得日」で探し直してください。",
            "",
        ]
    body = "\n".join(lines)
    path = _ledger_path(date_str)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def _briefing_block(result: dict) -> str:
    """ブリーフィングへ入れるブロック。裏取りできていなければ空文字。

    ⚠️ 2026-09-09 改訂：**出典のサイト名・企業名を本文に書かせない。**
       実測で「カウネットの調査によると76.0%が…」という投稿が出たが、
       読者はその社名を知らないので、**出典を書いたことでかえって疑わしく見える**
       （本人判定）。裏取りの目的は「読者に権威を見せる」ことではなく
       「こちらが嘘を書かない」ことなので、本文では出典をぼかしてよい。
       CLAUDE.md の✅2も「出典を本文に書く**／**ネタ台帳に一次URLがある」＝どちらかでよい。
       台帳（operation/research/YYYY-MM-DD.md）には全部残るので追跡性は落ちない。
    """
    if not result.get("ok"):
        return ""
    srcs = result.get("sources") or []
    n_pub = sum(1 for s in srcs if s.get("kind") == "公的・学術")
    n_corp = sum(1 for s in srcs if "企業" in (s.get("kind") or ""))
    n_sec = sum(1 for s in srcs if s.get("kind") == "二次")
    pub_names = [s.get("domain", "") for s in srcs if s.get("kind") == "公的・学術"][:3]
    return (
        "## 🔎 今日ネットで裏を取った情報（出典あり）\n\n"
        "⚠️ **投稿に数字を書くなら、ここに出ている数字だけを使うこと。**\n"
        "ここに無い数字は書かない（測っていない数字を作らない）。\n"
        "⚠️ この内容は**一般に公開されている情報**であって、あなたの体験ではない。\n"
        "「私は〜した」と書かず、「やり方は〜」「メーカーは〜と案内している」の形で使うこと。\n"
        "⚠️ **そのまま貼らない。** 読者が今日実行できる形に変換してから入れること。\n\n"
        # ⚠️ 実測：検索は「利用率は36.2%」のような**集団の割合**をよく拾ってくる。
        # それを使うと校閲が差し戻し、再生成の往復になる（実測で3/21スロット）。渡す時点で止める。
        "⛔ **上の中に「○%の人が」「利用率は○%」のような集団の割合があっても、投稿には使わない。**" + chr(10) +
        "　 公的機関（消費者庁・厚生労働省等）の調査で名前を明記できる場合だけ例外。" + chr(10) +
        "　 使うのは**手順・頸度・分量・番手などモノの数値**の方。" + chr(10) * 2 +
        "### 出典の書き方（守ること）\n"
        "⛔ **サイト名・企業名を本文に書かない。**\n"
        "　 読者が知らない社名を出すと、権威づけどころか「その会社は何？」と\n"
        "　 かえって疑わしく見える。実測でそう判定された。\n"
        "✅ 代わりにこう書く：「ある調査では」「調査によると」「メーカーの案内では」\n"
        "　 「公式の手順では」「〜と言われている」\n"
        "✅ **例外**：消費者庁・厚生労働省・国民生活センターなど、\n"
        "　 **誰でも知っている公的機関**だけは名前を出してよい（そこは信頼が上がる）。\n"
        f"　 今日の出典の内訳＝公的・学術 {n_pub}件 / 企業・メーカー {n_corp}件 / 個人・まとめ {n_sec}件"
        + (f"（公的：{', '.join(pub_names)}）" if pub_names else "") + "\n"
        "　（出典の一覧は operation/research/ の今日のファイルに記録済み）\n\n"
        + result.get("text", "").strip() + "\n"
    )

def run_daily_research(theme: str = "", genre: str = "", headlines=None,
                       api_key: str = None) -> str:
    """今日の裏取りを1回だけ行い、台帳に残して、ブリーフィング用のブロックを返す。

    Returns:
        ブリーフィングへ差し込む文字列。裏取りできなかった日は空文字（＝従来どおり進む）。

    ⚠️ この関数は例外を投げない。検索が原因で日次サイクルを止めないため。
    """
    date_str = _today()
    query = build_query(theme, genre, headlines)
    try:
        result = call_gemini_grounded(query, api_key=api_key)
    except Exception as e:   # 念のための保険（call_gemini_grounded 自体は投げない設計）
        logger.warning(f"裏取りで想定外のエラー: {type(e).__name__}: {str(e)[:120]}")
        result = {"ok": False, "reason": "all_failed"}

    try:
        path = _write_ledger(date_str, query, result)
        logger.info(f"リサーチ台帳: {path}")
    except OSError as e:
        logger.warning(f"リサーチ台帳を書けませんでした: {e}")

    if result.get("ok"):
        logger.info(f"裏取り成功: 引用 {len(result.get('sources') or [])} 件")
    else:
        logger.warning(f"裏取りなし（{result.get('reason')}）。従来どおり続行します。")
    return _briefing_block(result)
