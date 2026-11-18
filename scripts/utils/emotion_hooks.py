"""汎用感情フック100 から、その日の候補をライターに渡す（2026-11-19 追加）。

- 正本は operation/knowledge/emotion_hooks_100.md（「番号. フック」の行）
- 日付でシードした抽選なので、同じ日の再生成（差し戻し後の書き直し）でも候補が変わらない
- ファイルが無い・読めない時は空文字を返し、投稿生成は従来どおり動く
"""
import os
import random
import re
from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "operation", "knowledge", "emotion_hooks_100.md")


def load_hooks(path: str = _PATH) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    hooks = []
    for line in lines:
        m = re.match(r"^\s*\d+\.\s*(.+?)\s*$", line)
        if m:
            hooks.append(m.group(1))
    return hooks


def pick_today(n: int = 6, date: str = "") -> list[str]:
    hooks = load_hooks()
    if not hooks:
        return []
    seed = date or datetime.now(_JST).strftime("%Y-%m-%d")
    return random.Random(seed).sample(hooks, min(n, len(hooks)))


def prompt_block(n: int = 6, date: str = "") -> str:
    picks = pick_today(n, date)
    if not picks:
        return ""
    listed = "\n".join(f"- {h}" for h in picks)
    return f"""
---
## ★今日の感情フック候補（汎用感情フック100から日替わり抽選）★
{listed}

使い方：
- **3スロットのうち最低1つ**（推奨＝実験枠・夜のスロット）は、1投稿目の書き出しを上の候補から1つ選んで始める。
  他のスロットも内容に合うなら使ってよい。同じフックを2スロットで使わない。
- 声定義の「定番のつかみ」行がある場合は、その行の**直後**に置く（つかみ行を消さない）。
- フックの文言は**そのまま**使ってよい（語尾だけ声定義に合わせて調整可）。
- フックの直後に必ず具体を続ける：今日のテーマの場面・数字・固有名詞。フックだけで1投稿目を終わらせない。
- 読者や特定の誰かを攻撃・見下す向きには使わない。「世の中の常識・よくある思い込み」に向ける。
- 声定義のキャラに合わない強い言い回し（怒り・皮肉が強すぎるもの）は選ばない。
"""
