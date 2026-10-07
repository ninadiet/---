"""
malfoy_review.py
マルフォイ担当: 投稿案3案を厳格に校閲し、承認申請または差し戻しを行うスクリプト
ステップ④: 投稿案取得 → チェック → 承認申請 or 差し戻し
"""

import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))  # 2026-08-26 統一（UTCズレ事故の根絶）
from utils.github_issues import GitHubIssues
from utils.discord_notify import send_approval_request
from utils.gemini_client import call_gemini
from utils import fact_guard, owner_rules, post_history   # 出口の関所（2026-08-24）
from utils.agent_config import name as _n
# 語尾抽出は utils/voice_rules.py に一本化（2026-09-07）。
# 執筆(luna)と校閲(malfoy)が同じ関数を見る＝片方だけ直る事故を構造的に消す。
from utils.voice_rules import extract_voice_suffixes
from utils import voice_rules
from utils import post_guard
from utils import material_prompt          # 2026-09-09（素材帳の聞き取りの期日判定）
from utils import howto_stock             # 2026-09-12（手の内ストックの残量判定）
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MAX_RETRY      = 2   # 差し戻し最大回数


FORBIDDEN_CHARS = ['*', '"', "'", '“', '”', '‘', '’', '`']


def find_forbidden_chars(text: str) -> list[str]:
    """投稿テキストに禁止文字が含まれるか確認する"""
    return [c for c in FORBIDDEN_CHARS if c in text]


def get_luna_posts(issue_number: int, gh: GitHubIssues) -> str:
    """GitHub IssueのコメントからルーナのAB3案を取得する"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('luna')}より" in comment.body and ("投稿案" in comment.body or "3時間帯" in comment.body):
            return comment.body
    return ""


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")


def load_voice_definition() -> str:
    """kb_sys_ref_v001.mdから声定義を読み込む（マルフォイ審査用）"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return ""
    except FileNotFoundError:
        return ""


# ⚠️ 2026-09-09：ここにあった自前の丁寧語判定を削除した。
#   旧実装は ("です","ます","でしょう","ますの","ですわ") だけを見ており、
#   語尾に「〜ください」「〜ませんか」と書いた利用者を**丁寧語だと認識できなかった**。
#   その利用者は声定義どおりに書いても毎日差し戻され、投稿ゼロに倒れる（実測で確認）。
#   ③側は utils/voice_rules.has_polite_suffix を使っており、同じ判定が2か所に
#   別々に書かれて片方だけ古いという、何度も事故を起こしている形だった。
#   以後は voice_rules が唯一の正。ここに自前実装を戻さないこと。
_polite_in_suffix = voice_rules.has_polite_suffix


def review_posts(posts_text: str) -> str:
    """Gemini Flash で投稿案を厳格に校閲する（タイムアウト・フォールバック付き）"""

    voice_def = load_voice_definition()
    logger.info(f"マルフォイ声定義ロード: {len(voice_def)}文字")
    _suf = extract_voice_suffixes(voice_def)
    logger.info(f"マルフォイ語尾抽出: {_suf if _suf else '(未記入→キャラ一貫性で審査)'}")
    # ⚠️ 2026-09-07 修正（実測で回帰を検出）: ここを「指定語尾のみ許可・他は差し戻し」の
    #   **排他的な許可リスト**にしたところ、日本語として成立しなくなった。
    #   語尾を2〜3個しか書いていない顧客は疑問形・過去形・依頼形を作れず、
    #   自然に書けている文章が全スロット差し戻される（実測：関西弁指定の顧客で
    #   「〜へん？」「〜わ」「〜な」が"指定外"として3スロットとも差し戻し）。
    #   ＝ 語尾をきちんと書いた顧客ほど詰まるという、直そうとした問題の逆。
    #   → ③アフィリの content_review.py と同じ **deny-list のみ** の形に戻す。
    #     「書かれた語尾は全て許可」＋「声定義に書かれた語尾を差し戻し理由にしない」を明示し、
    #     禁止するのは"声定義と明らかに違う文体"だけにする。
    if _suf:
        # 顧客が既に「」付きで書いている場合に「「〜やで」」と二重括弧にしない
        _suf_q = _suf if _suf.startswith("「") else f"「{_suf}」"
        _suf_rule = (f"- 許可される語尾: 声定義に書かれた{_suf_q}（ここに書かれた語尾は全て許可）。"
                     f"これらの活用形・疑問形・過去形（例: 〜やで→〜やった／〜へん？）も同じ語尾として許可する")
        _suf_pass = f"声定義の語尾{_suf_q}に沿った文体で書けていればOK"
        _suf_check = "[声定義の語尾に沿っているか。声定義に書かれた語尾とその活用形は指摘しない]"
        if _polite_in_suffix(_suf):
            _polite_rule = ("- 禁止される語尾: なし。声定義が丁寧語ベースなので、"
                            "「〜です」「〜ます」等を差し戻し理由にしてはならない")
        else:
            _polite_rule = ("- 禁止される語尾: 声定義の文体と明らかに違う丁寧語"
                            "（「〜です」「〜ます」「〜ですよ」「〜ませんか」「〜しましょう」「〜ください」）"
                            "。声定義がフランクな話し言葉のため")
    else:
        _suf_rule = ("- 声定義に語尾の指定が無いため、キャラクター設定から一貫した語尾が使えているかを見る"
                     "（一般的な語尾でも、キャラに合っていて一貫していれば許可でよい）")
        _suf_pass = "キャラクター設定に合った語尾が一貫して使われていればOK"
        _suf_check = "[キャラに合って一貫している語尾なら、丁寧語でもフランクでも指摘しない]"
        _polite_rule = ("- 丁寧語（です・ます）: 声定義に語尾の指定が無いので、"
                        "**「です・ます」は差し戻し理由にしてはならない**。"
                        "キャラに合って一貫していれば許可する")

    system_instruction = f"""あなたはThreads投稿の品質管理責任者です。
以下の声定義を基準にして投稿案を審査してください。

{voice_def}

■ 審査で確認すべき語尾ルール:
{_suf_rule}
{_polite_rule}
- **声定義に書かれた語尾を差し戻し理由にしてはならない**
- 語尾・一人称の正は上の声定義であって、あなたの好みではない
- 「皆さん」は禁止（「みんな」が正しい）
"""

    prompt = f"""以下の投稿案を審査しろ。

## 審査対象
{posts_text}

## 差し戻し基準（1つでも該当すれば差し戻し）
1. 声定義の語尾指定から外れた語尾が使われている（※声定義が未記入なら、この項目は適用しない）
2. 「皆さん」が含まれている
3. 1投稿目が声定義の「定番のつかみ」で始まっていない（**声定義に定番のつかみが書かれている場合のみ**。未記入なら適用しない）
4. *（アスタリスク）が含まれている
5. 誤情報・誹謗中傷・規約違反
6. CTAに「何を届けるか」の価値提示がない
7. 禁止文字（** / * / " / " " / ' ' / `）が含まれている
8. 同じネタ・切り口が複数スロットで重複している
9. 冒頭60〜80文字に具体性がない（固有名詞または数字。固有名詞は**声定義・テーマファイルに出てくるものだけ**＝そこに無い名前はfact_guardが差し戻すため、要求しない）
10. （欠番）冒頭の数字は必須にしない。
    ⚠️ 2026-09-09：以前は「冒頭60〜80字に具体的数字が無ければ差し戻し」としていたが、
    素材帳が空の出荷状態では執筆側に「測っていない数字を書くな」と指示している。
    両方を同時に満たす道は**数字を作ること**しかなく、架空の実績を生む圧力になっていた。
    具体性は上の 9.（固有名詞**または**数字）で見る。
11. 冒頭に曖昧表現あり（「プロ級」「ある〇〇」「最新の〇〇」「神レベル」等）
12. 「稼げる」「月◯万」等の直接的収益表現が含まれている
13. マニアックなベンチマーク比較が含まれている（Kimi K2/Qwen3/Llama等）
14. （欠番）字数の判定はここでは行わない。
    ⚠️ 2026-09-08：以前は「2〜3投稿目が180文字未満なら差し戻し」と書いていたが、
    実測では3ジャンルの**116本中116本**が180字未満（中央値 91/75/110字）。
    つまりこの基準を真面目に適用したら**毎日全滅**する。今壊れていないのは
    LLMが字数を数えられず無視していたからで、基準が正しかったからではない。
    字数は**機械が数える**ので、下の機械検査側で見る（ここは中身だけを見る）。

## 合格基準
- {_suf_pass}
- 感情フックが機能している
- 3スロットが別の題材・別角度・別冒頭フレーズ
  （主題＝ブリーフィングが指定する大テーマは3本共通でよい。
  共通であることを理由に差し戻さない）

## 出力フォーマット

【マルフォイ審査結果】

■ SLOT_1（7時・朝）: [合格 / 差し戻し]
語尾: {_suf_check}
つかみ: [定番のつかみで始まっているか]
理由: [具体的なコメント]

■ SLOT_2（18時・夕方）: [合格 / 差し戻し]
語尾: {_suf_check}
つかみ: [定番のつかみで始まっているか]
理由: [具体的なコメント]

■ SLOT_3（21時・夜）: [合格 / 差し戻し]
語尾: {_suf_check}
つかみ: [定番のつかみで始まっているか]
理由: [具体的なコメント]

■ 総合判定: [全スロット承認申請可 / 差し戻しあり]
差し戻し理由（差し戻しがある場合）: [具体的な修正指示]
"""

    return call_gemini(prompt, GEMINI_API_KEY, system_instruction=system_instruction)


def clean_post_text(text: str) -> str:
    """投稿テキストからフォーマットラベルを除去する"""
    import re
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if re.match(r'^\[?\d+投稿目[：:].+\]?$', line.strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def extract_all_slot_texts(luna_posts: str) -> dict:
    """投稿案から各スロット（1/2/3）の本文を取り出す。

    ⚠️ 2026-09-01 改修（実際の公開事故を受けて）
    以前は「━ の区切り線に挟まれた部分」だけを本文と見なしていた。
    ところが生成モデルによっては **━ を出さない日がある**（実測：同じモデルでも
    出す日と出さない日がある）。そうなると本文が1つも取れず、校閲が
    `（SLOT_N 抽出失敗）` を書き、それがそのまま投稿された。

    区切り線という**1つの記号に依存する**のをやめ、取れなかったスロットは
    **見出し行から次の見出し行まで**を本文として拾う（見出し自体は落とす）。
    どちらでも取れなければ、そのスロットは空のまま返す（＝上流が差し戻す）。
    """
    text = luna_posts or ""
    lines = text.split(chr(10))

    # 各スロットの見出し行の位置（🌅 SLOT_1【…】 / **🌆 SLOT_2【…】** など）
    #
    # ⚠️ 2026-09-08 修正（実測：3スロット中2つが無言で消える事故が2種類）
    #   生成モデルは、本文の前に「今日の作業計画」や「渡された指示の復唱」を
    #   書き出す日がある。そこに次のような行が並ぶ：
    #       - SLOT_1: 【型1：対比・言い換え】     ← 計画の復唱
    #       - SLOT_1【呼びかけ型】読み手を1人に絞る  ← 型指定の復唱
    #   旧判定は「SLOT_n を含み、かつ 【 か [ を含む行」を見出しと見なしていたので、
    #   **これらを見出しと誤認**していた。結果、SLOT_1とSLOT_2は「復唱行の次から
    #   次の復唱行まで」＝中身ゼロになり、最後のSLOT_3が本文を全部飲み込んでいた。
    #   （＝2本が、エラーも警告も出ないまま消える）
    #
    #   本物の見出しと復唱行は、次の2点で確実に分かれる：
    #     (1) 本物は「SLOT_n【…】」とすぐ括弧が来る。計画行は「SLOT_n:」とコロンが入る
    #     (2) 本物は行頭が絵文字か ** で始まる。復唱行は「- 」「・」「1. 」の箇条書き
    #   両方を満たす行だけを見出しとして採用する。
    _HEAD_RX = {n: re.compile(r"SLOT[_ ]?%d\s*[【\[]" % n) for n in (1, 2, 3)}
    _BULLET_RX = re.compile(r"^(?:[-+・>]|\d+[.)]|\*(?!\*))\s")

    def _is_heading(ln, n):
        st = ln.strip()
        if _BULLET_RX.match(st):
            return False
        return bool(_HEAD_RX[n].search(st))

    head = {}
    for i, ln in enumerate(lines):
        for n in (1, 2, 3):
            if n not in head and _is_heading(ln, n):
                head[n] = i
    # 見出しが1つも取れない形（旧フォーマット）にも備える
    if not head:
        for i, ln in enumerate(lines):
            st = ln.strip()
            if _BULLET_RX.match(st):
                continue          # 箇条書きは見出しにしない（上と同じ理由）
            for n in (1, 2, 3):
                if n not in head and ("SLOT_%d" % n) in st \
                        and not re.search(r"SLOT[_ ]?%d\s*[：:]" % n, st):
                    head[n] = i
    slots = {}
    order = sorted(head.items(), key=lambda kv: kv[1])
    for idx, (n, start) in enumerate(order):
        end = order[idx + 1][1] if idx + 1 < len(order) else len(lines)
        block = lines[start + 1:end]
        # ① まず ━ に挟まれた部分を優先（従来どおり・最も正確）
        bars = [j for j, l in enumerate(block) if "━" in l]
        if len(bars) >= 2:
            body = block[bars[0] + 1:bars[1]]
        else:
            # ② ━ が無い場合は、見出しの次から次の見出しまでを本文とする。
            #    ただし最後のスロットは、後ろに付く定型のしめくくり
            #    （--- と、次の担当への引き継ぎ行）まで飲み込んでしまうので、
            #    水平線が出た時点で本文を打ち切る（実測で混入を確認して追加）。
            body = []
            for l in block:
                st = l.strip()
                if re.match(r"^(?:-{3,}|─{3,}|\*{3,})$", st):
                    break
                if st.startswith("*") and st.endswith("*") and len(st) > 2:
                    continue      # *担当への引き継ぎ* の形は本文ではない
                if "━" in l:
                    continue
                body.append(l)
        extracted = clean_post_text(chr(10).join(body))
        if extracted:
            slots[n] = extracted
    return slots

# ── 伏せ字プレースホルダの機械検査（2026-08-23 追加・実測で発覚）────────────
# 事故：生成文に「献立決めに〇〇する代わりに△△したら」がそのまま残ったまま、
#      Gemini校閲は該当スロットを **合格** にした（＝LLMだけに任せると素通りする）。
# 原因：writer.py と各ナレッジの**例文**が 〇〇 を穴埋め記号として多用しているのに、
#      「そのまま出すな」と書いてあるのは `[ ]` とリンクの2つだけだった。
# 対策：ここで機械的に弾く。何を埋めるべきかは機械には決められないので自動修復はせず、
#      差し戻し（既にあるリトライ経路に乗せる）。
_PLACEHOLDER_RX = re.compile(
    "[〇○]{2,}"                      # 〇〇
    "|[△▲]{2,}"                     # △△
    "|[×✕]{2,}"                     # ××
    "|\\{\\{[^}]{1,40}\\}\\}"          # {{ターゲットの悩み}}
    # ⚠️ 2026-08-30 拡大：旧「\\[(?:ここに|…)[^\\]]{0,20}\\]」は中身20字までしか見ず、
    #    ③キットで「[ここに◯◯のアフィリエイトリンクを貼る]」（中身21字・固有名詞入り）が
    #    1文字差ですり抜けて実投稿された。同型の穴の横展開修正。
    "|\\[[^\\]]{0,50}(?:ここに|挿入|商品名|リンク|URL|貼る)[^\\]]{0,50}\\]"
)


def find_placeholders(text):
    """本文に残った伏せ字・雛形記号を、前後の文脈つきで返す"""
    hits = []
    for m in _PLACEHOLDER_RX.finditer(text or ""):
        s = max(0, m.start() - 12)
        frag = text[s:m.end() + 12]
        hits.append(" ".join(frag.split()))
    return hits



# ── 社内用語の流出チェック（2026-08-23 追加・実測で発覚）────────────────
# 事故：声定義（buzz_posts.md）が未記入のまま回すと、リサーチが
#      「情報リサーチ担当として書け」と指示し、投稿本文が
#      「うちの情報リサーチ担当も、最近のThreadsのデータには頭を悩ませてる」になった。
#      承認すればそのまま公開され、**裏でAIチームが書いていることが読者に露見する**。
# 設計上の前提：声定義が未記入でも運用は止めない方針（writer.py 177行）。止めない以上、
#      出口で止める必要がある。ここは判断の要らない語の一致なので機械で確実に弾く。
# 注意：一般語（「ライター」「エージェント」等）は本文に自然に出うるので**入れない**。
#      ここに並べるのは「漏れた時にしか出ない社内語」だけ。
_INTERNAL_TERMS = [
    "情報リサーチ担当", "リサーチ担当", "校閲より", "ライターより", "投稿案",
    "ブリーフィング", "推奨ネタ", "感情フック", "参考バズ投稿", "リサーチ元",
    "パイプライン", "SLOT_1", "SLOT_2", "SLOT_3",
    "ハーマイオニー", "マルフォイ", "ルーナ", "スネイプ", "ロン",
]


def find_internal_terms(text):
    """投稿本文に混ざった社内用語を返す（前後の文脈つき）"""
    hits = []
    body = text or ""
    # 見出し行（🌅 SLOT_1【…】等）は投稿本文ではないので除く
    body = "\n".join(l for l in body.split("\n")
                     if not l.lstrip().startswith(("🌅", "🌆", "🌙", "#", "**", "━")))
    for w in _INTERNAL_TERMS:
        i = body.find(w)
        if i >= 0:
            frag = body[max(0, i - 14): i + len(w) + 14]
            hits.append("%s（…%s…）" % (w, " ".join(frag.split())))
    return hits

def _target_date_for_history() -> str:
    """重複判定の基準日。Issueのタイトル日付を優先し、無ければ当日。
    実時刻に固定すると、日付指定の再生成で窓がズレる（商品側で踏んだのと同じ罠）。"""
    import os as _os
    return _os.getenv("TARGET_DATE", "")


def main():
    logger.info("=== マルフォイ 校閲開始 ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "malfoy", "running")

    try:
        luna_posts = get_luna_posts(issue.number, gh)
        if not luna_posts:
            logger.error("ルーナの投稿案が見つかりません。先にluna_write.pyを実行してください。")
            gh.update_pipeline_status(issue.number, "malfoy", "error")
            sys.exit(1)

        # コードレベル禁止文字チェック（Gemini判断より優先）
        # ⚠️ 2026-08-01 修正：以前は luna_posts（Issueコメント全文）を検査していたため、
        #    ルーナのコメント整形（**作成日時:** 等）のアスタリスクを誤検知し、
        #    投稿本文に「*」が無くても毎回差し戻し → auto-retry上限で停止していた。
        #    検査対象は SLOT本文のみに限定する（extract_all_slot_texts は既存の抽出関数）。
        slot_texts = extract_all_slot_texts(luna_posts)
        if slot_texts:
            forbidden_found = sorted({c for t in slot_texts.values() for c in find_forbidden_chars(t)})
        else:
            # 本文が抽出できない＝整形が崩れている。ここで禁止文字を理由に落とすと
            # 原因が分からない差し戻しになるので、チェックはせずGemini審査へ回す。
            logger.warning("SLOT本文を抽出できませんでした。禁止文字チェックはスキップします。")
            forbidden_found = []
        if forbidden_found:
            chars_str = ' '.join(repr(c) for c in forbidden_found)
            logger.warning(f"禁止文字を検出: {chars_str} → 自動差し戻し")
            gh.update_pipeline_status(issue.number, "malfoy", "rejected")
            gh.add_comment(issue.number, f"## 🎩 {_n('malfoy')}より：差し戻し（禁止文字検出）\n\n**審査日時:** {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}\n\n禁止文字が含まれています: {chars_str}\n\n強調は `**` でも「」でもなく、**文の流れと改行**で出すこと（「」は感情と会話だけ）。ルーナに修正させます。")
            sys.exit(10)

        review_result = review_posts(luna_posts)
        is_approved   = "全スロット承認申請可" in review_result or "承認申請可" in review_result

        # ── 機械検査の入力を「スロット本文のみ」に一本化（2026-09-01・顧客報告で発覚）──
        # 事故：ルーナのコメント末尾の引き継ぎ行「*マルフォイ、…校閲をお願いします。*」
        #      （キット自身が書く定型文）を社内用語チェックが本文と誤認し、
        #      3スロット全部が合格なのに毎回差し戻し→リトライ上限で停止した。
        # 原因：各機械検査がコメント全文（見出し・引き継ぎメモ込み）を各自バラバラの
        #      除外ルールで解釈していた。検査を足すたびに解釈のズレ＝誤検知の口が増える構造。
        # 対策：読者の目に触れるのはスロット本文だけなので、**全機械検査の入力を
        #      抽出済みスロット本文に統一**する（禁止文字チェックは既に同方式）。
        #      抽出できない時だけ全文にフォールバック（検査を無効化しないため）。
        _guard_text = "\n\n".join(slot_texts.values()) if slot_texts else luna_posts

        # ⚠️ LLMの判定より機械の判定を優先する（上の find_placeholders の経緯を参照）
        _ph = find_placeholders(_guard_text)
        if _ph:
            is_approved = False
            _lines = ["", "", "■ 機械検査：伏せ字プレースホルダが残っています（自動差し戻し）"]
            _lines += ["  - ...%s..." % h for h in _ph[:8]]
            _lines += ["→ 〇〇 や △△ は例文で「ここを埋める」ことを示す記号です。"
                       "実際の言葉に置き換えてください（記号のまま投稿しない）。"]
            review_result += "\n".join(_lines)
            logger.warning("伏せ字プレースホルダ %d件を検出 → 機械的に差し戻し" % len(_ph))
        _it = find_internal_terms(_guard_text)
        if _it:
            is_approved = False
            _l2 = ["", "", "■ 機械検査：社内用語が投稿本文に混ざっています（自動差し戻し）"]
            _l2 += ["  - %s" % h for h in _it[:8]]
            _l2 += ["→ 読者向けの文章に、裏の仕組みの言葉が出ています。",
                    "　 声定義（operation/knowledge/kb_sys_ref_v001.md）が未記入だと、",
                    "　 書き手が「担当者」の立場で書いてしまい、これが起きます。",
                    "　 声定義を記入してから回し直してください。"]
            review_result += "\n".join(_l2)
            logger.warning("社内用語 %d件を検出 → 機械的に差し戻し" % len(_it))
        # ── 出口の関所（2026-08-24 追加・顧客報告4件への根本対応）──────────
        # LLMの判定より機械の判定を優先する。理由は find_placeholders と同じで、
        # 校閲を Gemini だけに任せると「合格」で素通りする事故が実測で起きているため。
        _fg = fact_guard.find_ungrounded(_guard_text)
        _or_ = owner_rules.find_owner_rule_violations(_guard_text)
        _rp = post_history.find_repeats(slot_texts or extract_all_slot_texts(luna_posts),
                                        anchor=_target_date_for_history())
        # 題材レベルの重複（2026-09-01 追加）：言い回しを変えた同じ話を拾う。
        # 実アカウントで「同じ題材・違う言い回し」が2日間隔で投稿された事例の対策
        # （その2本は言い回しの重複スコア0.010＝従来ガードでは素通りだった）。
        _tp = post_history.find_topic_repeats(slot_texts or extract_all_slot_texts(luna_posts),
                                              anchor=_target_date_for_history())
        if _fg or _or_ or _rp or _tp:
            is_approved = False
            _l3 = ["", ""]
            # 最終投稿のCTAを機械で見る（2026-09-10）
            # プロンプトに書くだけでは守られなかった（実測で①は21本中12本がCTA無し）。
            try:
                _cta_miss = []
                for _sk, _sv in sorted((slot_texts or {}).items()):
                    _parts = [x.strip() for x in re.split(r"===\s*THREAD\s*===", _sv or "") if x.strip()]
                    if not _parts:
                        continue
                    _sf = post_guard.cta_shortfall(_parts[-1])
                    if _sf:
                        _cta_miss.append("SLOT_%s → %s" % (_sk, _sf))
                if _cta_miss:
                    _l3 += ["", "■ 機械検査：最終投稿のCTAが弱い（自動差し戻し）"]
                    _l3 += ["  - %s" % m for m in _cta_miss[:3]]
                    _l3 += ["→ 最後の1投稿は「感想」ではなく、「読者がどうなるか」と",
                            "  「何を届けているか」のためだけに使ってください。"]
            except Exception as _ce:
                logger.warning("CTA検査をスキップ: %s" % _ce)
            if _fg:
                _l3 += ["■ 機械検査：根拠のない記述があります（自動差し戻し）"]
                _l3 += ["  - %s" % h for h in _fg[:6]]
                _l3 += ["→ 実在するかどうかではなく、**あなたのファイルに根拠があるか**で見ています。",
                        "　 実際に使っている物・実際に配っている物なら、声定義やテーマファイルに",
                        "　 一言書いておけば、次から通ります。"]
            if _or_:
                _l3 += ["", "■ 機械検査：あなたが決めたルールに違反しています（自動差し戻し）"]
                _l3 += ["  - %s" % h for h in _or_[:6]]
            if _rp:
                _l3 += ["", "■ 機械検査：直近の投稿と内容が重なりすぎています（自動差し戻し）"]
                _l3 += ["  - SLOT_%s が %s の投稿と %.0f%% 重複（…%s…）"
                        % (h["slot"], h["date"], h["ratio"] * 100, h["excerpt"]) for h in _rp[:6]]
                _l3 += ["→ 同じ題材でも切り口を変えるか、別の題材にしてください。"]
            if _tp:
                _l3 += ["", "■ 機械検査：直近の投稿と同じ題材です（自動差し戻し）"]
                _l3 += ["  - SLOT_%s が %s の投稿と同じ題材（%s）（…%s…）"
                        % (h["slot"], h["date"], h["shared"], h["excerpt"]) for h in _tp[:6]]
                _l3 += ["→ 言い回しを変えても、扱う題材が同じだと読者には同じ投稿に見えます。",
                        "　 素材帳（operation/my_material.md）から別の素材を選んでください。"]
            review_result += "\n".join(_l3)
            logger.warning("出口の関所で差し戻し（根拠なし%d / ルール違反%d / 重複%d / 同題材%d）"
                           % (len(_fg), len(_or_), len(_rp), len(_tp)))
        logger.info(f"審査結果: {'承認申請可' if is_approved else '差し戻し'}")

        if is_approved:
            # slot_texts は禁止文字チェック時に取得済み（再抽出しない）
            # ⚠️ 2026-09-01：ここで「（SLOT_N 抽出失敗）」という文字列を
            #    埋めていたため、**それが本文として実際にThreadsへ投稿された**。
            #    抽出できない＝投稿案の整形が壊れている状態なので、承認申請を出さず
            #    差し戻してやり直させる（既存のリトライ経路に乗せる）。
            _missing = [n for n in (1, 2, 3) if not (slot_texts.get(n) or "").strip()]
            if _missing:
                logger.error("スロット本文を抽出できません（SLOT_%s）。承認申請は出しません。"
                             % "・".join(str(n) for n in _missing))
                gh.update_pipeline_status(issue.number, "malfoy", "rejected")
                gh.add_comment(issue.number,
                    "## ⚠️ 差し戻し（投稿案の形が崩れています）\n\n"
                    "SLOT_%s の本文を取り出せませんでした。" % "・".join(str(n) for n in _missing)
                    + "投稿案は ━━ の区切り線で各スロットを囲む形で出力してください。\n"
                    + "（この状態で投稿すると、見出しや内部表記がそのまま公開されます）")
                sys.exit(10)   # 差し戻し＝再生成へ
            slot1_text = slot_texts[1]
            slot2_text = slot_texts[2]
            slot3_text = slot_texts[3]

            comment_body = f"""## 🎩 {_n('malfoy')}より：承認申請

**審査日時:** {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}

{review_result}

---
### 📋 推奨投稿案（3時間帯・オーナー一括承認用）

**🌅 SLOT_1【7時・即時投稿】**
```
{slot1_text}
```

**🌆 SLOT_2【18時・夕方投稿】**
```
{slot2_text}
```

**🌙 SLOT_3【21時・夜投稿】**
```
{slot3_text}
```

**オーナーへ:** このIssueに「承認」とコメントしてください。
- SLOT_1（7時）→ 承認後すぐに投稿されます
- SLOT_2（18時）→ GitHub Actionsが自動投稿します
- SLOT_3（21時）→ GitHub Actionsが自動投稿します
"""
            # ── 素材帳の聞き取りを「期日が来たら機械が出す」形にする（2026-09-09）
            # 散文で「週1で聞く」と書いても動かない（＝本人の声かけが起動条件になる）。
            # 毎日必ず動くこのサイクルが期日を判定し、顧客が必ず読む承認申請コメントに
            # 1行だけ足す。期日でない日は空文字なので何も増えない。
            try:
                _mnote = material_prompt.issue_note()
                if _mnote:
                    comment_body = comment_body + chr(10) * 2 + "---" + chr(10) * 2 + _mnote
                # 手の内ストックも同じ口で出す（2026-09-12）。
                # CLAUDE.md の散文だけだと「作られないまま運用が続く」ので、
                # 空・残りわずかを毎日機械が判定して、ここに1行だけ出す。
                _hnote = howto_stock.issue_note()
                if _hnote:
                    comment_body = comment_body + chr(10) * 2 + _hnote
            except Exception as _me:
                logger.warning("素材帳の声かけをスキップ: %s" % _me)
            done_ts = datetime.now(JST).strftime("%H:%M")
            gh.add_comment(issue.number, comment_body)
            gh.add_label(issue.number, GitHubIssues.APPROVAL_LABEL)
            gh.update_pipeline_status(issue.number, "malfoy", "done", done_ts)
            gh.update_pipeline_status(issue.number, "human", "pending")
            send_approval_request(
                DISCORD_WEBHOOK_URL,
                {"malfoy": ("done", done_ts), "human": ("pending", "-")},
                issue.number, issue.html_url,
                datetime.now(JST).strftime("%Y-%m-%d"),
                post_preview=slot1_text,
            )
            logger.info("承認申請コメントを追加しました（3スロット）")

        else:
            gh.update_pipeline_status(issue.number, "malfoy", "rejected")
            comment_body = f"""## 🎩 {_n('malfoy')}より：差し戻し（自動リトライします）

**審査日時:** {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}

{review_result}

---
*ルーナに修正指示を送り、自動でリトライします。*
"""
            gh.add_comment(issue.number, comment_body)
            logger.warning("投稿案を差し戻しました → リトライに進みます")
            sys.exit(10)

        logger.info("=== マルフォイ 校閲完了 ===")

    except SystemExit:
        raise  # sys.exit(10) をそのまま通す
    except Exception as e:
        logger.error(f"マルフォイ実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "malfoy", "error")
        gh.add_comment(issue.number, f"## ❌ {_n('malfoy')}: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ {_n('malfoy')}実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
