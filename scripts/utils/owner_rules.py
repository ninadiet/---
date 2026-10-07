# -*- coding: utf-8 -*-
"""owner_rules.py — オーナーが自分で足したルールファイルを、実際に効かせる

なぜ在るか（2026-08-24 新設・顧客報告）
──────────────────────────────────────────────────────────
顧客が `operation/writing_rules_owner.md` を用意し、テーマファイルからも
参照するよう書いていたのに、「？記号を使わない」というルールが守られなかった。

調べたところ、**このファイルを読むコードはキットに1行も無かった**。
守られなかったのではなく、最初から届いていなかった。

原因は、読み込むファイルが2つに固定されていたこと（声定義とプロンプトルール）。
顧客が何を足しても機械には見えない。マークダウンに「参照せよ」と書いても、
リンクをたどる仕組みは無いので何も起きない。

対策は2段構え：
  ① オーナーのルール本文を、執筆と校閲の両方に**必ず渡す**（届かせる）
  ② そのうち機械で判定できる形の行（「〜は使わない」等）は**抽出して機械が弾く**
     （LLMに読ませるだけでは、前回の 〇〇 の件と同じで素通りしうる）
"""
import os
import re

OPERATION_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "operation")

# オーナーが自分で足したと判断するファイル名の形。
# 「_owner」を含む md と、writing_rules で始まる md を拾う。
# 固定の許可リストにしないのは、また同じ穴（足しても見えない）を作らないため。
OWNER_FILE_RX = re.compile(r"(?:_owner|^writing_rules|^owner_)", re.I)


def find_owner_files() -> list:
    """operation 配下からオーナー独自ルールのファイルを探す"""
    found = []
    for root, _dirs, files in os.walk(OPERATION_DIR):
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            if OWNER_FILE_RX.search(os.path.splitext(fn)[0]):
                found.append(os.path.join(root, fn))
    return sorted(found)


# ⚠️ 2026-09-08 追加：未記入の雛形を「オーナーが決めたルール」として渡さない。
# 実測：新規利用者の出荷状態で、参考帳の**使い方の説明と記入例**が
#   「オーナーが決めたルール（最優先・キット標準より強い）」として
#   執筆プロンプトに入っていた（例文の「知ってた？で始める」が最優先ルールになる）。
# 素材帳（load_my_material）と同じ規則で落とす。
def _strip_template(body: str) -> str:
    lines = []
    for ln in (body or "").splitlines():
        t = ln.strip()
        if not t or t.startswith(("#", ">", "---", "|")):
            continue
        if t.lstrip("-*・ ").startswith("（例）"):
            continue
        if t.startswith("⚠"):
            continue
        lines.append(t)
    return chr(10).join(lines).strip()


def load_owner_rules() -> str:
    """オーナー独自ルールの本文をまとめて返す（執筆・校閲の両方に渡す）"""
    parts = []
    for p in find_owner_files():
        try:
            with open(p, "r", encoding="utf-8") as f:
                body = _strip_template(f.read())
        except OSError:
            continue
        if body:
            parts.append("【オーナー独自ルール %s】\n%s" % (os.path.basename(p), body))
    return "\n\n".join(parts)


# ── 機械で判定できる行の抽出 ────────────────────────────────────────
# 「本文で？記号は使わない」のような、対象がはっきり短い禁止だけを拾う。
# 長い文や条件付きの指示は機械には判定できないので拾わない（誤爆を避ける）。
_BAN_RX = [
    re.compile(r"[「『\"]([^」』\"]{1,8})[」』\"]\s*(?:記号)?\s*(?:は|を)?\s*(?:使わない|使用しない|入れない|書かない|禁止)"),
    re.compile(r"([^\s、。]{1,4})\s*記号\s*(?:は|を)?\s*(?:使わない|使用しない|入れない|禁止)"),
]
# 「例外は〜」「ただし〜」を含む行は、条件付き＝機械では判定しきれないので拾わない
_EXCEPTION_RX = re.compile(r"例外|ただし|除く|を除き|場合のみ|に限り")


def extract_banned_tokens() -> list:
    """オーナールールから「使わない文字・語」を取り出す。

    返すのは (トークン, 出典の行) のリスト。
    条件付き（例外あり）の行は**あえて拾わない**＝機械が誤って弾かないため。
    拾えなかった行も、本文としては①でLLMに渡っているので無視されるわけではない。
    """
    out = []
    for p in find_owner_files():
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if _EXCEPTION_RX.search(s):
                continue
            for rx in _BAN_RX:
                m = rx.search(s)
                if m:
                    tok = m.group(1).strip()
                    if tok and len(tok) <= 8:
                        out.append((tok, s[:80]))
                    break
    # 重複を除く（同じトークンが複数行に出ても1回でよい）
    seen, uniq = set(), []
    for tok, src in out:
        if tok not in seen:
            seen.add(tok)
            uniq.append((tok, src))
    return uniq


def find_owner_rule_violations(text: str) -> list:
    """投稿本文がオーナールール（機械判定できる分）に違反していないか"""
    hits = []
    body = text or ""
    for tok, src in extract_banned_tokens():
        if tok in body:
            i = body.find(tok)
            frag = " ".join(body[max(0, i - 16): i + len(tok) + 16].split())
            hits.append("「%s」を使わない、というルールに違反（…%s…）／出典: %s"
                        % (tok, frag, src))
    return hits
