"""
gemini_client.py
Gemini API呼び出しの共通ユーティリティ
タイムアウト・3段階フォールバック・エラーハンドリングを一元管理する

フォールバックチェーン（各モデルは別クォータ）:
  1. gemini-2.5-flash       (高品質・25件/日)
  2. gemini-2.5-flash-lite   (軽量・別枠)
  3. gemini-3-flash-preview  (次世代・別枠)
"""

import os
import time
from google import genai
from google.genai import types
from loguru import logger

# モデルチェーン: すべて異なるクォータを持つモデル
# ※ gemini-2.0-flash / gemini-2.0-flash-lite は2026年時点でfree tier枠=0のため使用しない
GEMINI_MODEL_CHAIN = [
    os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

# リクエストタイムアウト（ミリ秒）— 90秒でAPIが返さなければ強制終了
REQUEST_TIMEOUT_MS = 90_000

# 出力トークン上限
# 2026-06-10 追加: 3スロット × 5パーツツリー = 4,500〜6,000字 (≒ 9,000〜12,000トークン)
# デフォルト 8192 だと出力途中で切れる事故が発生（6/10 Issue #57 で SLOT_2/3 が欠落）
# 16,384 に引き上げて余裕を持たせる
MAX_OUTPUT_TOKENS = 16_384


def _make_config(timeout_ms: int = REQUEST_TIMEOUT_MS) -> types.GenerateContentConfig:
    """タイムアウト付きのGenerateContentConfigを作る"""
    return types.GenerateContentConfig(
        httpOptions=types.HttpOptions(timeout=timeout_ms),
        maxOutputTokens=MAX_OUTPUT_TOKENS,
    )


def _is_retryable(e: Exception) -> bool:
    """フォールバックすべきエラーかどうか判定（429/500/503/504）

    2026-06-04 修正: 504 / DEADLINE_EXCEEDED を追加。
    Gemini APIサーバー側で90秒以内にレスポンスを返せない事象は日常的に発生する。
    旧コードでは504で即raiseしていたため、フォールバック先のflash-lite/3-flash-previewが
    1回も発動せずワークフローが落ちる事故が発生した。
    """
    err_str = str(e)
    return any(code in err_str for code in [
        "429", "RESOURCE_EXHAUSTED",  # レート制限
        "500", "INTERNAL",             # サーバー内部エラー
        "503", "UNAVAILABLE",          # サーバー過負荷
        "504", "DEADLINE_EXCEEDED",    # サーバー側タイムアウト（★2026-06-04 追加）
    ])


def call_gemini(prompt: str, api_key: str = None, system_instruction: str = None) -> str:
    """
    Gemini APIを呼び出す共通関数。

    Args:
        prompt: ユーザープロンプト
        api_key: APIキー（省略時は環境変数から取得）
        system_instruction: システム指示（声定義等をここに入れるとモデルが強く従う）

    動作:
    1. GEMINI_MODEL_CHAIN の各モデルを順番に試す
    2. 429 (レート制限) → 次のモデルへフォールバック
    3. タイムアウト / その他エラー → 即座にraiseして呼び出し元へ
    4. 全モデルが429 → 明確なRuntimeErrorを送出

    保証:
    - 最大待ち時間 = 90秒 × 3モデル + 5秒 × 2回sleep = 280秒（約5分）
    - 永久ハングは絶対にしない（90秒タイムアウトで強制切断）
    """
    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)

    # system_instructionがある場合はconfigに含める
    if system_instruction:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            httpOptions=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
            maxOutputTokens=MAX_OUTPUT_TOKENS,
        )
    else:
        config = _make_config()

    # ── 外部リトライ（2026-06-24 追加）──────────────────────────────
    # 503/504 は「全モデルが同時に数十秒〜数分だけ過負荷」になる事象が朝方に頻発する。
    # 旧コードは3モデルを十数秒で試し切って即raiseしていたため、1〜2分の一時的混雑でも
    # daily-cycle が落ち、毎朝 手動再実行が必要だった（2026-06-23・24 と連続発生）。
    # チェーン全体を「時間を空けて」複数回試すことで、短時間の混雑を自動で乗り切る。
    # quota(429) や想定外エラーは再試行しても無駄なので、その場合はリトライせず即raiseする。
    OUTER_RETRIES = int(os.getenv("GEMINI_OUTER_RETRIES", "3"))  # チェーン全体の試行回数
    BACKOFFS = [20, 60, 120]  # ラウンド間の待機秒（混雑が収まるのを待つ）

    last_models = []
    last_kinds = []

    for round_idx in range(OUTER_RETRIES):
        exhausted_models = []
        error_kinds = []  # 各モデルが何で落ちたか（quota/transient/other）

        for i, model in enumerate(GEMINI_MODEL_CHAIN):
            try:
                logger.info(
                    f"Gemini API呼び出し: {model} "
                    f"(round {round_idx+1}/{OUTER_RETRIES}, attempt {i+1}/{len(GEMINI_MODEL_CHAIN)})"
                )
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                if round_idx > 0 or i > 0:
                    logger.info(f"フォールバック成功: {model} (round {round_idx+1})")
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
                #    （③アフィリエージェントの同型コードで 2026-07-03・07-26 に実際に発生）
                #    ここで「このモデルはダメだった」扱いにして次のモデルへ回す。
                if response.text is None:
                    exhausted_models.append(model)
                    error_kinds.append("empty")
                    logger.warning(f"{model} → 応答が空（response.text is None）")
                    if i < len(GEMINI_MODEL_CHAIN) - 1:
                        time.sleep(3)
                    continue

                return response.text

            except Exception as e:
                if _is_retryable(e):
                    exhausted_models.append(model)
                    es = str(e)
                    if "429" in es or "RESOURCE_EXHAUSTED" in es:
                        error_kinds.append("quota")    # 真の枠切れ
                    elif any(c in es for c in ["503", "UNAVAILABLE", "500", "INTERNAL", "504", "DEADLINE_EXCEEDED"]):
                        error_kinds.append("transient")  # サーバー一時障害（混雑/タイムアウト）
                    else:
                        error_kinds.append("other")
                    logger.warning(f"{model} → {type(e).__name__}: {es[:100]}")
                    if i < len(GEMINI_MODEL_CHAIN) - 1:
                        time.sleep(3)
                    continue
                else:
                    logger.error(f"{model} エラー: {type(e).__name__}: {str(e)[:300]}")
                    raise

        # チェーンを1周しても成功しなかった
        last_models = exhausted_models
        last_kinds = error_kinds
        all_transient = bool(error_kinds) and all(k == "transient" for k in error_kinds)

        # 全モデルが一時障害(503/500/504)で、まだ残りラウンドがあるなら待って再挑戦
        if all_transient and round_idx < OUTER_RETRIES - 1:
            wait = BACKOFFS[min(round_idx, len(BACKOFFS) - 1)]
            logger.warning(
                f"全モデル一時障害(503/500/504)。{wait}秒待ってチェーン全体を再試行します "
                f"（次ラウンド {round_idx+2}/{OUTER_RETRIES}）"
            )
            time.sleep(wait)
            continue

        # quota/other を含む or 最終ラウンド → 再試行しても無駄なので抜けてraise
        break

    model_list = ", ".join(last_models)
    # 503/500/504（一時障害）だけで落ちた場合は「枠切れ」ではなく「一時的な混雑」と正しく伝える
    if last_kinds and all(k == "transient" for k in last_kinds):
        raise RuntimeError(
            f"Gemini API: 全モデルが一時的に応答不可（503/500/504・サーバー混雑やタイムアウト）です ({model_list})。"
            f" {OUTER_RETRIES}回チェーン再試行しても回復しませんでした。"
            f" これは無料枠の枯渇ではなく一時的な障害です。"
            f" 数分〜1時間後に手動でワークフローを再実行すれば復旧することが多いです。"
        )
    elif "quota" in last_kinds:
        raise RuntimeError(
            f"Gemini API: レート制限/無料枠の枯渇（429・RESOURCE_EXHAUSTED）を検出 ({model_list})。"
            f" 日の無料枠を使い切った可能性があります。"
            f" 翌日の枠リセットを待つか、手動でワークフローを再実行してください。"
        )
    else:
        raise RuntimeError(
            f"Gemini API: 全モデルが応答不可 ({model_list}・種別: {','.join(last_kinds)})。"
            f" 手動でワークフローを再実行してください。"
        )
