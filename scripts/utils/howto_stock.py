# -*- coding: utf-8 -*-
"""howto_stock.py — 「手の内ストック」を持ち回す（2026-09-12 新設）

⚠️ このファイルは ③アフィリ / ④ホグ の両キットで**バイト単位で同一**にすること。

なぜ在るか
──────────────────────────────────────────────────────────
本人指摘（2026-09-12）＝「投稿の中身が薄い。フォローして即使えるものにしてほしい」。
実測で原因まで辿った：

  ・7日通し（21スロット）で、**後半2日に❌が固まった**
    d1○○○ d2○○○ d3○○○ d4○❌○ d5○○○ d6○❌❌ d7○❌❌
  ・題材も 要約13／メール10／資料8／議事録7 と、同じ4つを7日間回していた
  ・原因は素材帳が7行しかなく、**具体の種が5日で尽きる**こと

ここで最初に考えた「素材帳をもっと書いてもらう」は**間違い**だった（本人指摘）：

  「使用顧客自身が自分で素材を入れないと結果同じになるのでは危険かと思います」

そのとおりで、素材帳を埋めない顧客が大半である以上、
**素材帳が空でも具体が出る**状態にしないと同じ苦情が来る。

そこで材料を2つに分ける。ここがこのファイルの設計の核。

  ┌ 体験・失敗・立場（「私はこう失敗した」）
  │   → その人しか持っていない。**機械が作ったら捏造**。素材帳(my_material.md)が正。
  └ やり方の具体（打ち込む文・手順・設定・上限）
      → 世の中に公開されている**事実**。その人が持っている必要はない。
        ここを埋めるのがこのファイル。

さらに本人指摘＝「多ジャンル（AI・日用品・育児…）に効くようにできるのか？
　　　　　　　　　　顧客ごとにジャンルに応じて顧客のClaude Code自身が埋めるのはできないの？」
→ できる。運営は**中身を同梱しない**。同梱するのは「作り方（合格ライン）」だけで、
  中身は各顧客の Claude Code が**その顧客のジャンル**で生成する。
  これで全ジャンルに効き、かつ顧客ごとに中身が散る（＝投稿が似ない）。

3層のどこに居るか
──────────────────────────────────────────────────────────
  ① 手の内ストック（このファイル）… 土台。具体の供給源。素材帳が空でも効く
  ② 素材帳 my_material.md          … 角度。その人にしか書けない体験
  ③ 裏取り web_research.py（🔎）   … ①②で足りない日・題材が被る日の補充

ファイルの形
──────────────────────────────────────────────────────────
`operation/my_howto.md` に `- ` 始まりで1件1行。使った項目は行末に ` ✔YYYY-MM-DD` が付く。
状態ファイルを別に作らないのは、**顧客が中身をそのまま読めて、要らない行を消せる**ようにするため
（本人裁定：中身は見せる・消せる・承認は求めない）。
"""

import os
import re
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_UTILS_DIR)
STOCK_PATH = os.path.join(_SCRIPTS_DIR, "..", "operation", "my_howto.md")

#: 1日に投稿プロンプトへ渡す件数（3スロットぶん）
DAILY_PICK = 3
#: 未使用がこれを下回ったら補充する
TOPUP_THRESHOLD = 9
#: 生成時に目標とする件数
TARGET_ENTRIES = 30

# 使用印。★は「実測で伸びた」印（→ 一定日数あけて再登板する）。
# 例: 「- 本文 ✔2026-09-12#S1 ★」
_USED_RX = re.compile(r"\s*✔(\d{4}-\d{2}-\d{2})(?:#S([123]))?\s*(★)?\s*$")
#: 伸びた項目を再び使えるようにするまでの日数（同じ話が続けて出ないように間を空ける）
REVIVE_AFTER_DAYS = 21

# ── 合格ライン（生成時も、日々の投入時も、同じ物差しで見る）──────────
# ⚠️ ここを緩めると「〜を意識する」だけの項目がストックに溜まり、
#    結局いまと同じ薄い投稿に戻る。緩めないこと。
_INSTR_RX = re.compile(r"[「『][^」』]{10,}[」』]")          # そのまま貼れる文
_STEP_RX = re.compile(r"①.{0,60}②|1\).{0,60}2\)|まず.{0,30}次に")   # 番号付き手順
# 数量の判定。
# ⚠️ 2026-09-12 作り直し。最初は単位を列挙していたが、ジャンルが変わるたびに
#    「メートル」「箇所」「種類」…と**足し続けることになった**（本人指摘：対処法が間違い）。
#    列挙をやめ、**形**で見る：数字の直後が助詞でなければ数量とみなす。
#    「3つ」「40枚」「1メートル」「5ステップ」全部通る。単位を足す作業が二度と要らない。
#    ❌にしたいのは「Claude 3を使う」のような**ただの番号**なので、助詞だけ除外すれば足りる。
_NUM_RX = re.compile(r"[0-9０-９]+\s*(?![をはがのにとでもやか、。．！？!?\s\d])[^\s]")
# 漢数字（「八分目」「三日に一回」）。
# ⚠️ ここだけ列挙が残るのは、漢数字が**本当に紛らわしい**から
#    （「十分」＝じゅうぶん／10分、「一般」「一番」「一方」）。
#    ただしこれは“単位の一覧”ではなく“取り違えない組み合わせ”なので、
#    ジャンルが増えても足す必要はない（アラビア数字側が全部拾う）。
_KANJI_NUM_RX = re.compile(r"[一二三四五六七八九十百][\s]*(分目|回|個|枚|本|日|週間|ヶ月|か月|文字|割)")
_VAGUE_RX = re.compile(r"(意識す|心がけ|が大事|が重要|使い分け|気をつけ)")


#: ファイルが無い日に自分で用意する見出し（顧客がそのまま読める形にしておく）
_STOCK_HEADER = """# 手の内ストック（そのまま真似できるやり方を溜める場所）

> **あなたが書く必要はありません。** あなたのジャンルに合わせてClaudeが自動で作り、
> 足りなくなったら自動で補充します。**要らない行は消して構いません。**
> 使った行の末尾には `✔日付` が付き、実測で伸びた行には `★` が付いて後日また使われます。
>
> ここは**やり方**を置く場所です。あなた自身の体験・失敗は `my_material.md` に置きます。

## 一覧
"""


def _today(anchor: str = "") -> datetime.date:
    if anchor:
        try:
            return datetime.date.fromisoformat(anchor[:10])
        except ValueError:
            pass
    return datetime.datetime.now(JST).date()


def _read() -> list:
    """[(本文, 使用日 or ""), ...] を返す。ファイルが無くても落ちない。"""
    try:
        with open(STOCK_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    # ⚠️ 「## 一覧」より後ろだけを読む。
    #    説明文にも箇条書きがあるので、ファイル全体を読むと
    #    「使った行は末尾に✔日付が付きます」のような**説明文が手の内として投稿に混ざる**
    #    （2026-09-12 実測で実際に起きた。素材帳で同じ穴を塞いだのと同じ型）。
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("## 一覧"):
            start = i + 1
            break
    else:
        return []        # 見出しが無いファイル＝まだ作られていない。空として扱う
    out = []
    for ln in lines[start:]:
        s = ln.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        m = _USED_RX.search(body)
        if m:
            out.append({"text": body[:m.start()].strip(), "used": m.group(1),
                        "slot": m.group(2) or "", "win": bool(m.group(3))})
        else:
            out.append({"text": body, "used": "", "slot": "", "win": False})
    return out


# ── 作り方の説明語が中身に混ざっていないか（2026-09-12 追加）──────────
# 実測：自動生成30件のうち3件に「公式の仕様・上限・目安の数字を記載する」
# 「そのまま貼れる文で入力する」「単位つきの数字で指定する」が本文として入っていた。
# 形（数字・手順）は満たすので _NUM_RX / _STEP_RX では止まらない。ここで止める。
_META_RX = re.compile(
    r"そのまま貼れる|単位つき|単位付き|番号付き|目安の数字|仕様・上限|"
    r"合格ライン|不合格|箇条書きで出して|読者が今日そのまま")


# ── 理由が付いているか（2026-09-12 追加・実測から）────────────────
# 手書きストック（1件39字・73%が「。」で理由が続く）→ 投稿は1投稿98字になった。
# 自動生成ストック（1件57字・理由0%・操作だけ）    → 投稿は1投稿40字に落ちた。
# **長さではなく、理由が入っているかで決まる。** 理由が無いと書き手に膨らませる材料が無く、
# 「深く書け」と指示しても効かない（実測で55字→40字とさらに痩せた）。
# ⚠️ 「から」「ので」を手がかりにするのは**やめた**。助詞の「から」
#    （「一覧から、〜を消す」「これから送る〜」）と区別できず、操作だけの行が3件通った。
#    実測の差はもっと単純で、**手書き（効いた方）は73%が「。」で2文**、
#    自動生成（痩せた方）は「。」0%だった。**2文になっているか**で見る。
_REASON_RX = re.compile(
    r"。.{8,}"            # 「やること。理由」の2文構成（これが本命）
    r"|ると、.{8,}$"       # 「〜すると、こうなる」
    r"|ないと.{8,}$")      # 「〜しないと、こうなる」


def has_reason(text: str) -> bool:
    """「何をするか」だけでなく「そうなる理由・つまずき」が入っていれば True。"""
    return bool(_REASON_RX.search(text or ""))


def has_meta_leak(text: str) -> bool:
    """作り方の説明語が本文に混ざっていれば True。"""
    return bool(_META_RX.search(text or ""))


def entry_ok(text: str) -> bool:
    """1件が合格ラインを満たすか。満たさないものはストックに入れない。"""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    if _VAGUE_RX.search(t) and not (_INSTR_RX.search(t) or _STEP_RX.search(t)):
        return False
    if has_meta_leak(t):          # 作り方の説明語が混ざっている
        return False
    if not has_reason(t):         # 操作だけで理由が無い＝投稿が膨らまない
        return False
    return bool(_INSTR_RX.search(t) or _STEP_RX.search(t)
                or _NUM_RX.search(t) or _KANJI_NUM_RX.search(t))


def quality_report(texts) -> dict:
    """生成直後の検品用。落ちた行をそのまま返すので、作り直しの材料になる。"""
    ok, ng = [], []
    for t in texts:
        (ok if entry_ok(t) else ng).append(t)
    return {"ok": ok, "ng": ng, "n_ok": len(ok), "n_ng": len(ng)}


def _available(rows, anchor: str = "") -> list:
    """今日また使ってよい項目。未使用＋「伸びて、間が空いた」項目。

    ⚠️ 伸びた項目だけ戻す。伸びなかった項目は戻さない
       （戻すと、反応が無かった話を延々と繰り返すことになる）。
    """
    today = _today(anchor)
    out = []
    for r in rows:
        if not r["used"]:
            out.append(r)
            continue
        if not r["win"]:
            continue
        try:
            gap = (today - datetime.date.fromisoformat(r["used"])).days
        except ValueError:
            continue
        if gap >= REVIVE_AFTER_DAYS:
            out.append(r)
    return out


def stats(anchor: str = "") -> dict:
    rows = _read()
    avail = _available(rows, anchor)
    wins = [r for r in rows if r["win"]]
    return {"total": len(rows), "available": len(avail),
            "unused": len([r for r in rows if not r["used"]]),
            "used": len([r for r in rows if r["used"]]),
            "wins": len(wins),
            "needs_topup": len(avail) < TOPUP_THRESHOLD}


def select_today(n: int = DAILY_PICK, anchor: str = "") -> list:
    """今日プロンプトへ渡す項目を選ぶ。

    ・未使用を古い順（ファイルの並び順）に取る＝毎日ちがう項目が出る
    ・同じ日に何度呼んでも同じ結果（差し戻し再生成でブレない）
    ・未使用が足りない日は、**いちばん古く使った項目**を回して穴を空けない
      （⚠️ ここで空を返すと、補充が遅れた日に投稿がまた痩せる）
    """
    rows = _read()
    if not rows:
        return []
    avail = _available(rows, anchor)
    # 伸びた項目を先に出す（実測で効いたものを優先して当てにいく）
    avail.sort(key=lambda r: (0 if r["win"] else 1, r["used"]))
    if len(avail) >= n:
        return [r["text"] for r in avail[:n]]
    # 足りない日は、いちばん古く使った項目で穴を埋める
    # （⚠️ ここで空を返すと、補充が遅れた日に投稿がまた痩せる）
    rest = sorted([r for r in rows if r not in avail], key=lambda r: r["used"])
    return [r["text"] for r in avail] + [r["text"] for r in rest[: n - len(avail)]]


def mark_used(texts, anchor: str = "", slots=None) -> int:
    """使った項目の行末に ✔日付#Sn を付ける。すでに今日の印がある行は触らない。

    slots: texts と同じ並びのスロット番号（["1","2","3"] 等）。
           あとで実測（閲覧数）と突き合わせるために持っておく。
    """
    if not texts:
        return 0
    day = _today(anchor).isoformat()
    slot_of = {}
    if slots:
        for t, s in zip(texts, slots):
            slot_of[t.strip()] = str(s)
    try:
        with open(STOCK_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return 0
    want = {t.strip() for t in texts}
    n = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        m = _USED_RX.search(body)
        core = body[:m.start()].strip() if m else body
        if core in want and (not m or m.group(1) != day):
            indent = ln[: len(ln) - len(ln.lstrip())]
            sl = slot_of.get(core, "")
            star = " ★" if (m and m.group(3)) else ""
            lines[i] = "%s- %s ✔%s%s%s" % (
                indent, core, day, ("#S" + sl) if sl else "", star)
            n += 1
    if n:
        with open(STOCK_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return n


def prompt_block(n: int = DAILY_PICK, anchor: str = "") -> str:
    """執筆プロンプトへ入れる文字列。空なら空文字（＝何も足さない）。"""
    picked = select_today(n, anchor)
    if not picked:
        return ""
    out = ["## 🧰 今日つかえる「手の内」（この中から必ず1つ以上を本文に入れる）", ""]
    for t in picked:
        out.append("- " + t)
    out += [
        "",
        "⚠️ これは**やり方の具体**であって、あなたの体験ではない。",
        "　 「私が試したら」と**一人称の体験にすり替えない**（それは捏造になる）。",
        "　 ⭕「やり方としては〜」「手順はこうです」「〜と入れると変わります」",
        "⛔ 貼る文の中に **〇〇 や △△ の空欄を作らない**（機械が『書きかけ』と見て差し戻す・実測2件）。",
        "　 読者が入れ替える所は空欄にせず、**具体例をそのまま書く**",
        "　 （❌「〇〇（会議名）の議事録を」 ⭕「先週の定例会議の議事録を」）。",
        "⚠️ そのまま貼らない。**読者が今日そのまま実行できる形**に整えてから入れる",
        "　 （どこを開く・何と打つ・どこで詰まる・そうすると何が変わる）。",
        "",
        "⛔ **1件を書き写して終わりにしない。** ここに書いてあるのは**芯だけ**で、投稿ではない。",
        "　 実測（2026-09-12）：芯をそのまま1投稿にしたら、1投稿55字・5投稿で227字になった。",
        "　 読者は40字のために4回タップすることになり、ツリーにする意味が無くなる。",
        "　 **1つの投稿の中に**、芯のまわりへ次の3つを書き足して100字以上にすること：",
        "　 ①**どこで詰まるか**（そのままやると何が起きるか・よくある間違い）",
        "　 ②**なぜそれで変わるのか**（理由がわかると読者は応用できる）",
        "　 ③**やったあと何が変わるか**（次に何ができるようになるか）",
        "⛔ **この①②③を投稿ごとに分けない。**分けると1投稿30〜40字になり、",
        "　 読者は40字のために何度もタップすることになる（実測：5投稿で227字）。",
        "　 手順の①②③も同じ。**1つの投稿の中に並べる。**",
        "⛔ 1つのSLOTに芯を2つ3つ詰め込まない。**1つを深く**書く（浅い話を並べると全部薄くなる）。",
        "⚠️ 素材帳（あなた自身の体験）がある日は、**そちらを軸にして**これを具体の補強に使う。",
        "",
    ]
    return "\n".join(out)


def generation_brief(genre: str = "", voice_hint: str = "", n: int = 0) -> str:
    """ストックを作るときにモデルへ渡す文。

    ⚠️ ここに書く言葉は**そのまま中身に写る**。2026-09-12 の実測で、
       「そのまま貼れる文」「単位つきの数字」「番号付きの手順」という
       **作り方の説明語が30件中3件の本文に混ざった**。
       だから要求は「◯◯を入れろ」ではなく、**問い**の形で書く。
    """
    g = (genre or "このアカウントのジャンル").strip()
    want = n or TARGET_ENTRIES
    who = (voice_hint or "").strip()
    who_block = ("## 読者はこういう人です（ここを外すと的外れになります）\n"
                 + who[:1500] + "\n\n") if who else ""
    return f"""「{g}」で発信しているアカウントに向けて、
**読者が今日そのまま真似できること**を {want} 件、箇条書きで出してください。

{who_block}## 1件の書き方
`- ` で始まる1行に、**2つを続けて**書きます。

  〈やること〉。〈そのままだとどうなるか／なぜそうするのか〉

2つ目が無いと、読んだ人は真似はできても**応用ができません**。必ず両方入れてください。

書いたあと、自分で次の3つを確かめてください。
1. 読んだ人は、これを読んだ直後に**何をすればいいか分かりますか**？
2. その人は**もう知っている**話ではありませんか？（知っていたら価値がありません）
3. 上の読者像の人が**実際にやる**ことですか？（専門家向けになっていませんか）

## 書き方の見本（※別ジャンルの例です。この話題は書かないでください）
- 米は炊く30分前に水に浸ける。急ぐと芯が残って、結局炊き直しになる
- ①湯を沸かす ②沸いてから塩を入れる ③麺を入れて7分。先に塩を入れると沸くのが遅くなる
- 焦げついた鍋は水を張って重曹を大さじ1入れ、10分沸かす。こすらないので表面が傷まない

⛔ 見本の**後半（。のあと）を落とさないでください**。そこが無いと使えません。
  ❌「米は炊く30分前に水に浸ける」だけ ← やることしか無い
  ⭕「米は炊く30分前に水に浸ける。急ぐと芯が残って、結局炊き直しになる」

## ⛔ 出さないもの
- 「〜を意識する」「〜が大事」「〜を使い分ける」だけのもの（読んでも動けません）
- **この指示文に出てくる言葉**（「そのまま貼れる」「単位つき」「番号付き」「目安の数字」
  「合格」など）を、書く文の中に入れないでください。これは作り方の説明であって、
  読者に読ませる言葉ではありません
- 誰かの体験や実績（「私は3割減った」など）。ここは**やり方だけ**を置く場所です
- 伏せ字（〇〇・△△）。入れ替える所は具体例をそのまま書いてください

## 出力
説明も前置きも書かず、`- ` で始まる行を {want} 行だけ出してください。
"""

def _read_genre() -> str:
    """このアカウントのジャンルを、キットが既に持っている設定から読む。

    ④は operation/config/research_config.json の topic_genre、
    ③は operation/config/genre_config.yaml のキーワード。どちらも無ければ空。
    """
    import json as _json
    p = os.path.join(_SCRIPTS_DIR, "..", "operation", "config", "research_config.json")
    try:
        with open(p, encoding="utf-8") as f:
            g = str(_json.load(f).get("topic_genre", "")).strip()
        if g:
            return g
    except (OSError, ValueError):
        pass
    p = os.path.join(_SCRIPTS_DIR, "..", "operation", "config", "genre_config.yaml")
    try:
        with open(p, encoding="utf-8") as f:
            words = []
            for ln in f:
                ln = ln.strip()
                if ln.startswith("- ") and "{{" not in ln:
                    words.append(ln[2:].strip().strip('"').strip("'"))
            if words:
                return "・".join(words[:6])
    except OSError:
        pass
    return ""


def ensure_stock(api_key: str = "", genre: str = "", voice_hint: str = "",
                 anchor: str = "") -> dict:
    """足りなければ、その場で自分で作って足す（2026-09-12 新設）。

    なぜ人に頼まないか（本人指摘）：
      ・顧客は0スタートではなく**更新**で入る。「始める」の手順は通らない
      ・「手の内を作って」と言わせるのは、結局**声かけが起動条件**になるのと同じ
    だから、毎日必ず動くこの経路が**自分で作る**。顧客は何もしなくてよい。

    ⚠️ 落ちても投稿は止めない。作れなかった日はストック無しで書く（従来の挙動に戻るだけ）。
    ⚠️ 合格ラインを通らなかった行は**捨てる**。薄い行を入れると投稿がそのぶん薄くなる。
    """
    s = stats(anchor)
    if not s["needs_topup"]:
        return {"added": 0, "reason": "足りている"}
    if not api_key:
        return {"added": 0, "reason": "APIキーが無い"}
    g = (genre or _read_genre()).strip()
    if not g:
        return {"added": 0, "reason": "ジャンルが設定されていない"}

    # ⚠️ 裸の `from gemini_client import ...` を保険で書かないこと。
    #    キットの検査が**外部パッケージのimport**と誤認して「requirementsに無い」と鳴る
    #    （2026-09-12 実測）。キットは常に utils パッケージとして動くので保険は要らない。
    try:
        from utils.gemini_client import call_gemini
    except ImportError as e:
        return {"added": 0, "reason": "gemini_client を読めない（%s）" % e}

    have = {r["text"] for r in _read()}
    want = max(TARGET_ENTRIES - len(have), TOPUP_THRESHOLD)
    prompt = generation_brief(g, voice_hint, want)
    if have:
        prompt += ("\n## すでにあるもの（これとは違う話にしてください）\n"
                   + "\n".join("- " + t for t in sorted(have)[:40]) + "\n")

    try:
        raw = call_gemini(prompt, api_key)
    except Exception as e:
        return {"added": 0, "reason": "生成に失敗（%s）" % e}
    if not raw:
        return {"added": 0, "reason": "生成が空だった"}

    cand = []
    for ln in str(raw).splitlines():
        t = ln.strip()
        if not t.startswith("- "):
            continue
        t = t[2:].strip()
        if t and t not in have and t not in cand and entry_ok(t):
            cand.append(t)
    if not cand:
        return {"added": 0, "reason": "合格する行が1つも無かった"}

    try:
        # ⚠️ ファイルが無い／見出しが無い時は、**見出しごと自分で作る**。
        #    こうしておけば my_howto.md を更新パックに同梱しなくてよくなり、
        #    次の更新で**顧客が貯めた手の内と「伸びた★」を上書きで消す**事故が起きない
        #    （素材帳 my_material.md を同梱から外しているのと同じ理由）。
        need_head = True
        try:
            with open(STOCK_PATH, encoding="utf-8") as f:
                need_head = "## 一覧" not in f.read()
        except OSError:
            pass
        os.makedirs(os.path.dirname(os.path.abspath(STOCK_PATH)), exist_ok=True)
        with open(STOCK_PATH, "a", encoding="utf-8", newline="\n") as f:
            if need_head:
                f.write(_STOCK_HEADER)
            f.write("\n".join("- " + t for t in cand) + "\n")
    except OSError as e:
        return {"added": 0, "reason": "書き込めない（%s）" % e}
    return {"added": len(cand), "reason": ""}

def issue_note(anchor: str = "") -> str:
    """承認申請のコメントに足す1行（2026-09-12 追加・空なら何も足さない）。

    ⚠️ なぜ在るか：手の内ストックを作る手順は CLAUDE.md に**散文で**書いてあるだけだった。
       それはこのキット自身が「動かない」と結論を出している形（＝本人の声かけが起動条件）。
       実際、素材帳の聞き取りが一度も走らない利用者が生まれたのと同じ穴。
       毎日必ず動く生成サイクルに期日判定を持たせ、**顧客が必ず読む場所**に1行だけ出す。
    """
    s = stats(anchor)
    if s["total"] == 0:
        # 自動生成が続けて失敗している状態。ここだけは人に伝える（黙って薄いままにしない）
        return ("🧰 手の内ストック（そのまま真似できるやり方）をまだ用意できていません。"
                "ジャンル設定が空か、生成に失敗しています。"
                "`operation/config` のジャンル設定をご確認ください。")
    # ⚠️ 残りが少ない時は**何も言わない**（本人裁定 2026-09-12）。
    #    自動で補充するのだから、人に伝える必要が無い。伝えると「鳴るだけの通知」になる。
    return ""

def score_day(date_str: str, slot_metrics: dict, anchor: str = "") -> dict:
    """実測（閲覧数）で「伸びた」項目に ★ を付ける（2026-09-12 追加）。

    型（type_engine）は既に同じ実測で勝ち負けを付けている。同じ物差しをここでも使う。
    slot_metrics: {"1": {"views": int, ...}, "2": {...}, "3": {...}}
    ＝ auto_measure が type_engine.score_day に渡しているものと同じ形。

    ⚠️ 判定は type_engine.is_relative_win に任せる（基準を2か所に書かない）。
       読めない・落ちる場合は何もしない（計測は投稿を止めてよい理由にならない）。
    """
    try:
        from utils import type_engine
    except ImportError as e:
        return {"marked": 0, "reason": "type_engine を読めない（%s）" % e}
    try:
        with open(STOCK_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return {"marked": 0, "reason": "ストックが無い"}

    win_slots = set()
    for slot, met in (slot_metrics or {}).items():
        try:
            views = int((met or {}).get("views") or 0)
        except (TypeError, ValueError):
            continue
        try:
            if views and type_engine.is_relative_win(views, anchor=date_str):
                win_slots.add(str(slot))
        except Exception:
            continue
    if not win_slots:
        return {"marked": 0, "reason": "伸びたスロットなし"}

    n = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        m = _USED_RX.search(body)
        if not m or m.group(1) != date_str[:10]:
            continue
        if (m.group(2) or "") not in win_slots:
            continue
        if m.group(3):                      # すでに★
            continue
        lines[i] = ln.rstrip() + " ★"
        n += 1
    if n:
        with open(STOCK_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    return {"marked": n, "reason": ""}

def _cli():
    import sys
    rows = _read()
    if "--check" in sys.argv:
        rep = quality_report([r["text"] for r in rows])
        print("手の内ストック：合格 %d件 / 不合格 %d件" % (rep["n_ok"], rep["n_ng"]))
        for t in rep["ng"][:20]:
            print("  ✗ " + t[:70])
        if rep["n_ng"]:
            print("→ 不合格の行は「貼れる文・番号付き手順・単位つきの数字」のどれかを入れて直す")
        sys.exit(1 if rep["n_ng"] else 0)
    if "--status" in sys.argv:
        s = stats()
        print("合計 %d件／今日使える %d件（未使用 %d・伸びて再登板できる %d）／"
              "使用済み %d件／伸びた %d件／補充が必要: %s"
              % (s["total"], s["available"], s["unused"],
                 s["available"] - s["unused"], s["used"], s["wins"],
                 "はい" if s["needs_topup"] else "いいえ"))
        sys.exit(0)
    if "--today" in sys.argv:
        print(prompt_block() or "(ストックが空です)")
        sys.exit(0)
    print("使い方: howto_stock.py [--check|--status|--today]")


if __name__ == "__main__":
    _cli()
