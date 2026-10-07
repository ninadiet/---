# -*- coding: utf-8 -*-
"""material_prompt.py — 素材帳の聞き取りを「機械が期日を判定する」形にする（2026-09-09 新設）

⚠️ このファイルは ③アフィリ / ④ホグ の両キットで**バイト単位で同一**にすること。

なぜ在るか
──────────────────────────────────────────────────────────
素材帳の聞き取りは、最初 CLAUDE.md に**散文で**書いてあるだけだった。
  「素材帳が3行未満なら聞く」「週に1回は巡回の3問を聞く」
これは動かない。理由は運営側の CLAUDE.md が既に言語化している：

  散文は「セッションが始まって・そのファイルが読まれて・やろうと判断された時」しか動かない
  ＝**本人の声かけが起動条件**になる。しかも完了痕跡が無いので、やらなくても何も鳴らない。

実際、旧仕様は「1回提案して断られたら `.material_asked` を作り、以後永久に黙る」だった。
＝ 聞き取りが一度も走らないまま、素材帳が空のまま運用が続く利用者が普通に生まれていた。

そこで、定例を成立させる3点を機械側に持たせる：
  ① 登記     … 判定はこの1ファイルだけが持つ（散文に判断を置かない）
  ② 完了痕跡 … いつ聞いたか・何を聞いたか・何件入ったかを state ファイルに残す
  ③ 自動起動 … 毎日動いている生成サイクルが期日を判定し、
                **顧客が必ず見る場所（承認申請のコメント）**に1行だけ出す

これで「Claudeが思い出したら聞く」ではなく「期日が来たら機械が出す」になる。
"""

import os
import json
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_UTILS_DIR)
MATERIAL_PATH = os.path.join(_SCRIPTS_DIR, "..", "operation", "my_material.md")
STATE_PATH = os.path.join(_SCRIPTS_DIR, "..", "operation", "config", "material_state.json")

#: 立ち上げ用の7問（一度ずつ聞く）。
#
# ⚠️ 2026-09-12 全面改訂。旧版は**答えられない問いが混ざっていた**。
#    実測（本人が実際に答えてみた結果）：
#      答えられた … 「やめたこと・減らしたこと」「うまくいかない時にどうしたか」
#      答えられない … 「数字で言えることは？」「周りと違う使い方は？」「よく聞かれることは？」
#    差は1つだけ。**起きた出来事を聞くと答えられる。自己評価を求めると答えられない。**
#    人は「自分の何が珍しいか」を判定できないし、測っていない数字も出せない。
#    本人の言葉＝「当たり前のように使っていて、みんなと違うか分からない」。
#
#    だから以後、この7問は**全部「何をしたか・何が変わったか」だけ**を聞く。
#    ⛔ 追加・変更するときも、次の形の問いを入れないこと：
#       「あなたの強みは」「人と違う点は」「何割くらい」「どのくらい効果が」
#
#    ジャンルを問わず答えられる（日用品でも育児でもAIでも「つまずき」「やめたこと」はある）。
#    実績ゼロでも答えられる＝始めたばかりの人ほど答えやすい問いにしてある。
SEVEN_QUESTIONS = [
    "最初にどこでつまずきましたか？（うまくいかなかった場面をそのまま）",
    "それをどうやって切り抜けましたか？（やり直した・調べた・人に聞いた 等）",
    "やってみて「思ってたのと違った」ことは？",
    "できたとき、いちばん嬉しかったのは何ですか？",
    "前はやっていたのに、今はやらなくなったことは？",
    "今も解決していなくて、困ったままのことは？",
    "毎回おなじ順番でやっていることはありますか？"
    "（例：まず〇〇して、次に△△する。道具・置き場所・声のかけ方でもOK）",
]

#: ⚠️ 質問文は**答え方が想像できる形**にすること（2026-09-12 本人指摘）。
#   旧「実際に使っている手順や設定で、そのまま人に見せられるものはありますか？」は
#   「見せられるもの」＝価値の自己判定を求めていたので答えられなかった。
#   ⭕「毎回おなじ順番でやっていることは？」＝**やっているかどうか**だけを聞いている。
#   質問を足すときは、必ず（例：…）を1つ添えて、答えの形を見せること。

#: 7問を答え終えたあとの積立用（毎週答えが変わるので何度でも聞ける）
#  こちらも「先週その人に起きたこと」だけを聞く（同上の理由）。
WEEKLY_QUESTIONS = [
    "先週、思ったのと違ったことは？",
    "先週やめたこと・減らしたことは？",
    "先週うまくいかなくて、やり直したのはどこですか？",
]

#: 素材帳が「立ち上がった」とみなす行数。これ未満なら7問フェーズ。
BOOTSTRAP_LINES = 3
#: 積立フェーズで聞く間隔（日）
WEEKLY_INTERVAL_DAYS = 7


def _today() -> datetime.date:
    return datetime.datetime.now(JST).date()


def count_material_lines(path: str = None) -> int:
    """素材帳の「実記入」行数を数える。

    ⚠️ 行頭が `- ` の行だけを数える。説明文（行頭 `>`）と記入例（（例）で始まる行）は
       素材として渡らない仕様なので、ここでも数えない。
       これを間違えると「説明文が入っているから記入済み」と誤判定し、
       聞き取りが永久に発動しなくなる（2026-09-08 に実際に起きた形）。
    """
    p = path or MATERIAL_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return 0
    n = 0
    for ln in lines:
        t = ln.strip()
        if not t.startswith("- "):
            continue
        if t.lstrip("-*・ ").startswith("（例）"):
            continue
        n += 1
    return n


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("asked_seven", [])     # 7問のうち既に聞いた番号（0始まり）
    st.setdefault("last_asked", "")      # 最後に聞いた日（YYYY-MM-DD）
    st.setdefault("last_answered", "")   # 最後に素材が増えた日
    st.setdefault("last_line_count", 0)  # 前回見たときの実記入行数
    return st


def save_state(st: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except OSError:
        pass          # 記録できなくても運用は止めない


def next_question() -> dict:
    """今日聞くべき問いを1つ返す。聞く必要が無ければ due=False。

    Returns:
        {"due": bool, "phase": "bootstrap"|"weekly", "question": str,
         "lines": int, "reason": str}
    """
    lines = count_material_lines()
    st = load_state()
    today = _today()

    # 素材が増えていたら記録しておく（あとで「答えてくれた日」が分かる）
    if lines > st.get("last_line_count", 0):
        st["last_answered"] = today.isoformat()
        st["last_line_count"] = lines
        save_state(st)

    if lines < BOOTSTRAP_LINES:
        # ── 立ち上げフェーズ：7問を1つずつ。毎日1問（断られても翌日また次の1問）
        asked = [i for i in st.get("asked_seven", []) if 0 <= i < len(SEVEN_QUESTIONS)]
        remaining = [i for i in range(len(SEVEN_QUESTIONS)) if i not in asked]
        if not remaining:
            # 7問を一巡したら最初から回す（諦めない）。
            # ⚠️ ここで state を実際に空に戻すこと。変数だけ戻して保存しないと、
            #    mark_asked() が満杯のリストに追記し続け、毎日同じ問い（1番目）を
            #    出し続ける（8日目以降が全部同じになる・実測で発見）。
            remaining = list(range(len(SEVEN_QUESTIONS)))
            asked = []
            st["asked_seven"] = []
            save_state(st)
        if st.get("last_asked") == today.isoformat():
            return {"due": False, "phase": "bootstrap", "question": "",
                    "lines": lines, "reason": "今日はもう聞いた"}
        idx = remaining[0]
        return {"due": True, "phase": "bootstrap", "question": SEVEN_QUESTIONS[idx],
                "lines": lines, "reason": "素材帳が%d行（%d行未満）" % (lines, BOOTSTRAP_LINES),
                "_idx": idx}

    # ── 積立フェーズ：週1で巡回3問。素材が3行以上あっても止めない
    last = st.get("last_asked") or st.get("last_answered") or ""
    try:
        last_d = datetime.date.fromisoformat(last) if last else None
    except ValueError:
        last_d = None
    if last_d and (today - last_d).days < WEEKLY_INTERVAL_DAYS:
        return {"due": False, "phase": "weekly", "question": "",
                "lines": lines,
                "reason": "前回から%d日（%d日ごと）" % ((today - last_d).days, WEEKLY_INTERVAL_DAYS)}
    # 週替わりで巡回（週番号で回す＝毎回同じ問いにならない）
    q = WEEKLY_QUESTIONS[today.isocalendar()[1] % len(WEEKLY_QUESTIONS)]
    return {"due": True, "phase": "weekly", "question": q, "lines": lines,
            "reason": "前回から%s日" % ((today - last_d).days if last_d else "初回")}


def mark_asked(idx: int = None) -> None:
    """聞いたことを記録する（完了痕跡）。呼ばないと同じ問いを毎日出し続ける。"""
    st = load_state()
    st["last_asked"] = _today().isoformat()
    if idx is not None:
        asked = list(st.get("asked_seven", []))
        if idx not in asked:
            asked.append(idx)
        st["asked_seven"] = asked
    save_state(st)


def issue_note() -> str:
    """顧客が必ず見る場所（承認申請コメント）に出す1行を作る。

    ⚠️ 長く書かない。毎日出るものなので、長いと読み飛ばされて無音と同じになる。
       期日でない日は空文字を返す（＝何も出さない）。
    """
    r = next_question()
    if not r["due"]:
        return ""
    if r["phase"] == "bootstrap":
        head = "📝 投稿を「あなたにしか書けない内容」にするために、1つだけ教えてください"
        tail = ("（Claude Code に答えを言うだけでOKです。今は素材が%d行なので、"
                "投稿が一般論寄りになっています）" % r["lines"])
    else:
        head = "📝 今週の素材を1つだけ足させてください"
        tail = "（Claude Code に答えを言うだけでOKです。1行増えるだけで来週の投稿が変わります）"
    mark_asked(r.get("_idx"))
    return "%s\n\n> %s\n\n%s" % (head, r["question"], tail)


# ── コマンドラインから呼べるようにする（2026-09-10 追加）─────────────
# なぜ在るか：
#   「会話の最初に素材帳を見て、足りなければ聞く」を CLAUDE.md に**散文で**書いても、
#   実行されるかどうかが Claude の判断に委ねられる（＝運営側 CLAUDE.md が
#   「散文の定例は動かない」と結論づけている形そのもの）。
#   そこで**1コマンド叩けば答えが返る**形にし、CLAUDE.md 側は
#   「これを実行して、出力があればそのまま聞く」とだけ書く。判断を残さない。
#
# 使い方:
#   python scripts/utils/material_prompt.py            … 今日聞くべき1問（無ければ無出力）
#   python scripts/utils/material_prompt.py --status   … 状態だけ表示（聞いた記録は残さない）
#   python scripts/utils/material_prompt.py --after-update
#        … キット更新直後に1回だけ使う。7問をまとめて出す（前回いつ聞いたかを無視する）

UPDATE_MARK = os.path.join(_SCRIPTS_DIR, "..", "operation", "config", ".update_pending")


def after_update_note() -> str:
    """キットを更新した直後に、Claude が顧客へ出す文面。

    素材帳が既に埋まっている人には出さない（更新のたびに聞かれたら鬱陶しいため）。

    ⚠️ 2026-09-10 文面改訂：以前は「いま素材帳が0行なので、投稿は検索で誰でも
       書ける内容に寄りやすい状態です」と現状の弱点から入っていた。
       これは受け取る側を不安にさせる書き方なので、**良くなることの方を書く**。
       伝えるべきは「今こうなっている」ではなく「答えるとこう変わる」。
    """
    if count_material_lines() >= BOOTSTRAP_LINES:
        return ""
    qs = "\n".join("%d. %s" % (i + 1, q) for i, q in enumerate(SEVEN_QUESTIONS))
    return (
        "キットを更新しました。今回から、**あなたの話を投稿の材料に使える**ようになっています。\n"
        "一般的な情報はこれまでどおり自動で裏を取って揃えます。"
        "そこに**あなただけの話**が1行入ると、投稿の中身がはっきり変わります。\n\n"
        "7つだけ聞かせてください。**答えられるものだけでOK**です。1つ埋まるだけで効きます。\n\n"
        "%s\n\n"
        "（答えていただいた内容は operation/my_material.md に私が書き込みます。"
        "実測では、この7つに答えると1投稿の中身が約2倍に濃くなり、"
        "読者がその日のうちに試せる具体策が入るようになりました）" % qs
    )

def clear_update_mark() -> None:
    """更新直後の呼びかけを1回で終わらせる（毎回聞かないため）"""
    try:
        if os.path.exists(UPDATE_MARK):
            os.remove(UPDATE_MARK)
    except OSError:
        pass


def _main(argv) -> int:
    args = set(argv[1:])
    if "--status" in args:
        st = load_state()
        r = next_question()
        print("素材帳の実記入: %d行" % count_material_lines())
        print("フェーズ: %s / 今日聞くべきか: %s（%s）" % (r["phase"], r["due"], r["reason"]))
        print("更新直後の呼びかけ待ち: %s" % os.path.exists(UPDATE_MARK))
        print("最後に聞いた日: %s / 最後に素材が増えた日: %s"
              % (st.get("last_asked") or "-", st.get("last_answered") or "-"))
        return 0
    if "--after-update" in args or os.path.exists(UPDATE_MARK):
        note = after_update_note()
        clear_update_mark()
        if note:
            print(note)
            mark_asked()
        return 0
    r = next_question()
    if not r["due"]:
        return 0
    print(r["question"])
    mark_asked(r.get("_idx"))
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_main(_sys.argv))
