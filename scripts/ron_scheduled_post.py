"""
ron_scheduled_post.py
ロン担当: スケジュール投稿（18時・21時）
GitHub Issueのマルフォイ承認コメントから該当スロットのテキストを取得して投稿する
GitHub Actions cron で自動実行される。
"""

import os
import sys
import re
import argparse
import requests
import time
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))  # 2026-08-26 統一（UTCズレ事故の根絶）
from utils.github_issues import GitHubIssues
from utils import post_guard
pass  # discord send_post_complete removed
from utils.sheets_logger import log_post
from utils.agent_config import name as _n
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

THREADS_ACCESS_TOKEN    = os.getenv("THREADS_ACCESS_TOKEN")
THREADS_USER_ID         = os.getenv("THREADS_USER_ID")
GITHUB_TOKEN            = os.getenv("GITHUB_TOKEN")
GITHUB_REPO             = os.getenv("GITHUB_REPO")
DISCORD_WEBHOOK_URL     = os.getenv("DISCORD_WEBHOOK_URL")
SPREADSHEET_ID          = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")
THREADS_API_BASE        = "https://graph.threads.net/v1.0"

# ── ネットワーク層のタイムアウトとリトライ（2026-08-15 修正）──
# publish は正常時でも読み取りに 8〜20 秒かかることがあるため、read timeout=15 は
# 正常系を定期的に切断してしまう。タイムアウトは (接続, 読み取り) で長めに取り、
# 環境変数 THREADS_API_READ_TIMEOUT で上書きできるようにする。
# タイムアウト・接続断は HTTP ステータスを持たないため、ステータス条件だけの
# リトライでは素通りで raise してしまう → _is_transient() で明示的に再試行対象にする。
# publish は creation_id が一意キーなので、同じコンテナの再送は投稿を増やさない（冪等）。
REQUEST_TIMEOUT = (10, int(os.getenv("THREADS_API_READ_TIMEOUT", "60")))


def _is_transient(exc: Exception) -> bool:
    """ステータスを持たない一時障害（タイムアウト・接続断）か。"""
    return isinstance(exc, (requests.exceptions.Timeout,
                            requests.exceptions.ConnectionError))


SLOT_LABELS = {
    2: "🌆 18時・夕方投稿",
    3: "🌙 21時・夜投稿",
}


def create_threads_container(text: str, reply_to_id: str = None, max_retries: int = 3) -> str:
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads"
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
            # 5xx系（サーバー側一時障害）はリトライ対象
            if resp.status_code >= 500 and attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                logger.warning(f"コンテナ作成 5xx（attempt {attempt+1}/{max_retries}）→ {wait}秒待機してリトライ")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            container_id = resp.json().get("id")
            label = "返信コンテナ" if reply_to_id else "コンテナ"
            logger.info(f"{label}作成成功: {container_id}")
            return container_id
        except requests.exceptions.RequestException as e:
            last_exc = e
            # サーバー側一時障害（5xx）とタイムアウト・接続断はリトライ
            if attempt < max_retries - 1 and (
                _is_transient(e) or any(code in str(e) for code in ["500", "502", "503", "504"])
            ):
                wait = 5 * (attempt + 1)
                logger.warning(
                    f"コンテナ作成失敗（attempt {attempt+1}/{max_retries}・{type(e).__name__}）"
                    f"→ {wait}秒待機してリトライ")
                time.sleep(wait)
                continue
            logger.error(f"Threadsコンテナ作成失敗: {e}")
            raise
    raise last_exc if last_exc else RuntimeError("container creation failed")


def publish_threads_container(container_id: str, max_retries: int = 3) -> str:
    url = f"{THREADS_API_BASE}/{THREADS_USER_ID}/threads_publish"
    payload = {
        "creation_id": container_id,
        "access_token": THREADS_ACCESS_TOKEN,
    }
    # リトライ付き（コンテナ処理に時間がかかる場合がある）
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 400 and attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                logger.warning(f"公開リクエスト400エラー（attempt {attempt+1}/{max_retries}）→ {wait}秒待機してリトライ")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            # 400（コンテナ処理待ち）に加え、タイムアウト・接続断も再試行する。
            # creation_id が一意キーなので同じコンテナの再公開は投稿を増やさない。
            if attempt < max_retries - 1 and (_is_transient(e) or "400" in str(e)):
                wait = 5 * (attempt + 1)
                logger.warning(
                    f"公開リクエスト失敗（attempt {attempt+1}/{max_retries}・{type(e).__name__}）"
                    f"→ {wait}秒待機してリトライ（creation_id={container_id}）")
                time.sleep(wait)
                continue
            logger.error(f"Threads公開リクエスト失敗: {e}")
            raise
    post_id = resp.json().get("id")
    logger.info(f"Threads投稿成功: Post ID = {post_id}")
    return post_id


def clean_post_text(text: str) -> str:
    """投稿テキストからフォーマットラベルを除去する"""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if re.match(r'^\[?\d+投稿目[：:].+\]?$', line.strip()):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def get_slot_text_from_issue(issue_number: int, gh: GitHubIssues, slot_num: int) -> str:
    """マルフォイの承認コメントから指定スロットのテキストを取得"""
    comments = gh.get_comments(issue_number)
    for comment in reversed(comments):
        if f"{_n('malfoy')}より：承認申請" in comment.body:
            # 推奨投稿案セクション以降のみ対象（レビュー結果のコードブロック誤検出を防止）
            body = comment.body
            marker = "推奨投稿案"
            idx = body.find(marker)
            if idx != -1:
                body = body[idx:]
            code_blocks = re.findall(r'```\n([\s\S]*?)\n```', body)
            if len(code_blocks) >= slot_num:
                text = clean_post_text(code_blocks[slot_num - 1])
                if text:
                    return text
    return ""


def check_approved(issue_number: int, gh: GitHubIssues) -> bool:
    """承認コメントがあるか確認"""
    comments = gh.get_comments(issue_number)
    return any(
        "承認" in c.body and c.user.type != "Bot" and "申請" not in c.body
        for c in comments
    )


def find_approved_issue(gh: GitHubIssues) -> object:
    """当日→前日の順で承認済みIssueを検索する（cron遅延による日付またぎ対策）"""
    JST = timezone(timedelta(hours=9))
    today     = datetime.now(JST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

    for date_str in [today, yesterday]:
        title_prefix = f"【運用ループ】{date_str}"
        for state in ["open", "closed"]:
            issues = gh.repo.get_issues(state=state, labels=[gh.DAILY_OP_LABEL])
            for issue in issues:
                if issue.title.startswith(title_prefix):
                    if check_approved(issue.number, gh):
                        logger.info(f"承認済みIssueを発見 ({date_str}): #{issue.number}")
                        return issue
                    logger.info(f"Issue #{issue.number} ({date_str}) は未承認")
                    break  # 日付一致Issueは1つのみ
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--slot", type=int, required=True, choices=[2, 3],
        help="スロット番号（2=18時, 3=21時）"
    )
    args = parser.parse_args()

    slot_label = SLOT_LABELS.get(args.slot, f"SLOT_{args.slot}")
    logger.info(f"=== ロン スケジュール投稿開始 [{slot_label}] ===")

    gh    = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 当日→前日の順で承認済みIssueを検索（cron遅延による日付またぎ対策）
    issue = find_approved_issue(gh)
    if issue is None:
        logger.info("承認済みのIssueが見つかりません（当日・前日を検索済み）。投稿をスキップします。")
        sys.exit(0)  # exit(0)=正常終了でcronを維持（exit(1)はGitHubがcronを自動無効化する）

    # Python側の投稿済みチェック（yml側チェックとの2重防止）
    # yml側のgrepがコメント形式にマッチしない場合の保険
    slot_keyword = "18時" if args.slot == 2 else "21時"
    comments_for_check = gh.get_comments(issue.number)
    already_posted = any(
        slot_keyword in c.body and "投稿完了" in c.body
        for c in comments_for_check
    )
    if already_posted:
        logger.info(f"SLOT_{args.slot}（{slot_keyword}）は既に投稿済みです。スキップします。")
        sys.exit(0)

    # スロットテキスト取得
    post_text = get_slot_text_from_issue(issue.number, gh, args.slot)
    if not post_text:
        logger.info(f"SLOT_{args.slot} のテキストが見つかりません。投稿をスキップします。")
        sys.exit(0)  # exit(0)=正常終了でcronを維持

    logger.info(f"投稿テキスト（先頭50文字）: {post_text[:50]}...")

    # ── 投稿してはいけないテキストの最終関所（2026-09-01・共通化）──────────
    # 判定は utils/post_guard.py に一本化した。以前はキットごとに別実装で、
    # ③にはあった検査が④に無く、`（SLOT_3 抽出失敗）` が実際に公開された。
    _reason = post_guard.unpostable_reason(post_text)
    if _reason:
        _msg = (f"SLOT_{args.slot} は投稿できません（{_reason}）。投稿を中止します。"
                f"{chr(10)}先頭200文字:{chr(10)}{post_text[:200]}")
        logger.error(_msg)
        try:
            notify_error_discord(args.slot, _msg)
        except Exception:
            pass
        sys.exit(1)

    # ツリー投稿
    thread_parts = [p.strip() for p in post_text.split("===THREAD===") if p.strip()]
    logger.info(f"投稿パーツ数: {len(thread_parts)}")

    container_id = create_threads_container(thread_parts[0])
    time.sleep(5)  # コンテナ処理待ち
    post_id      = publish_threads_container(container_id)

    # ツリーをチェーン形式で投稿（親→ツリー1→ツリー2→...）
    #
    # ⚠️ ここで例外を投げっぱなしにしない（2026-08-15 修正）。
    #   旧コードはツリー途中の例外でスクリプトごと落ちたため、
    #   **親投稿は出ているのに Issue の完了コメントも Sheets の記録も残らなかった**。
    #   その結果、監視は「完了コメントが無い＝不投稿」と判定し、
    #   実際には出ている投稿を「出ていない」と報告する（＝原因調査が空振りする）。
    #   出た事実は必ず記録し、切断は切断として報告し、runは赤で落とす。
    last_id = post_id
    posted_parts = 1
    tree_error = None
    for i, part in enumerate(thread_parts[1:], 2):
        try:
            time.sleep(5)  # API制限+コンテナ処理待ち
            reply_container = create_threads_container(part, reply_to_id=last_id)
            time.sleep(5)  # 返信コンテナ処理待ち
            reply_id = publish_threads_container(reply_container)
            last_id = reply_id  # 次のツリーはこの投稿に繋げる
            posted_parts += 1
            logger.info(f"ツリー{i}投稿完了: {reply_id}")
        except Exception as e:
            tree_error = f"ツリー{i}投稿失敗: {type(e).__name__}: {e}"
            logger.error(f"SLOT_{args.slot} {tree_error}（以降のツリーは投稿されません）")
            break

    posted_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    if tree_error:
        status_line = (
            f"⚠️ **ツリー切断**（{len(thread_parts)}本中 {posted_parts}本まで投稿済み）\n"
            f"失敗内容: `{tree_error}`\n"
            f"親投稿ID: `{post_id}`（親は出ています。二重投稿になるので再実行しないでください）"
        )
    else:
        status_line = "投稿成功" + (f"（{len(thread_parts)}連投）" if len(thread_parts) > 1 else "")

    comment_body = f"""## 📤 {_n('ron')}より：{slot_label} 投稿完了

<!-- SLOT_{args.slot} 投稿完了 -->

**投稿日時:** {posted_at}
**投稿ID:** `{post_id}`

**投稿テキスト:**
```
{post_text}
```

**ステータス:** {status_line}
"""
    gh.add_comment(issue.number, comment_body)
    # Google Sheets に記録
    log_post(SPREADSHEET_ID, GOOGLE_CREDENTIALS_PATH,
             slot=args.slot, post_text=post_text, post_id=post_id, issue_number=issue.number)
    print(f"POST_ID={post_id}")
    print(f"ISSUE_NUMBER={issue.number}")
    if tree_error:
        # 記録を残した上で run は赤にする（緑のまま切断を黙らせない）
        logger.error(f"=== ロン スケジュール投稿 ツリー切断で終了 [{slot_label}] ===")
        sys.exit(1)
    logger.info(f"=== ロン スケジュール投稿完了 [{slot_label}] ===")


if __name__ == "__main__":
    main()
