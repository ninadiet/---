r"""voice_rules.py
声定義（operation/knowledge/buzz_posts.md「B. 口調・文体」）から
語尾・読者への呼びかけを取り出す**唯一の正**（2026-09-07 新設）。

■ なぜ共通化したか（2つの実害）
1. **改行またぎ**：writer 側の抽出は `…[：:]\s*(.+)` で、`\s*` が**改行をまたぐ**
   構造だった。出荷テンプレで壊れて見えなかったのは、値が `{{…}}` で始まり
   `val[:2] in ('{{','｛｛')` に引っかかるという**偶然**にすぎない。
   顧客がテンプレ文言を消して値を空のまま残すと、実測で次行の
   `- **一人称**: 私` を語尾として掴んだ（＝隣の項目を語尾だと思い込む）。
   → 抽出は `[^\n]*` で**行内完結**にする。改行の先は絶対に見ない。
2. **見出し語の不一致**：writer は「よく使う語尾｜基本の語尾」の両方を読むのに、
   content_review は「基本の語尾」しか見なかった。実測で、見出しを
   「よく使う語尾」にした声定義では writer='「ですわ / ますのよ」' に対し
   content_review=[] となり、**同じキットの中で書き手と校閲が別の真実を持つ**
   （＝声定義どおりに書いた文を校閲が語尾違反で差し戻し、MAX_RETRY を
   使い切ってその日の投稿がゼロになる）。
   → 見出し語・未記入判定・例文除去を**この1ファイルに集約**し、両者が同じ関数を呼ぶ。

■ 未記入の扱い（＝docstring と実挙動を一致させる）
次のいずれかは「記入なし」＝ `''` / `[]` を返す。呼び出し側は語尾で判定しない。
  - 行そのものが無い
  - 値が空（次行を拾いに行かない）
  - `{{…}}` `｛｛…｝｝` のテンプレ記入例しか無い
  - 「設定してください」等の未記入マーカーを含む
  - 「（例：…）」「例：…」だけ
  - 記号・約物しか残らない（例：`／` `-` `—`）
"""

import re

# 行内完結（[^\n]* ＝ 改行の手前で必ず止まる）。見出し語は2種類とも拾う。
_SUFFIX_LINE_RX = re.compile(
    r"^[-*・\s]*(?:よく使う語尾|基本の語尾)\*{0,2}\s*[：:]([^\n]*)",
    re.MULTILINE,
)
_CALL_LINE_RX = re.compile(
    r"^[-*・\s]*(?:読者への呼びかけ|呼びかけ)\*{0,2}\s*[：:]([^\n]*)",
    re.MULTILINE,
)

_TEMPLATE_RX = re.compile(r"\{\{[^}]*\}\}|｛｛[^｝]*｝｝")
_LEAD_EXAMPLE_RX = re.compile(r"^\s*[（(]\s*例\s*[：:]?[^）)]*[）)]\s*")
_HEAD_EXAMPLE_RX = re.compile(r"^\s*(?:例|例えば|ex|EX|Ex)\s*[：:]\s*")
_MEANINGFUL_RX = re.compile(r"[0-9A-Za-z\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")
_POLITE_RX = re.compile(r"(です|ます|ましょ|ません|ください|下さい|でしょ)")

_UNSET_MARKERS = (
    "設定してください", "記入してください", "ここに記入",
    "ここにあなた", "未記入", "記入例",
)
_VOICE_NOISE = {"など", "等", "他", "その他", "系", "羅列", "を羅列", "例", "ex", "なし"}


def _clean_value(raw: str) -> str:
    """1行から取り出した生の値を、未記入なら '' に潰して返す"""
    val = (raw or "").strip()
    val = val.strip("*").strip()          # 太字マーカー **…** を落とす
    val = _LEAD_EXAMPLE_RX.sub("", val)   # 先頭の「（例：…）」を落とす
    val = _HEAD_EXAMPLE_RX.sub("", val)   # 先頭の「例：」を落とす
    val = val.strip()
    if not val:
        return ""
    if any(marker in val for marker in _UNSET_MARKERS):
        return ""
    if not _TEMPLATE_RX.sub("", val).strip():   # テンプレ記入例しか無い
        return ""
    if not _MEANINGFUL_RX.search(val):          # 記号・約物しか残っていない
        return ""
    return val


def extract_suffix_value(voice_def: str) -> str:
    """声定義の「よく使う語尾／基本の語尾」の**行内の値**を返す（未記入なら ''）"""
    m = _SUFFIX_LINE_RX.search(voice_def or "")
    return _clean_value(m.group(1)) if m else ""


def extract_call_value(voice_def: str) -> str:
    """声定義の「読者への呼びかけ」の**行内の値**を返す（未記入なら ''）"""
    m = _CALL_LINE_RX.search(voice_def or "")
    return _clean_value(m.group(1)) if m else ""


def split_voice_values(raw: str) -> list:
    """『「だよ」「だね」／だよね など』のような1行から、語の並びだけを取り出す"""
    raw = _TEMPLATE_RX.sub(" ", raw or "")
    raw = re.sub(r"[（(][^）)]*[）)]", " ", raw)        # 補足の括弧書きは落とす
    raw = re.sub(r"^\s*(?:例|例えば|ex)\s*[:：]?\s*", "", raw)
    out = []
    for p in re.split(r"[「」『』、，,/／・|｜\s]+", raw):
        p = p.strip().strip("。.、､")
        p = p.lstrip("〜~ー")
        if not p or len(p) > 8 or p in _VOICE_NOISE:
            continue
        if p not in out:
            out.append(p)
    return out[:12]


def extract_voice_suffixes(voice_def: str) -> str:
    """【writer 用】語尾を生の1行文字列で返す（未記入なら ''）"""
    return extract_suffix_value(voice_def)


def extract_voice_suffix_list(voice_def: str) -> list:
    """【校閲用】語尾を語の並びにして返す（未記入なら []）。
    元は extract_suffix_value と同じ1行なので、writer と真実がズレない。"""
    return split_voice_values(extract_suffix_value(voice_def))


def extract_voice_call_list(voice_def: str) -> list:
    """【校閲用】読者への呼びかけを語の並びにして返す（未記入なら []）"""
    return split_voice_values(extract_call_value(voice_def))


def has_polite_suffix(suffixes) -> bool:
    """声定義の語尾が丁寧語ベースか（＝丁寧語を差し戻し理由にしてはいけないか）"""
    if isinstance(suffixes, str):
        suffixes = split_voice_values(suffixes)
    return any(_POLITE_RX.search(s) for s in (suffixes or []))
