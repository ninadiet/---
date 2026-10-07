# -*- coding: utf-8 -*-
"""fact_guard.py — 「根拠のないことを書かせない」ための出口の関所

なぜ在るか（2026-08-24 新設・顧客報告）
──────────────────────────────────────────────────────────
顧客から2件の報告が来た。
  ・実在の海外通販サイト名が、本人が使っているか確認されないまま
    「愛用している」という体で本文に入った（たまたま実際に使っていて事なきを得た）
  ・「プロフィールから無料の受け取りガイドを公開している」と書かれたが、
    そんなガイドは存在しない

調べたところ、これは誤作動ではなく**指示どおりの動作**だった。
執筆のプロンプトは「**実在するものだけを書く**」と要求している。
その通販サイトは実在する。つまり条件は満たしている。
「**本人が実際に使っているか**」を要求している行は、どこにも無かった。
存在しない特典への誘導を禁じる行も無かった。

これまでの直し方（社内用語のリストを足す等）は症状を1つずつ潰すやり方で、
穴そのもの＝「根拠が無くても書いてよい」は残っていた。だから形を変えて再発した。

そこで判定基準を変える：
  ×「実在するか」（機械には確かめられないし、実在しても嘘になる）
  ○「**顧客の手元のファイルに根拠があるか**」（機械に確かめられる）

根拠＝顧客が用意したもの全部（声定義・テーマ・設定・オーナールール・過去の投稿）。
ここに出てこない固有名詞を「愛用している」と書いたり、
ここに書かれていない配布物へ誘導したら、差し戻す。

⚠️ 精度について（正直に書いておく）
  ラテン文字の固有名詞（iHerb 等）と、配布・特典への誘導は、
  形が決まっているので機械で高い精度で拾える。
  一方カタカナ語（ハーブティー等）は普通名詞と区別がつかないので、
  ここでは**使用の断定と一緒に出た時だけ**拾う。
  それでも取りこぼす分は、プロンプト側の指示と本人の承認で受ける。
"""
import glob
import json
import os
import re

OPERATION_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "operation")

# ── 根拠として読むもの（顧客が用意したファイル全部）──────────────────
_CORPUS_GLOBS = [
    "knowledge/*.md", "themes/*.md", "config/*.json", "config/*.yaml",
    "weekly/*.md", "*.md", "memory/post_history.jsonl",
]

# 日本語の投稿に自然に出るラテン語＝ブランド名ではないので除外する
_LATIN_ALLOW = {
    "sns", "ai", "pr", "ng", "ok", "url", "dm", "tv", "pc", "id", "qa",
    "line", "threads", "instagram", "x", "note", "youtube", "tiktok",
    "facebook", "google", "gpt", "chatgpt", "claude", "gemini",
    "er", "kpi", "diy", "uv", "led", "usb", "wifi", "ec", "cm", "ml", "kg",
}

# 「本人が使っている」と断定する言い方
_USAGE_RX = re.compile(
    r"(愛用|使ってる|使っている|使用してる|使ってます|買った|購入した|届いた|"
    r"リピート|定期便|飲んでる|飲んでいる|取り寄せ|愛飲)")

# 配布物・特典・リンク先へ誘導する言い方（形が決まっているので拾いやすい）
_OFFER_RX = re.compile(
    r"(プロフィール(?:から|の)|プロフ(?:から|の)|ハイライト(?:から|に)|"
    r"固定(?:投稿|ポスト)(?:から|に)|"
    r"無料(?:で)?(?:配布|プレゼント|公開|配って|お渡し|受け取)|"
    r"受け取(?:り|って|れます)|"
    r"(?:ガイド|テンプレ|テンプレート|シート|チェックリスト|マニュアル|PDF|特典)"
    r"(?:を)?(?:公開|配布|用意|置いて|プレゼント)|"
    r"コメント(?:欄)?(?:に|で)[^\n]{0,12}(?:送|書い|くれたら)|"
    r"DM(?:で|して)|リンク(?:は|から)[^\n]{0,10}(?:プロフ|概要))")


def load_corpus() -> str:
    """顧客が用意したファイルを全部つなげて「根拠」にする"""
    parts = []
    for pat in _CORPUS_GLOBS:
        for p in glob.glob(os.path.join(OPERATION_DIR, pat)):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    parts.append(f.read())
            except (OSError, UnicodeDecodeError):
                continue
    return "\n".join(parts)


def _latin_tokens(text: str) -> list:
    """本文に出てくるラテン文字の語（＝ほぼブランド名）

    ⚠️ 2026-08-25 修正（診断で発覚）：URLを除去せずに走査していたため、
    アフィリリンクがドメインやパラメータの断片に分解され、全部
    「根拠のない固有名詞」として差し戻されていた。リンクは検査対象から外す。"""
    text = re.sub(r"https?://\S+", "", text or "")
    out = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9&.\-']{2,}", text or ""):
        w = m.group()
        if w.lower().strip(".-'") in _LATIN_ALLOW:
            continue
        out.append((w, m.start()))
    return out


def _katakana_tokens(text: str) -> list:
    """カタカナの連なり（普通名詞も混ざるので、使用の断定とセットの時だけ使う）"""
    return [(m.group(), m.start())
            for m in re.finditer(r"[ァ-ヴー]{4,}", text or "")]


def _context(text: str, i: int, w: str, span: int = 20) -> str:
    return " ".join(text[max(0, i - span): i + len(w) + span].split())


def find_ungrounded(post_text: str, corpus: str = None) -> list:
    """根拠のない固有名詞・特典誘導を返す。空なら合格。"""
    text = post_text or ""
    corpus = load_corpus() if corpus is None else corpus
    low_corpus = corpus.lower()
    hits = []

    # ① ラテン文字の固有名詞が、顧客のどのファイルにも出てこない
    seen = set()
    for w, i in _latin_tokens(text):
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        if key in low_corpus:
            continue
        hits.append("根拠のない固有名詞「%s」（…%s…）→ この名前を外し、固有名詞なしの言い方に書き直すこと"
                        "（利用者の方へ: 実際に使っている物なら、声定義かテーマファイルに一言書けば次から通ります）"
                    % (w, _context(text, i, w)))

    # ② カタカナ語＋「愛用してる」等の断定が、根拠に無い
    for w, i in _katakana_tokens(text):
        if w in corpus:
            continue
        around = text[max(0, i - 30): i + len(w) + 30]
        if _USAGE_RX.search(around):
            hits.append("使っていると断定している「%s」（…%s…）／根拠が見つからない"
                        % (w, _context(text, i, w)))

    # ③ 配布物・特典への誘導。根拠になる記述が顧客のファイルに無ければ捏造扱い。
    for m in _OFFER_RX.finditer(text):
        frag = _context(text, m.start(), m.group(), 24)
        # 顧客が実際に配布物を持っているなら、根拠側にその語が出ているはず
        anchor = m.group()[:6]
        if anchor and anchor in corpus:
            continue
        hits.append("存在が確認できない配布物・特典への誘導（…%s…）／"
                    "顧客のファイルに、その配布物の記述が無い" % frag)

    # 同じ指摘が何度も出ても読みにくいだけなので、まとめる
    uniq, seen2 = [], set()
    for h in hits:
        k = h[:40]
        if k not in seen2:
            seen2.add(k)
            uniq.append(h)
    return uniq
