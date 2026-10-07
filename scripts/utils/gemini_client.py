"""
gemini_client.py
Gemini API呼び出しの共通ユーティリティ
タイムアウト・モデル連鎖フォールバック・エラーハンドリングを一元管理する

⚠️ このファイルは ③アフィリ / ④ホグ の両キットで**バイト単位で同一**にすること。
   2026-09-09 に統合。それまで2キットで別々に育っており、実害が出ていた：
     ・④にしか無かった: MAX_OUTPUT_TOKENS（出力の途中切れ対策）／出力打ち切りの検知ログ
     ・③にしか無かった: エラー種別の分離（quota / transient / other / empty）
   ＝「同じファイルが2つあって片方だけ直る」という、過去に何度も事故を起こした形。
   片方を直したら必ずもう片方へコピーし、cmp で同一を確認すること。

モデル連鎖の考え方（2026-09-09 改訂・最重要）:
   **どのモデルがどんな理由で落ちても、必ず次のモデルを試す。**
   旧実装は「既知のエラー文字列の一覧」に載っているときだけ次へ進み、
   知らないエラーが来ると **1モデル目で即 raise** して連鎖が1つも試されなかった。
   その結果、新しいエラー文言が出るたびに人がこのファイルを直す必要があり、
   運用が人の修正待ちで止まっていた。
   そこで判定を反転させ、**既定を「次のモデルを試す」**にした。
   例外は「どのモデルでも同じように失敗するもの」＝APIキー不正・権限エラーだけ。
   これは連鎖を回しても無駄なので、原因が分かる文言で即座に落とす。
"""

import os
import time
from google import genai
from google.genai import types
from loguru import logger

# モデル連鎖: すべて異なるクォータを持つモデル
# ※ gemini-2.0-flash / gemini-2.0-flash-lite は2026年時点で free tier 枠=0 のため使用しない
# ⚠️ 2026-08-06 顧客報告で判明した3点を修正:
#   1) 新規Googleアカウントでは gemini-2.5 系が 404（no longer available to new users）になる
#      → 受け皿として gemini-flash-latest（常に現行版を指すエイリアス）を連鎖に追加
#   2) 404 がフォールバック対象外だったため、連鎖があっても2つ目以降に進まず即死していた
#   3) この定数は import 時に評価され、呼び出し側の load_dotenv() より先に走るため
#      .env の GEMINI_MODEL が効かなかった → 関数化して呼び出しのたびに評価する
# KV配信の連鎖ファイル（運営が更新すると再配布なしで全員に反映される・2026-08-07 追加）。
# サイクル冒頭のKB取得ループが operation/knowledge/ へ書き出す。無ければ内蔵連鎖で動く。
_CHAIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "operation", "knowledge", "gemini_model_chain.txt")
# 内蔵の既定連鎖（KVが無い/壊れている場合の最後の砦。flash-latest が新規垢の受け皿）
_BUILTIN_CHAIN = [
    "gemini-2.5-flash",           # 既存アカウント: 高品質・別クォータ
    "gemini-2.5-flash-lite",      # 既存アカウント: 軽量・別枠
    "gemini-flash-latest",        # 新規アカウントの受け皿（常に現行版を指す）
    "gemini-3-flash-preview",     # 次世代・別枠
    # ⚠️ 2026-09-01: lite-latest は「応答はするが投稿フォーマットを守らない日がある」
    #    ことが実測で判明した（8/30に3番手へ入れたところ、本文を取り出せず
    #    内部表記が投稿される事故につながった）。全部だめな日の最後の砦としてのみ残す。
    "gemini-flash-lite-latest",
]


def _read_kv_chain() -> list:
    """KV配信されたモデル連鎖を読む。1行1モデル・#はコメント。
    壊れた内容で全滅しないよう、モデル名として妥当な行だけ採用する。"""
    import re as _re
    try:
        with open(_CHAIN_FILE, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    models = []
    for line in lines:
        s = line.split("#", 1)[0].strip()
        if s and _re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,60}", s):
            models.append(s)
    return models[:8]   # 暴走防止（8モデルを超える連鎖は想定しない）


def _model_chain() -> list:
    """モデル連鎖を「呼び出し時点」で組み立てる。
    優先順: ①環境変数 GEMINI_MODEL（最優先・顧客の緊急上書き用）
            ②KV配信の gemini_model_chain.txt（運営が再配布なしで更新できる）
            ③内蔵の既定連鎖（上2つが無くても必ず動く）
    ②があっても③を末尾に足す＝KVに書き間違いがあっても全滅しない。
    ⚠️ ①で指定したモデルが使えない場合も、連鎖の残りが後ろに続く。
       「指定したモデルが死んでいたらその日は生成できない」を起こさないため。"""
    kv = _read_kv_chain()
    chain = kv + [m for m in _BUILTIN_CHAIN if m not in kv]
    env = os.getenv("GEMINI_MODEL", "").strip()
    if env:
        chain = [env] + [m for m in chain if m != env]
    return chain


# 後方互換: 旧名を参照している既存コードのために残す（実際の呼び出しは毎回 _model_chain()）
GEMINI_MODEL_CHAIN = _model_chain()

# リクエストタイムアウト（ミリ秒）— 90秒でAPIが返さなければ強制終了
REQUEST_TIMEOUT_MS = 90_000

# 出力トークン上限
# 2026-06-10 追加: 3スロット × 5パーツツリー = 4,500〜6,000字 (≒ 9,000〜12,000トークン)
# デフォルト 8192 だと出力途中で切れる事故が発生（6/10 Issue #57 で SLOT_2/3 が欠落）
# 16,384 に引き上げて余裕を持たせる。
# ⚠️ 2026-09-09: ③のキットにはこの指定が入っておらず SDK 既定の 8192 のままだった
#    （＝④で起きた「SLOT_2/3 が丸ごと欠落」が③でも起こりうる状態だった）。統合で解消。
MAX_OUTPUT_TOKENS = 16_384


def _make_config(system_instruction: str = None,
                 timeout_ms: int = REQUEST_TIMEOUT_MS) -> types.GenerateContentConfig:
    """タイムアウトと出力上限を付けた GenerateContentConfig を作る（組み立ての唯一の口）。
    ⚠️ ここを通さない config を別途組み立てないこと。過去に system_instruction のある道だけ
       maxOutputTokens が抜ける、という食い違いが起きている。"""
    kwargs = {
        "httpOptions": types.HttpOptions(timeout=timeout_ms),
        "maxOutputTokens": MAX_OUTPUT_TOKENS,
    }
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    return types.GenerateContentConfig(**kwargs)


# ── エラーの見分け方 ───────────────────────────────────────────────
#: 「待てば直る」一時障害。これだけで全滅したときは、時間を空けて連鎖ごと再試行する。
_TRANSIENT_CODES = [
    "503", "UNAVAILABLE",          # サーバー過負荷
    "500", "INTERNAL",             # サーバー内部エラー
    "504", "DEADLINE_EXCEEDED",    # サーバー側タイムアウト
    # ★2026-09-01: クライアント側の読み取りタイムアウト。httpx.ReadTimeout の文言は
    #   "The read operation timed out" で、上のどのコードにも当たらない。
    "timed out", "Timeout", "ReadTimeout", "ConnectError", "ConnectTimeout",
]
#: 「待っても無駄」＝枠切れ。翌日のリセットまで直らない。
_QUOTA_CODES = ["429", "RESOURCE_EXHAUSTED"]
#: 「どのモデルで試しても同じように失敗する」もの。連鎖を回す意味がないので即座に落とす。
#: モデル固有の問題ではないため、ここだけは例外的にフォールバックしない。
_FATAL_CODES = [
    "API key not valid", "API_KEY_INVALID", "API key expired",
    "PERMISSION_DENIED", "UNAUTHENTICATED",
]


def _error_kind(e: Exception) -> str:
    """落ちた理由を fatal / quota / transient / other に分ける。

    ⚠️ この分類は「次のモデルを試すかどうか」には**使わない**（fatal 以外は必ず試す）。
       使うのは ①外側リトライをするかの判断 ②人に見せるエラー文言 の2つだけ。
       ここに新しいコードを足し忘れても連鎖は止まらない、という形にしてある。
    """
    es = str(e)
    if any(c in es for c in _FATAL_CODES):
        return "fatal"
    if any(c in es for c in _QUOTA_CODES):
        return "quota"
    if any(c in es for c in _TRANSIENT_CODES):
        return "transient"
    return "other"


def call_gemini(prompt: str, api_key: str = None, system_instruction: str = None) -> str:
    """
    Gemini APIを呼び出す共通関数。

    Args:
        prompt: ユーザープロンプト
        api_key: APIキー（省略時は環境変数から取得）
        system_instruction: システム指示（声定義等をここに入れるとモデルが強く従う）

    動作:
    1. モデル連鎖の各モデルを順番に試す
    2. **どんなエラーでも次のモデルへフォールバックする**（既知のエラー一覧に依存しない）
       例外は APIキー不正・権限エラーだけ（どのモデルでも同じに失敗するため即raise）
    3. 応答が空(None)のモデルも「だめだった」扱いにして次へ回す
    4. 全モデルが一時障害(500/503/504)だけで落ちた → 時間を空けて連鎖ごと再試行
    5. それでもだめ → どのモデルが何で落ちたかを明記した RuntimeError

    保証:
    - 永久ハングは絶対にしない（90秒タイムアウトで強制切断）
    - 「新しいエラー文言が出たせいで連鎖が1つも試されない」は起こらない
    """
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)
    config = _make_config(system_instruction)

    # ── 外側リトライ（2026-06-24 追加）──────────────────────────────
    # 503/504 は「全モデルが同時に数十秒〜数分だけ過負荷」になる事象が朝方に頻発する。
    # 連鎖を十数秒で試し切って即raiseすると、1〜2分の一時的混雑でも日次サイクルが落ちて
    # 毎朝の手動再実行が必要になる（2026-06-23・24 と連続発生）。
    # 連鎖全体を時間を空けて複数回試して混雑を乗り切る。
    # quota(429) や other は再試行しても無駄なので、その場合はリトライせず抜ける。
    OUTER_RETRIES = int(os.getenv("GEMINI_OUTER_RETRIES", "3"))  # 連鎖全体の試行回数
    BACKOFFS = [20, 60, 120]  # ラウンド間の待機秒（混雑が収まるのを待つ）

    last_failures = []   # [(model, kind, message), ...]

    chain = _model_chain()   # .env の GEMINI_MODEL を呼び出し時点で反映
    for round_idx in range(OUTER_RETRIES):
        failures = []        # このラウンドで各モデルが何で落ちたか

        for i, model in enumerate(chain):
            try:
                logger.info(
                    f"Gemini API呼び出し: {model} "
                    f"(round {round_idx+1}/{OUTER_RETRIES}, attempt {i+1}/{len(chain)})"
                )
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )

                # 出力の打ち切り検知（2026-07-26 追加）
                # 2.5系は thinking トークンも maxOutputTokens を食うため、
                # 「SLOT_2/3 が丸ごと欠落」が MAX_TOKENS 由来なのかモデルの手抜きなのかを
                # ログだけで切り分けられるようにする（以前は無言で短い出力が返っていた）。
                try:
                    fr = getattr(response.candidates[0], "finish_reason", None)
                    um = getattr(response, "usage_metadata", None)
                    fr_name = getattr(fr, "name", str(fr))
                    if um is not None:
                        logger.info(
                            f"Gemini応答: finish_reason={fr_name} "
                            f"prompt={getattr(um, 'prompt_token_count', '?')} "
                            f"thoughts={getattr(um, 'thoughts_token_count', 0) or 0} "
                            f"output={getattr(um, 'candidates_token_count', '?')}"
                        )
                    if fr_name and "MAX_TOKENS" in fr_name:
                        logger.warning(
                            "Gemini出力が maxOutputTokens で打ち切られた。"
                            "MAX_OUTPUT_TOKENS の引き上げ or プロンプト短縮が必要。"
                        )
                except Exception:
                    pass

                # ⚠️ response.text は例外を出さずに None を返すことがある
                #    （safety block / finish_reason 異常 / 候補ゼロ）。
                #    そのまま return すると呼び出し元が str のつもりで触って
                #    "TypeError: 'NoneType' object is not subscriptable" で落ちる。
                #    （2026-07-03・07-26 に実際に発生）
                #    ここで「このモデルはダメだった」扱いにして次のモデルへ回す。
                text = response.text
                if text is None:
                    failures.append((model, "empty", "応答が空（response.text is None）"))
                    logger.warning(f"{model} → 応答が空（response.text is None）")
                    if i < len(chain) - 1:
                        logger.info(f"→ 次のモデル {chain[i+1]} にフォールバック")
                        time.sleep(3)
                    continue

                if round_idx > 0 or i > 0:
                    logger.info(f"フォールバック成功: {model} (round {round_idx+1})")
                return text

            except Exception as e:
                kind = _error_kind(e)
                msg = str(e)[:200]

                # APIキー不正・権限エラーは、どのモデルで試しても同じように失敗する。
                # 連鎖を回すだけ時間の無駄なので、原因が分かる文言で即座に落とす。
                if kind == "fatal":
                    logger.error(f"{model} → 認証エラー: {type(e).__name__}: {msg}")
                    raise RuntimeError(
                        "Gemini API: APIキーが無効か、権限がありません。"
                        " モデルを変えても直りません。.env の GEMINI_API_KEY を確認してください。"
                        f"（元のエラー: {msg}）"
                    ) from e

                # ★ それ以外は**理由を問わず次のモデルを試す**（既知エラー一覧に依存しない）
                failures.append((model, kind, msg))
                logger.warning(f"{model} → [{kind}] {type(e).__name__}: {msg[:100]}")
                if i < len(chain) - 1:
                    logger.info(f"→ 次のモデル {chain[i+1]} にフォールバック")
                    time.sleep(3)
                continue

        # 連鎖を1周しても成功しなかった
        last_failures = failures
        kinds = [k for _m, k, _msg in failures]
        all_transient = bool(kinds) and all(k == "transient" for k in kinds)

        # 全モデルが一時障害(500/503/504)で、まだ残りラウンドがあるなら待って再挑戦
        if all_transient and round_idx < OUTER_RETRIES - 1:
            wait = BACKOFFS[min(round_idx, len(BACKOFFS) - 1)]
            logger.warning(
                f"全モデル一時障害(500/503/504)。{wait}秒待って連鎖全体を再試行します "
                f"（次ラウンド {round_idx+2}/{OUTER_RETRIES}）"
            )
            time.sleep(wait)
            continue

        # quota/other/empty を含む or 最終ラウンド → 再試行しても無駄なので抜ける
        break

    # ── ここまで来た＝全モデルが失敗。何がどう落ちたかを全部書いて渡す ──
    detail = " / ".join(f"{m}[{k}]" for m, k, _msg in last_failures) or "なし"
    kinds = [k for _m, k, _msg in last_failures]

    if kinds and all(k == "transient" for k in kinds):
        raise RuntimeError(
            f"Gemini API: 全モデルが一時的に応答不可（500/503/504・サーバー混雑やタイムアウト）です"
            f"（{detail}）。{OUTER_RETRIES}回チェーン再試行しても回復しませんでした。"
            " これは無料枠の枯渇ではなく一時的な障害です。"
            " 数分〜1時間後に再実行すれば復旧することが多いです。"
        )
    if "quota" in kinds:
        raise RuntimeError(
            f"Gemini API: レート制限/無料枠の枯渇（429・RESOURCE_EXHAUSTED）を検出しました"
            f"（{detail}）。日の無料枠を使い切った可能性があります。"
            " 翌日の枠リセットを待つか、手動で再実行してください。"
        )
    raise RuntimeError(
        f"Gemini API: 全モデルが使用できませんでした（{detail}）。"
        " 各モデルの詳細はログの warning 行を見てください。"
        " 1〜2時間後に再実行するか、手動でワークフローを再実行してください。"
    )


# ══════════════════════════════════════════════════════════════════
# Google検索グラウンディング（2026-09-09 追加）
# ══════════════════════════════════════════════════════════════════
# なぜ在るか：
#   リサーチ層が集めていたのは YouTube のタイトルと RSS の見出しだけで、
#   **本文の取得も裏取りもしていなかった**。その結果ブリーフィングは
#   「話題の一覧」にしかならず、投稿が「読者が既に知っている一般論」になっていた。
#   検索で裏の取れた具体（手順・番手・頻度）を材料に渡せば密度が上がる。
#
# ⚠️ 実測（2026-09-09・生curlとSDKの両方で確認）：
#   検索グラウンディングが使えるモデルは**通常の生成とは別枠**で、
#   同じアカウントでも可否がまったく違う。
#     gemini-2.5-flash        : 検索なし=OK / 検索あり=429（20回/日で打ち止め）
#     gemini-2.5-flash-lite   : 検索なし=OK / 検索あり=OK（12回連続成功・上限に当たらず）
#     gemini-flash-latest     : 検索なし=OK / 検索あり=429
#     gemini-3-flash-preview  : 検索なし=OK / 検索あり=429
#     gemini-flash-lite-latest: 検索なし=OK / 検索あり=429
#   → 執筆用の連鎖をそのまま使うと1モデル目で枠を食って終わる。
#     リサーチ専用の連鎖ファイル（gemini_research_chain.txt）に分ける。
#
# ⚠️ もっと危険な実測：**引用0件でも「成功」が返る**（12回中2回）。
#   モデルが検索せず自分の記憶だけで答えた回で、HTTPは200・本文もそれらしい。
#   これを裏取り済みとして扱うと「裏を取ったつもりの捏造」になる。
#   よってこの関数は **引用が1件も無い応答を「裏取り失敗」として空で返す**。
#
# ⚠️ この関数は**例外を投げない**。検索が落ちた日も生成は従来どおり続ける。
#   ただし無音にはしない（呼び出し側が台帳に「本日は裏取りなし」と残す）。

_RESEARCH_CHAIN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "operation", "knowledge", "gemini_research_chain.txt")

# 内蔵の既定（連鎖ファイルが無い/壊れている場合）。実測で検索が通った順。
_BUILTIN_RESEARCH_CHAIN = [
    "gemini-2.5-flash-lite",   # 実測で唯一安定して検索が通る（2026-09-09）
    "gemini-2.5-flash",        # 20回/日だが品質は高い。lite が落ちた日の受け皿
    "gemini-flash-latest",     # 新規アカウントの受け皿
]

#: 一次ソースとみなすドメインの手がかり（メーカー公式・公的機関・学術）
#: ⚠️ ここは「参考」であって断定ではない。台帳には判定と一緒に必ずドメインも残すので、
#:    人が見て違うと思ったら直せる。機械が勝手に一次と決めつけて終わりにしない。
_PRIMARY_HINTS = (".go.jp", ".lg.jp", ".ac.jp", ".or.jp", "who.int", ".gov", ".edu")
#: 二次（まとめ・個人発信・動画）とみなす手がかり
_SECONDARY_HINTS = ("note.com", "ameblo.jp", "youtube.com", "twitter.com", "x.com",
                    "matome", "naver", "hatena", "qiita.com", "zenn.dev",
                    "nifty.com", "goo.ne.jp", "livedoor")


def _research_chain() -> list:
    """リサーチ（検索グラウンディング）専用のモデル連鎖。
    優先順: ①環境変数 GEMINI_RESEARCH_MODEL ②連鎖ファイル ③内蔵の既定"""
    import re as _re
    kv = []
    try:
        with open(_RESEARCH_CHAIN_FILE, encoding="utf-8") as f:
            for line in f.read().splitlines():
                s = line.split("#", 1)[0].strip()
                if s and _re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,60}", s):
                    kv.append(s)
    except OSError:
        pass
    chain = kv[:8] + [m for m in _BUILTIN_RESEARCH_CHAIN if m not in kv]
    env = os.getenv("GEMINI_RESEARCH_MODEL", "").strip()
    if env:
        chain = [env] + [m for m in chain if m != env]
    return chain


def _source_kind(domain: str) -> str:
    """出典が一次寄りか二次寄りかを、ドメインの手がかりだけで粗く分ける"""
    d = (domain or "").lower()
    if any(h in d for h in _SECONDARY_HINTS):
        return "二次"
    if any(h in d for h in _PRIMARY_HINTS):
        # 公的機関・学術だけは**本文で名前を出してよい**（読者が知っているので信頼が上がる）。
        # 企業サイトは一次情報ではあるが、社名を出しても読者は知らないので逆効果。
        return "公的・学術"
    return "一次(企業サイト)" if d else "不明"


def call_gemini_grounded(query: str, api_key: str = None) -> dict:
    """Google検索で裏を取りながら答えさせる。**失敗しても例外を投げない。**

    Returns:
        {"ok": bool, "text": str, "queries": [str], "sources": [{"domain","title","uri","kind"}],
         "model": str, "reason": str}

        ok=False のときは text が空文字。理由は reason に入る：
          "no_citation" … 応答は返ったが引用0件（＝検索していない＝裏取りではない）
          "all_failed"  … 全モデルが落ちた（枠切れ・障害など）
          "no_key"      … APIキーが無い

    ⚠️ 呼び出し側は ok を必ず見ること。text だけ使うと、裏取りできていない日に
       「検索した気になっている材料」を投稿へ流すことになる。
    """
    out = {"ok": False, "text": "", "queries": [], "sources": [],
           "model": "", "reason": ""}
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        out["reason"] = "no_key"
        logger.warning("検索グラウンディング: APIキーが無いのでスキップします")
        return out

    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            httpOptions=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
            maxOutputTokens=MAX_OUTPUT_TOKENS,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    except Exception as e:
        out["reason"] = "all_failed"
        logger.warning(f"検索グラウンディング: 準備に失敗 {type(e).__name__}: {str(e)[:100]}")
        return out

    chain = _research_chain()
    no_citation_models = []

    for i, model in enumerate(chain):
        try:
            logger.info(f"検索グラウンディング: {model} (attempt {i+1}/{len(chain)})")
            resp = client.models.generate_content(model=model, contents=query, config=config)

            text = resp.text
            cand = (resp.candidates or [None])[0]
            gm = getattr(cand, "grounding_metadata", None) if cand else None
            chunks = list(getattr(gm, "grounding_chunks", None) or []) if gm else []

            sources = []
            for ch in chunks:
                web = getattr(ch, "web", None)
                if not web:
                    continue
                domain = (getattr(web, "title", "") or "").strip()
                sources.append({
                    "domain": domain,
                    "title": (getattr(web, "domain", "") or domain).strip(),
                    # ⚠️ このURLは vertexaisearch のリダイレクトで**期限つき**（およそ30日）。
                    #    あとから開けなくなるので、台帳には必ず取得日を一緒に残すこと。
                    "uri": (getattr(web, "uri", "") or "").strip(),
                    "kind": _source_kind(domain),
                })

            # ★ 引用0件＝モデルが検索していない＝裏取りではない。使わない。
            if not sources or not text:
                no_citation_models.append(model)
                logger.warning(
                    f"{model} → 引用0件（検索せず自分の記憶で答えた可能性）。裏取り失敗として扱います")
                if i < len(chain) - 1:
                    logger.info(f"→ 次のモデル {chain[i+1]} で再試行")
                    time.sleep(3)
                continue

            out.update({
                "ok": True,
                "text": text,
                "queries": list(getattr(gm, "web_search_queries", None) or []),
                "sources": sources,
                "model": model,
                "reason": "",
            })
            logger.info(f"検索グラウンディング成功: {model} / 引用 {len(sources)} 件")
            return out

        except Exception as e:
            # ここも「理由を問わず次のモデルを試す」（call_gemini と同じ方針）
            kind = _error_kind(e)
            logger.warning(f"{model} → [{kind}] {type(e).__name__}: {str(e)[:120]}")
            if kind == "fatal":
                out["reason"] = "all_failed"
                return out
            if i < len(chain) - 1:
                logger.info(f"→ 次のモデル {chain[i+1]} で再試行")
                time.sleep(3)
            continue

    out["reason"] = "no_citation" if no_citation_models else "all_failed"
    logger.warning(
        f"検索グラウンディング: 裏取りできませんでした（{out['reason']}）。"
        " 本日は検索なしで従来どおり進めます。")
    return out
