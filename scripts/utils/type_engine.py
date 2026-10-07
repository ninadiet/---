# -*- coding: utf-8 -*-
"""type_engine.py — 「型の勝ち残りゲーム」：自分の実績で型を選び、育て、入れ替える

なぜ在るか（2026-08-25 新設）
──────────────────────────────────────────────────────────
実際の利用者から「同じ型を回すうちに内容がワンパターンになった」
「伸びた投稿が1本あるのに、その勝ち筋が翌日以降に活かされない」という報告を受けた。

これまでのキットには
  ・伸びた投稿を**保存する**仕組みはあった（絶対値基準）が、
  ・保存した勝ちを**翌日の生成に寄せる**仕組みが無かった。
勝ちが出ても出なくても、翌日は同じ書き方をする＝学習しない構造だった。

このモジュールは3つを閉じた輪にする：
  ①選ぶ … 今日の3スロットに使う「型」を、自分の成績上位から2つ＋探索枠1つで選ぶ
  ②測る … 投稿の成績を「自分の直近28日の中央値」との比で採点する（他人と比べない）
  ③入れ替える … 成果を生まない型をベンチに下げ、新しい型を試し続ける

設計原則
──────────────────────────────────────────────────────────
・すべて**自分比**。絶対値の基準を1つも持たない
  （フォロワー10人でも1万人でも、初日から同じ仕組みが働く）
・型は「文章の構造」だけを定義する。ジャンル・話題・商品には一切依存しない
・コールドスタート（採点が10件未満）の間は全型を均等に試す。
  試す順は利用者ごとに異なる（リポジトリ名から決まる）＝利用者どうしの投稿が似ない
・ベンチは「点が低い」では落とさない。**一度も成果を生まなかった型だけ**落とす
  （点が低くても1回でもフォロワーを連れてきた型は残す。低頻度の大当たり型を守るため）
・このファイルが読み書きするデータは workflow がコミットする前提
  （コミットされないと毎日リセットされ、学習が永久に始まらない）

データの置き場所
──────────────────────────────────────────────────────────
  operation/strategy/type_pool.json   … 型の一覧と成績（本体）
  operation/memory/type_scores.csv    … 採点の台帳（追記のみ）
  operation/weekly/type_report.md     … 人が読む1枚レポート（毎回上書き）
"""
import csv
import hashlib
import json
import os
import re
import statistics
from datetime import datetime, timedelta, timezone, date as _date

JST = timezone(timedelta(hours=9))
_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
POOL_PATH = os.path.join(_BASE, "operation", "strategy", "type_pool.json")
SCORES_PATH = os.path.join(_BASE, "operation", "memory", "type_scores.csv")
REPORT_PATH = os.path.join(_BASE, "operation", "weekly", "type_report.md")

# ── 型の初期プール ─────────────────────────────────────────────
# 「型」＝冒頭と展開の構造。どのジャンルでも成立する中立な定義だけを書く。
# guide は執筆プロンプトにそのまま渡る1〜2文。話題や商品名の例は書かない。
DEFAULT_TYPES = [
    {"id": "toikake", "name": "問いかけ型",
     "guide": "読者が日常で感じている小さな違和感を、そのまま質問の形で冒頭に置く。答えはツリーで明かす。⛔答えが「気をつける」「意識する」で終わるなら不合格。答えは**その場で試せる1手**にする。"},
    {"id": "bamen", "name": "場面描写型",
     "guide": "具体的な場所・時間・出来事の描写から入る。説明より先に情景を見せて、そこから気づきへつなぐ。⛔情景で終わらせない。**その場面で実際に打った文・とった手順**を1つ必ず出す。"},
    {"id": "shippai", "name": "失敗告白型",
     "guide": "自分の失敗・後悔を先に打ち明ける。かっこつけず、そこから学んだ1つだけを持ち帰らせる。**気づきで締めない。読んだ人が同じ失敗をしないように、先回りして教えてあげる形で締める。**「私はこうなった」で終わらせず、「だからあなたは、最初にここだけ見ておくといい」まで書く。"},
    {"id": "gyakubari", "name": "逆張り型",
     "guide": "多くの人が正しいと思っている**やり方**を冒頭で否定する（意見ではなく手順を否定する）。⛔「◯◯は不要」だけで終わらせない。**代わりにやる手順**をツリーで丸ごと出す。合格ラインは、読者が「今までの手順を今日やめられる」と分かること。"},
    {"id": "kazoe", "name": "数え上げ型",
     "guide": "「3つ」「5分」など具体的な数字を軸に、密度高く列挙する。⛔**1項目ごとに投稿を分けない。**列挙は1投稿の中に収め、各項目に理由を1つ添える（分けると1投稿30字になり、読者が何度もタップすることになる）。⛔よく見る項目を並べない。**1つ以上は読者が見たことのない項目**を混ぜる。"},
    {"id": "tejun", "name": "手順公開型",
     "guide": "やり方をまるごと順番に公開する。出し惜しみせず、今日そのまま真似できる粒度で書く。**打ち込む文・押す場所・つまずく所**を省かない。⛔概要だけの手順は不合格。⛔**手順①②③を投稿ごとにバラさない。**①②③は1投稿の中に並べ、その投稿に「どこで詰まるか」も足す（バラすと1投稿30字になる）。"},
    {"id": "hikaku", "name": "比較型",
     "guide": "2つの選択肢を並べて比べ、どちらをなぜ選ぶかを言い切る。判断基準を1つに絞る。⛔「どちらも良い」で逃げない。**自分はこっち**と決めて、その理由を1つに絞る。"},
    {"id": "yobikake", "name": "呼びかけ型",
     "guide": "「〜で悩んでいるあなたへ」のように読み手を1人に絞って呼びかける。その1人に手紙のように書く。⛔励ましで終わらせない。その1人が**今日できる1手**を必ず渡す。"},
    {"id": "hakken", "name": "発見共有型",
     "guide": "「実は〜だった」という意外な事実から入る。知らなかった読者が誰かに話したくなる形にする。**自分が使って初めて分かったこと**なら、いちばん強い。"},
    {"id": "rensai", "name": "連載型",
     "guide": "話に続きがあることを示して締める（「明日は〜の話」など）。読者への依頼は命令形にせず対等の形で。⛔予告だけの投稿にしない。**今日の分だけで完結する持ち帰り**を1つ入れてから予告する。"},
    {"id": "urawaza", "name": "裏の使い方型",
     "guide": "**本来の用途ではない使い方**を1つ見せる。読者が「そんな使い方があったのか」と止まる角度。⛔ただの便利機能紹介は不合格。**みんなが知っている道具を、みんながやらない順番・目的で使う**。見つけ方＝①出力ではなく『問いの方』を作らせる ②手順の順番をひっくり返す ③やらなくていいことを名指しする ④一行足すだけで結果が変わる指示を出す。必ず**その場で試せる形**（打ち込む文・順番）まで書く。"},
]

RULES = {
    "rolling_samples": 10,       # 型の成績＝直近10回の移動平均
    "cold_start_until": 10,      # 採点が溜まるまでは全型を均等に試す
    "min_samples_for_bench": 5,  # 5回試すまでは絶対にベンチしない
    "bench_window_days": 21,     # 成果ゼロ判定を見る窓
    "min_active": 6,             # 稼働中の型はこれ未満にしない
    "max_bench_per_day": 1,      # 1日に落とすのは最大1型
    "explore_slots": 1,          # 毎日1スロットは探索枠
    "base_window_days": 28,      # 自分比の基準＝直近28日の同スロット中央値
    "base_min_samples": 3,       # 基準を作るのに必要な最低サンプル
    "relative_win_ratio": 3.0,   # 閲覧が自分の中央値の3倍なら「勝ち」として学習へ保存
    # 採点の重み（2026-08-26 改訂）：このキットの最終ゴールは「投稿のインプ（表示回数）を
    # 伸ばすこと」なので閲覧を最重視する。フォロワー増は「見られた後に残す力」として
    # 次点で残す（初動エンゲージの土台＝将来のインプにも効くため）。
    "w_views": 0.50, "w_follower": 0.30, "w_likes": 0.20,
    "w_views_nf": 0.65, "w_likes_nf": 0.35,   # フォロワー計測が無い環境用
}


def _now_jst():
    return datetime.now(JST)


def _customer_seed() -> int:
    """利用者ごとに異なる（が本人内では毎回同じ）順序の種。
    リポジトリ名→無ければ認証ID→無ければ固定値。
    これで全利用者が同じ順で型を試して投稿が似てしまうのを防ぐ。"""
    for source in (os.getenv("GITHUB_REPOSITORY", ""),):
        if source:
            return int(hashlib.sha256(source.encode()).hexdigest()[:8], 16)
    try:
        with open(os.path.join(_BASE, "auth_member.txt"), encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return int(hashlib.sha256(v.encode()).hexdigest()[:8], 16)
    except OSError:
        pass
    return 20260825


# ── プールの読み書き ───────────────────────────────────────────
def load_pool() -> dict:
    try:
        with open(POOL_PATH, encoding="utf-8") as f:
            pool = json.load(f)
        if pool.get("types"):
            # ── 新しい型の取り込み（2026-08-26 追加）─────────────────────
            # type_pool.json は利用者の学習資産なので、キット更新で**上書きしない**。
            # その代わり、キット側の DEFAULT_TYPES に新しい型が増えていたら、
            # 成績を壊さずに「未採点の新型」としてプールへ合流させる。
            # ＝運営がキット更新で型を追加でき、利用者の探索枠が自動で試し始める。
            have = {t["id"] for t in pool["types"]}
            for d in DEFAULT_TYPES:
                if d["id"] not in have:
                    pool["types"].append(dict(d, status="active", score=None, n=0,
                                              used=0, last_used="", bench_reason=""))
            # ── guide（書き方の指示）の更新も届かせる（2026-09-12 追加）───────
            # 従来は「新しい型」しか合流せず、**既存の型の guide を良くしても
            # 既にプールを持っている利用者には一生届かなかった**。
            # guide は運営が書く指示であって利用者の学習資産ではないので、上書きしてよい。
            # 成績（score / n / used / last_used / status）には触らない。
            _def = {d["id"]: d for d in DEFAULT_TYPES}
            for t in pool["types"]:
                d = _def.get(t["id"])
                if d and t.get("guide") != d["guide"]:
                    t["guide"] = d["guide"]
                    t["name"] = d["name"]
            return pool
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "types": [dict(t, status="active", score=None, n=0,
                                         used=0, last_used="", bench_reason="")
                                    for t in DEFAULT_TYPES],
            "rules": dict(RULES)}


def save_pool(pool: dict) -> None:
    os.makedirs(os.path.dirname(POOL_PATH), exist_ok=True)
    pool["updated"] = _now_jst().isoformat()
    with open(POOL_PATH, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


# ── 台帳の読み書き ─────────────────────────────────────────────
_CSV_HEADER = ["date", "slot", "type_id", "views", "likes",
               "follower_attr", "score", "flags"]


def _read_scores() -> list:
    rows = []
    try:
        with open(SCORES_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except OSError:
        pass
    return rows


def _append_scores(new_rows: list) -> None:
    os.makedirs(os.path.dirname(SCORES_PATH), exist_ok=True)
    exists = os.path.exists(SCORES_PATH)
    with open(SCORES_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_HEADER)
        if not exists:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)


def _anchor_date(anchor: str = "") -> _date:
    try:
        return datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else _now_jst().date()
    except ValueError:
        return _now_jst().date()


def _recent_rows(days: int, anchor: str = "") -> list:
    today = _anchor_date(anchor)
    out = []
    for r in _read_scores():
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if d > today or (today - d).days > days:
            continue
        out.append(r)
    return out


# ── ①選ぶ ─────────────────────────────────────────────────────
def select_today(n_slots: int = 3, anchor: str = "") -> list:
    """今日使う型を n_slots 個選ぶ。返り値は [{'id','name','guide'}...]。

    コールドスタート（採点10件未満）: 全型を均等に・利用者固有の順で回す
    通常運転: 成績上位から (n_slots-1) 個 ＋ 探索枠1個（最も試していない型）
    """
    pool = load_pool()

    # ── 同日は同じ選択を返す（冪等）──
    # 差し戻しリトライや correct.yml の再生成で同じ日に複数回呼ばれる。
    # 毎回選び直すと (a)使用回数が水増しされ (b)再生成のたびに型が変わって
    # 「どの型の成績か」が採点と食い違う。日付キーで固定する。
    today_key = _anchor_date(anchor).isoformat()
    daily = pool.get("daily") or {}
    if daily.get("date") == today_key and len(daily.get("ids", [])) >= n_slots:
        by_id = {t["id"]: t for t in pool["types"]}
        return [{"id": i, "name": by_id[i]["name"], "guide": by_id[i]["guide"]}
                for i in daily["ids"][:n_slots] if i in by_id]

    active = [t for t in pool["types"] if t.get("status") == "active"]
    if len(active) < n_slots:                       # 想定外でも止めない
        active = pool["types"][:]

    scored_total = sum(t.get("n", 0) for t in pool["types"])
    seed = _customer_seed()
    day_no = _anchor_date(anchor).toordinal()

    if scored_total < pool["rules"].get("cold_start_until", 10):
        # 均等試行：使用回数が少ない順 → 同数なら利用者固有の順
        ordered = sorted(active, key=lambda t: (t.get("used", 0),
                                                (seed ^ hash(t["id"])) % 9973))
        chosen = ordered[:n_slots]
    else:
        ranked = sorted([t for t in active if t.get("score") is not None],
                        key=lambda t: -t["score"])
        chosen = ranked[: max(1, n_slots - RULES["explore_slots"])]
        rest = [t for t in active if t not in chosen]
        rest.sort(key=lambda t: (t.get("used", 0), t.get("last_used", "")))
        chosen += rest[: n_slots - len(chosen)]

    # ── 保存・再投稿を取りにいく型を1つは必ず入れる（2026-09-08 追加）──
    # 執筆プロンプトには最初から
    #   「★3スロットのうち必ず1つはリスト形式か対比形式にすること」
    # という指示がある（保存・再投稿のトリガーを取るための元からの設計）。
    # ところが select_today はその制約を知らず、10型中該当は2型だけなので、
    # 実測では3ジャンル中2ジャンルが違反していた（＝指示と型が毎日けんかしていた）。
    # 1本だけ差し替えて整合を取る。成績上位は残し、**末尾（探索枠）だけ**を入れ替える。
    _SAVE_TYPES = ("kazoe", "hikaku")          # 数え上げ型／比較型

    # ── 読者がその場で真似できる型を1つは必ず入れる（2026-09-11 追加）──
    # 本人指摘＝「内容が薄い。フォローして即使えるものにしてほしい」。
    # 実測で原因を特定した：3日間に割り当てられた9型は
    #   比較／問いかけ／逆張り／連載／発見共有／比較／問いかけ／数え上げ／失敗告白
    # で、**手順が出る型が1度も出ていなかった**。
    # 「貼れる指示文・数字・手順を入れよ」と執筆プロンプトに4通り書いて試したが
    # 5/9 → 4/9 → 5/9 → 5/9 でまったく動かなかった。
    # 当然で、割り当てられた型が「比較しろ」「問いかけろ」と言っている日に、
    # 文章だけで手順を要求しても勝てない。**型の側で席を1つ確保する。**
    _HOWTO_TYPES = ("tejun", "kazoe", "urawaza")   # 手順公開型／数え上げ型／裏の使い方型

    def _ensure(want, keep_idx):
        """want のどれかが chosen に無ければ1枠だけ差し替える。差し替えた位置を返す。

        ⚠️ 成績上位（先頭）を壊さないよう**末尾から**探す。
           keep_idx は「直前の保証で埋めた枠」＝そこは上書きしない。
        """
        if not chosen or any(t["id"] in want for t in chosen):
            return None
        cand = [t for t in active if t["id"] in want and t not in chosen]
        if not cand:
            return None
        cand.sort(key=lambda t: (t.get("used", 0), t.get("last_used", "")))
        for i in range(len(chosen) - 1, -1, -1):
            if i != keep_idx:
                chosen[i] = cand[0]
                return i
        return None

    # ① 手順が出る型（これが無いと「心がけ」だけの投稿になる）
    _i = _ensure(_HOWTO_TYPES, None)
    # ② 保存・再投稿を取りにいく型（執筆プロンプトの「1つはリストか対比」と整合させる）
    #    ①で埋めた枠は壊さない。kazoe は両方を兼ねるので、その日は差し替え自体が起きない。
    _ensure(_SAVE_TYPES, _i)

    # スロットへの割り当ては日替わりで回す（同じ型が毎日同じ時間帯に固定されるのを防ぐ）
    rot = (seed + day_no) % max(1, len(chosen))
    chosen = chosen[rot:] + chosen[:rot]

    for t in chosen:                                 # 使用記録
        for p in pool["types"]:
            if p["id"] == t["id"]:
                p["used"] = p.get("used", 0) + 1
                p["last_used"] = _anchor_date(anchor).isoformat()
    pool["daily"] = {"date": today_key, "ids": [t["id"] for t in chosen]}
    save_pool(pool)
    return [{"id": t["id"], "name": t["name"], "guide": t["guide"]} for t in chosen]


def prompt_block(chosen: list) -> str:
    """執筆プロンプトへそのまま入れる文字列を作る"""
    if not chosen:
        return ""
    lines = ["### 今日の各スロットの「型」（この構造で書く。型名は本文に書かない）"]
    for i, t in enumerate(chosen, 1):
        # ⚠️ 「SLOT_n【…】」は**スロット見出しと同じ書式**。
        #    この行をモデルが復唱すると、校閲の抽出器が見出しと誤認して
        #    本文が2本消える（実測で発生）。書式をずらして衝突させない。
        lines.append(f"- SLOT_{i} … 「{t['name']}」{t['guide']}")
    lines.append("型が同じでも、話題・言い回しは過去の投稿と重複させないこと。")
    return "\n".join(lines) + "\n"


# ── ②測る ─────────────────────────────────────────────────────
def _comp(x: float, base: float) -> float:
    if base <= 0:
        return 0.5
    return min(x / base, 2.0) / 2.0


def _slot_base(slot: str, col: str, anchor: str) -> float:
    vals = []
    for r in _recent_rows(RULES["base_window_days"], anchor):
        if str(r.get("slot")) == str(slot):
            try:
                vals.append(float(r.get(col) or 0))
            except ValueError:
                pass
    if len(vals) < RULES["base_min_samples"]:
        return -1.0
    return max(statistics.median(vals), 1.0)


def score_day(date_str: str, slot_metrics: dict, follower_gain=None,
              slot_types: dict = None) -> list:
    """1日ぶんを採点して台帳とプールを更新する。

    slot_metrics: {"1": {"views": int, "likes": int}, ...}
    follower_gain: その日のフォロワー純増（不明なら None）
    slot_types:   {"1": "toikake", ...}（無ければ post_history から探す）
    """
    if slot_types is None:
        slot_types = _types_from_post_history(date_str)

    total_views = sum(max(0, int(m.get("views") or 0))
                      for m in slot_metrics.values()) or 1
    results = []
    for slot, m in sorted(slot_metrics.items()):
        views = max(0, int(m.get("views") or 0))
        likes = max(0, int(m.get("likes") or 0))
        flags = []
        vb = _slot_base(slot, "views", date_str)
        lb = _slot_base(slot, "likes", date_str)
        if vb < 0 or lb < 0:
            flags.append("NO_BASE")     # 基準がまだ無い＝中立の50点相当で記録
        if follower_gain is None:
            flags.append("NO_FOLLOWER")
            f_attr = 0.0
            score = 100 * (RULES["w_views_nf"] * (_comp(views, vb) if vb > 0 else 0.5)
                           + RULES["w_likes_nf"] * (_comp(likes, lb) if lb > 0 else 0.5))
        else:
            f_attr = max(0.0, float(follower_gain)) * (views / total_views)
            fb = _slot_base(slot, "follower_attr", date_str)
            score = 100 * (RULES["w_follower"] * (_comp(f_attr, fb) if fb > 0 else 0.5)
                           + RULES["w_views"] * (_comp(views, vb) if vb > 0 else 0.5)
                           + RULES["w_likes"] * (_comp(likes, lb) if lb > 0 else 0.5))
        results.append({"date": date_str, "slot": str(slot),
                        "type_id": (slot_types or {}).get(str(slot), ""),
                        "views": views, "likes": likes,
                        "follower_attr": round(f_attr, 3),
                        "score": round(score, 1), "flags": "|".join(flags)})
    _append_scores(results)
    _update_pool(results, date_str)
    _write_report(date_str)
    return results


def _types_from_post_history(date_str: str) -> dict:
    """post_history.jsonl から、その日の各スロットの型IDを引く"""
    path = os.path.join(_BASE, "operation", "memory", "post_history.jsonl")
    found = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("date") == date_str and r.get("types"):
                    found = {str(k): v for k, v in r["types"].items()}
    except OSError:
        pass
    return found


def is_relative_win(views: int, anchor: str = "") -> bool:
    """自分の直近28日の閲覧中央値の relative_win_ratio 倍を超えたら「勝ち」。
    絶対値の勝ち基準（大きいアカウント向け）と OR で併用する。"""
    vals = []
    for r in _recent_rows(RULES["base_window_days"], anchor):
        try:
            vals.append(float(r.get("views") or 0))
        except ValueError:
            pass
    if len(vals) < 5:
        return False
    med = max(statistics.median(vals), 1.0)
    return views >= med * RULES["relative_win_ratio"]


# ── ③入れ替える ───────────────────────────────────────────────
def _update_pool(new_rows: list, anchor: str) -> None:
    pool = load_pool()
    rows = _read_scores()

    for t in pool["types"]:
        mine = [r for r in rows if r.get("type_id") == t["id"] and "NO_BASE" not in (r.get("flags") or "")]
        mine = mine[-RULES["rolling_samples"]:]
        if mine:
            t["n"] = len([r for r in rows if r.get("type_id") == t["id"]])
            t["score"] = round(sum(float(r["score"]) for r in mine) / len(mine), 1)

    # ベンチ判定v2：点の低さでは落とさない。
    # 「窓の中で min_samples 回以上試して、フォロワー寄与が一度もゼロ超にならなかった型」だけ落とす。
    active = [t for t in pool["types"] if t.get("status") == "active"]
    if len(active) > RULES["min_active"]:
        window = _recent_rows(RULES["bench_window_days"], anchor)
        benched = 0
        for t in sorted(active, key=lambda x: (x.get("score") or 50)):
            if benched >= RULES["max_bench_per_day"]:
                break
            mine = [r for r in window if r.get("type_id") == t["id"]]
            if len(mine) < RULES["min_samples_for_bench"]:
                continue
            has_follower_data = any("NO_FOLLOWER" not in (r.get("flags") or "") for r in mine)
            if not has_follower_data:
                continue                     # フォロワー計測が無い環境ではベンチしない
            if all(float(r.get("follower_attr") or 0) <= 0 for r in mine):
                t["status"] = "bench"
                t["bench_reason"] = (f"{RULES['bench_window_days']}日間で{len(mine)}回試して"
                                     f"フォロワー増への寄与が一度もゼロを超えなかった")
                benched += 1
    save_pool(pool)


# ── 人が読むレポート ───────────────────────────────────────────
def _write_report(anchor: str) -> None:
    pool = load_pool()
    lines = [f"# 型の成績表（{anchor} 更新・数字はすべて自分比）", ""]
    lines.append("| 型 | 状態 | 成績(直近10回平均・50=普段どおり) | 試行回数 |")
    lines.append("|---|---|---|---|")
    for t in sorted(pool["types"], key=lambda x: -(x.get("score") or 0)):
        s = "稼働" if t.get("status") == "active" else f"ベンチ（{t.get('bench_reason','')}）"
        lines.append(f"| {t['name']} | {s} | {t.get('score') if t.get('score') is not None else '未採点'} | {t.get('n',0)} |")
    lines += ["",
              "- 成績は「自分の直近28日の中央値と比べて」の点数。50点＝普段どおり、100点＝普段の2倍以上。",
              "- 型は成績上位2つ＋探索枠1つで毎日選ばれます。ベンチ入りは「成果を一度も生まなかった型」だけです。",
              "- あなたが何かをする必要はありません。この表は読むだけでOKです。"]
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
