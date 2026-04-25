"""
urgent_post.py
緊急投稿スクリプト: Discord /add-idea から受け取ったネタを即時投稿する
ファクトチェック → 投稿案生成 → Threads投稿 → Discord通知
"""

import os
import sys
import re
import requests
from datetime import datetime
from utils.github_issues import GitHubIssues
from utils.gemini_client import call_gemini
from utils.agent_config import name as _n
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID      = os.getenv("THREADS_USER_ID")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


def load_voice_definition() -> str:
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return ""
    except FileNotFoundError:
        return ""


def sanitize_post_text(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'「\1」', text)
    text = text.replace('*', '')
    text = text.replace('"', '').replace("'", '')
    text = text.replace('"', '').replace('"', '')
    text = text.replace(''', '').replace(''', '')
    text = text.replace('`', '')
    return text


def fact_check(idea: str) -> tuple[bool, str]:
    """ネタの事実確認を行う。問題がなければ (True, "") を返す"""
    prompt = f"""以下のSNS投稿ネタについて、事実確認を行ってください。

ネタ: {idea}

確認項目:
1. 明らかな誤情報・虚偽情報が含まれていないか
2. 特定個人・企業への誹謗中傷になっていないか
3. Threadsの利用規約に違反する内容でないか

出力フォーマット:
判定: [通過 / 要修正 / 不可]
理由: [判定の根拠。「通過」の場合は「問題なし」]
"""
    result = call_gemini(prompt, GEMINI_API_KEY)
    passed = "通過" in result and "不可" not in result and "要修正" not in result
    return passed, result


def generate_urgent_post(idea: str, voice_def: str) -> str:
    """ネタから単体投稿（ツリーなし）を生成する"""
    prompt = f"""以下の声定義に従って、Threads単体投稿（1投稿）を作成してください。

## 声定義
{voice_def}

## ネタ
{idea}

## 制約
- 300文字以内
- 禁止語尾: 「〜です」「〜ます」「〜ください」
- 禁止文字: * " ' ` （強調は「」を使う）
- 感情フックを必ず1つ入れる
- 最後にCTA（価値提示）を入れる

## 出力
投稿文のみ（説明不要）:
"""
    result = call_gemini(prompt, GEMINI_API_KEY, system_instruction=voice_def)
    return sanitize_post_text(result.strip())


def post_to_threads(text: str) -> dict | None:
    """Threads APIで即時投稿する"""
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.warning("Threads認証情報なし → 投稿スキップ")
        return None

    # コンテナ作成
    create_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    res = requests.post(create_url, params={
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }, timeout=30)
    res.raise_for_status()
    container_id = res.json().get("id")

    # 公開
    publish_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish"
    res2 = requests.post(publish_url, params={
        "creation_id": container_id,
        "access_token": THREADS_ACCESS_TOKEN,
    }, timeout=30)
    res2.raise_for_status()
    return res2.json()


def notify_discord(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception:
        pass


def main():
    idea = os.getenv("IDEA", "").strip()
    if not idea:
        logger.error("IDEA環境変数が設定されていません")
        sys.exit(1)

    logger.info(f"=== 緊急投稿開始: {idea[:50]}... ===")

    # ファクトチェック
    passed, fact_result = fact_check(idea)
    if not passed:
        msg = f"⛔ **ファクトチェック不通過**\nネタ: {idea[:100]}\n\n{fact_result}"
        notify_discord(msg)
        logger.error(f"ファクトチェック失敗: {fact_result}")
        sys.exit(1)

    # 投稿案生成
    voice_def = load_voice_definition()
    post_text = generate_urgent_post(idea, voice_def)
    logger.info(f"投稿案生成完了: {len(post_text)}文字")

    if DRY_RUN:
        msg = f"🧪 **テスト投稿案（未投稿）**\n\n{post_text}"
        notify_discord(msg)
        logger.info("DRY_RUN: 投稿せず案をDiscordに送信")
        return

    # Threads投稿
    result = post_to_threads(post_text)
    if result:
        msg = f"✅ **緊急投稿完了**\n\n{post_text}"
        notify_discord(msg)
        logger.info("Threads投稿完了")
    else:
        msg = f"📋 **投稿案（手動投稿してください）**\n\n{post_text}"
        notify_discord(msg)
        logger.warning("Threads未投稿 → 手動投稿をDiscordに通知")

    logger.info("=== 緊急投稿完了 ===")


if __name__ == "__main__":
    main()
