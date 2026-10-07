# -*- coding: utf-8 -*-
"""post_history.py — 生成した投稿を残し、直近N日と見比べられるようにする

なぜ在るか（2026-08-24 新設・顧客報告）
──────────────────────────────────────────────────────────
「数日おきに同じ食材・同じ技法（白湯・生姜・味噌汁・スマホ断ち）が
 ほぼ同じ構成で繰り返される。酷い日は3スロット全部が焼き直し」という報告を受けた。

調べたところ、執筆担当が読むファイルは声定義とプロンプトルールの2つだけで、
**自分が昨日まで何を書いたかを一度も見ていなかった**。
つまり重複は不具合ではなく、重複しないほうが偶然という作りだった。

商品リサーチ側には同じ問題があり 2026-08-21 に直したが、そのとき
「他に何が繰り返しうるか」を投稿本文に広げなかった。ここがその穴。

設計
──────────────────────────────────────────────────────────
・生成のたびに1行（JSONL）追記するだけ。読む側は直近N日を取るだけ。
・追記のみなので、同日に複数回動いても壊れない。
・⚠️ このファイルは**コミットされている必要がある**。GitHub Actions は毎回
  まっさらなチェックアウトで動くため、コミットしないと毎日リセットされ、
  「昨日なにを書いたか」を読む手段がまた無くなる（＝同じ穴の再発）。
  daily-cycle.yml のコミットstepに含めてある。
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "operation", "memory", "post_history.jsonl")

KEEP_DAYS = int(os.getenv("POST_HISTORY_DAYS", "10"))


def _now_jst():
    return datetime.now(JST)


def _norm(s: str) -> str:
    """比較用に正規化（記号・空白・絵文字の違いで別物に見えないようにする）"""
    s = re.sub(r"https?://\S+", "", s or "")
    s = re.sub(r"[\s　]+", "", s)
    s = re.sub(r"[!-/:-@\[-`{-~！-／：-＠［-｀｛-～、。「」『』・…ー〜♪✨🙌💦😊😭🥺💡👇🔥]", "", s)
    return s


def record(slot_texts: dict, target_date: str = "", types: dict = None) -> None:
    """生成した投稿を1行追記する。slot_texts は {1: text, 2: text, 3: text}。
    types はそのスロットに使った「型」のID（採点係が後で成績を付けるための紐づけ・2026-08-25追加）"""
    date = target_date or _now_jst().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    row = {"date": date,
           "at": _now_jst().isoformat(),
           "slots": {str(k): (v or "")[:1200] for k, v in (slot_texts or {}).items()}}
    if types:
        row["types"] = {str(k): v for k, v in types.items()}
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_recent(days: int = KEEP_DAYS, anchor: str = "") -> list:
    """直近days日ぶんの投稿を新しい順で返す。

    基準日は「実行した瞬間の今日」ではなく **生成対象日**（2026-08-21 に
    商品側で踏んだのと同じ罠を避ける。--date 指定の再生成で窓がズレる）。
    """
    try:
        today = (datetime.strptime(anchor, "%Y-%m-%d").date()
                 if anchor else _now_jst().date())
    except ValueError:
        today = _now_jst().date()
    rows = []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    d = datetime.strptime(r.get("date", ""), "%Y-%m-%d").date()
                except (json.JSONDecodeError, ValueError):
                    continue          # 壊れた行があっても止めない
                if d > today or (today - d).days > days:
                    continue
                rows.append((d, r))
    except FileNotFoundError:
        return []
    rows.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in rows]


def summarize_for_prompt(days: int = KEEP_DAYS, anchor: str = "", limit: int = 18) -> str:
    """執筆担当に渡す「直近こう書いた」の一覧。冒頭だけで足りる（題材が分かればよい）。"""
    out = []
    for r in load_recent(days, anchor):
        for k in sorted(r.get("slots", {})):
            t = (r["slots"][k] or "").strip().split("\n")[0]
            if t:
                out.append("- %s: %s" % (r.get("date", ""), t[:60]))
            if len(out) >= limit:
                return "\n".join(out)
    return "\n".join(out)


def overlap_ratio(a: str, b: str, n: int = 8) -> float:
    """2つの文章の重なり具合（0〜1）。n文字の並びをどれだけ共有しているかで測る。

    形態素解析なしで日本語の「言い回しごとの使い回し」を捉えたいので、
    文字n-gramのJaccardにする。8文字にすると偶然の一致はほぼ出ない。
    """
    x, y = _norm(a), _norm(b)
    if len(x) < n or len(y) < n:
        return 0.0
    sx = {x[i:i + n] for i in range(len(x) - n + 1)}
    sy = {y[i:i + n] for i in range(len(y) - n + 1)}
    if not sx or not sy:
        return 0.0
    return len(sx & sy) / len(sx | sy)


# ── 題材レベルの重複検査（2026-09-01 新設・実アカウントで実測して追加）────────
# 事故：実際の利用者アカウントで「朝の登園準備をAIに相談したら怒鳴り声が減った」という
#      同じ話が2日間隔で投稿された（違うのはAIの名前と数字だけ）。
#      この2本を overlap_ratio にかけると **0.010**（差し戻し閾値0.22）で素通りだった。
# 原因：overlap_ratio は「言い回しの重なり」しか見ておらず、**題材の重なりを見ていない**。
#      言葉を変えて同じ話を書かれると、機械には別ネタに見える。
# 対策：本文から題材語（名詞的なかたまり）を抜き、直近の投稿と**題材で**照合する。
#      言い回しではなく「何について書いたか」で判定するので、書き換えでは逃げられない。
TOPIC_DAYS = int(os.getenv("POST_TOPIC_DAYS", "7"))   # 題材の再登場を禁じる日数
TOPIC_MIN_SHARED = int(os.getenv("POST_TOPIC_MIN", "2"))  # 何語一致したら同じ題材とみなすか

# 題材の手がかりにならない一般語（どの投稿にも出るので除く）
_TOPIC_STOP = {
    "こと", "とき", "ため", "もの", "自分", "今日", "毎日", "本当", "最近", "時間",
    "気持", "感じ", "内容", "方法", "状態", "場合", "以上", "以下", "一番", "普通",
    "投稿", "発信", "変化", "結果", "理由", "意味", "存在", "関係", "必要", "可能",
}


def topic_words(text: str) -> set:
    """本文から題材語を取り出す（漢字2字以上＋カタカナ3字以上のかたまり）"""
    out = set()
    for m in re.finditer(r"[一-龠]{2,6}|[ァ-ヴー]{3,10}", text or ""):
        w = m.group()
        if w in _TOPIC_STOP or len(w) > 10:
            continue
        out.add(w)
    return out


def find_topic_repeats(slot_texts: dict, days: int = None, anchor: str = "") -> list:
    """直近 TOPIC_DAYS 日と「題材」が重なるスロットを返す。

    言い回しを変えても、扱っている題材が同じなら拾う。
    当日の記録は除く（find_repeats と同じ理由＝自分と比較して毎回落ちるのを防ぐ）。
    """
    days = TOPIC_DAYS if days is None else days
    recent = load_recent(days, anchor)
    today_key = anchor if anchor else _now_jst().strftime("%Y-%m-%d")
    recent = [r for r in recent if r.get("date") != today_key]

    hits = []
    for k, text in (slot_texts or {}).items():
        if not text:
            continue
        mine = topic_words(text)
        if len(mine) < TOPIC_MIN_SHARED:
            continue
        best = (0, "", set(), "")
        for r in recent:
            for _pk, pt in (r.get("slots") or {}).items():
                shared = mine & topic_words(pt)
                if len(shared) > best[0]:
                    best = (len(shared), r.get("date", ""), shared,
                            (pt or "").strip().split(chr(10))[0][:40])
        if best[0] >= TOPIC_MIN_SHARED:
            hits.append({"slot": k, "date": best[1],
                         "shared": "・".join(sorted(best[2])[:5]), "excerpt": best[3]})
    return hits


def find_repeats(slot_texts: dict, days: int = KEEP_DAYS, anchor: str = "",
                 threshold: float = 0.22) -> list:
    """直近の投稿と重なりすぎているスロットを返す。

    threshold は「言い回しの使い回し」を拾い、
    同じ話題を別の切り口で書いた場合は通す線に置いてある（実測で調整）。
    """
    recent = load_recent(days, anchor)

    # ⚠️ 2026-08-25 修正（診断で発覚・最悪級）：
    #   執筆は生成直後に**今日の分**を履歴へ記録する。その直後に校閲がここを呼ぶと、
    #   「さっき自分が書いた投稿」と比較して一致率6割超＝**毎回必ず差し戻し**になっていた。
    #   さらにリトライのたびに今日の記録が増え、リトライするほど不合格になる逆スパイラル。
    #   重複回避の趣旨は「過去の日と被らない」なので、**当日の記録は比較対象から外す**。
    today_key = anchor if anchor else _now_jst().strftime("%Y-%m-%d")
    recent = [r for r in recent if r.get("date") != today_key]

    hits = []
    for k, text in (slot_texts or {}).items():
        if not text:
            continue
        best = (0.0, "", "")
        for r in recent:
            for pk, pt in (r.get("slots") or {}).items():
                ratio = overlap_ratio(text, pt)
                if ratio > best[0]:
                    best = (ratio, r.get("date", ""), (pt or "").strip().split("\n")[0][:48])
        if best[0] >= threshold:
            hits.append({"slot": k, "ratio": round(best[0], 3),
                         "date": best[1], "excerpt": best[2]})
    return hits
