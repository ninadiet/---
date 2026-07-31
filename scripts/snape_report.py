"""
snape_report.py
スネイプ担当: 週次コスト・エンゲージメント監視レポートを生成するスクリプト
毎週月曜日に GitHub Actions から自動実行
"""

import os
import csv
from datetime import datetime, timedelta
from pathlib import Path
from utils.github_issues import GitHubIssues
from dotenv import load_dotenv
from loguru import logger
from utils.agent_config import name as _n

load_dotenv()

from utils.auth_check import check_auth

_auth_ok, _auth_msg = check_auth()
if not _auth_ok:
    import sys as _sys
    print(f"[認証失敗] {_auth_msg}", file=_sys.stderr)
    _sys.exit(1)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("GITHUB_REPO")

SCRIPT_DIR      = Path(__file__).resolve().parent
WEEKLY_DIR      = SCRIPT_DIR / ".." / "operation" / "weekly"
API_USAGE_CSV   = WEEKLY_DIR / "api_usage_log.csv"


def get_weekly_issues(gh: GitHubIssues) -> list:
    """今週（月〜日）の運用ループIssueを取得する"""
    today  = datetime.now()
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.strftime("%Y-%m-%d")

    issues = []
    all_issues = gh.repo.get_issues(
        state="all",
        labels=["daily-operation"],
        since=monday,
    )
    for issue in all_issues:
        issues.append(issue)
    return issues


def parse_engagement_from_issue(issue) -> dict:
    """Issueのコメントからエンゲージメントデータを取得する"""
    data = {"likes": 0, "replies": 0, "reposts": 0, "posted": False}
    comments = list(issue.get_comments())
    for comment in comments:
        if "エンゲージメント計測結果" in comment.body:
            lines = comment.body.split("\n")
            for line in lines:
                if "いいね" in line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        try:
                            num = "".join(filter(str.isdigit, parts[2]))
                            data["likes"] = int(num) if num else 0
                        except Exception:
                            pass
                if "返信" in line and "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        try:
                            data["replies"] = int("".join(filter(str.isdigit, parts[2])) or "0")
                        except Exception:
                            pass
        if "投稿完了" in comment.body:
            data["posted"] = True
    return data


# フォロワー数桁の育成初期段階に合わせて引き下げ（旧: 50件）
WEEKLY_BUZZ_THRESHOLD = 3


def _build_suggestions(post_count: int, likes_list: list, replies_list: list, buzz_count: int, avg_likes: float) -> list:
    """今週の実データに応じた改善提案を組み立てる（固定テンプレを廃止）"""
    suggestions = []
    if post_count == 0:
        suggestions.append("今週投稿が0件でした。daily-cycle.ymlやscheduled-post系ワークフローが正常に動いているか確認してください。")
    elif likes_list and all(l == 0 for l in likes_list):
        suggestions.append(f"今週の投稿{post_count}件すべてでいいねが0件でした。文体の微調整では届かない可能性が高く、フォロワー数の少なさ（リーチの土台）と投稿テーマ・フックの両方を根本から見直す時期です。")
    elif avg_likes < WEEKLY_BUZZ_THRESHOLD:
        suggestions.append(f"平均いいね{avg_likes:.1f}件と低調です。{_n('luna')}に文体・冒頭フックの見直しを依頼してください。")
    elif buzz_count == 0:
        suggestions.append(f"バズ（いいね{WEEKLY_BUZZ_THRESHOLD}件以上）が今週0件でした。{_n('hermione')}にトレンド分析の精度向上を依頼してください。")
    else:
        suggestions.append(f"バズ投稿が{buzz_count}件ありました。良好なパフォーマンスを維持してください。")

    if replies_list and all(r == 0 for r in replies_list):
        suggestions.append("今週は返信が一切ついていません。読者に問いかける投稿（質問形式・共感を誘う一言）を増やしてみてください。")

    suggestions.append("無料枠の消費状況を来週も引き続き監視する")
    return suggestions[:3]


def generate_snape_report(weekly_issues: list, week_str: str) -> str:
    """スネイプの週次レポートを生成する"""
    post_count   = sum(1 for d in weekly_issues if d["engagement"]["posted"])
    likes_list   = [d["engagement"]["likes"] for d in weekly_issues if d["engagement"]["posted"]]
    replies_list = [d["engagement"]["replies"] for d in weekly_issues if d["engagement"]["posted"]]
    avg_likes    = sum(likes_list) / len(likes_list) if likes_list else 0
    buzz_count   = sum(1 for l in likes_list if l >= WEEKLY_BUZZ_THRESHOLD)
    max_likes    = max(likes_list) if likes_list else 0

    suggestions_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(_build_suggestions(post_count, likes_list, replies_list, buzz_count, avg_likes)))

    report = f"""# スネイプ週次監視レポート {week_str}

## ① コスト状況
| サービス | 今週使用量 | 無料枠残量 | 危険度 |
|---|---|---|---|
| Gemini Flash | 確認中 | 確認中 | 🟢 |
| YouTube API | 確認中 | 確認中 | 🟢 |
| Threads API | {post_count}回 | 制限なし | 🟢 |
| GitHub API | 確認中 | 確認中 | 🟢 |

*※ API残量は各コンソールで手動確認してください*

## ② エンゲージメント推移
| 指標 | 今週 |
|---|---|
| 投稿数 | {post_count} |
| 平均いいね | {avg_likes:.1f} |
| バズ投稿数（{WEEKLY_BUZZ_THRESHOLD}+） | {buzz_count} |
| 最高いいね | {max_likes} |

## ③ 問題発生記録
（今週のエラー・問題があればここに記録）

## ④ 改善提案（最大3件）
{suggestions_text}

## ⑤ 来週の注意事項
- 投稿テーマのマンネリ化に注意
- Gemini APIの無料枠残量を週初めに確認すること
- GitHub Issues の承認待ちが滞留していないか確認すること
"""
    return report


def main():
    logger.info("=== スネイプ 週次レポート生成開始 ===")

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)

    # 今週のIssueを取得
    raw_issues    = get_weekly_issues(gh)
    weekly_issues = []
    for issue in raw_issues:
        engagement = parse_engagement_from_issue(issue)
        weekly_issues.append({"issue": issue, "engagement": engagement})

    # 週番号
    now      = datetime.now()
    week_str = now.strftime("%Y年W%V")
    week_num = now.strftime("%YW%V")

    # レポート生成
    report = generate_snape_report(weekly_issues, week_str)

    # ファイル保存
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = WEEKLY_DIR / f"snape_report_{week_num}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"レポート保存: {report_path}")

    # API使用量ログCSVの更新
    if not API_USAGE_CSV.exists():
        with open(API_USAGE_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["週", "投稿数", "平均いいね", "バズ数", "Gemini使用量", "YouTube使用量"])

    likes_list = [d["engagement"]["likes"] for d in weekly_issues if d["engagement"]["posted"]]
    avg_likes  = sum(likes_list) / len(likes_list) if likes_list else 0
    buzz_count = sum(1 for l in likes_list if l >= WEEKLY_BUZZ_THRESHOLD)

    with open(API_USAGE_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([week_str, len(likes_list), f"{avg_likes:.1f}", buzz_count, "確認中", "確認中"])

    logger.info("=== スネイプ 週次レポート生成完了 ===")


if __name__ == "__main__":
    main()
