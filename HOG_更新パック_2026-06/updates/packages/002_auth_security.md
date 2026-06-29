# 📦 アップデート 002: 月次認証セキュリティ強化（2026年6月）

**バージョン**: v1.1
**目的**: 月次キーファイルを受け取っていない顧客のエージェントを完全停止させる
**対象**: 全顧客（必須）
**⚠️ 今月1回のみ適用・来月以降は自動化される**

---

## 📂 このパッケージで更新されるファイル

```
updates/packages/002_files/
├── auth_check.py      → scripts/utils/auth_check.py    （上書き）
├── auth_gate.py       → scripts/auth_gate.py            （上書き）
└── SYS_VER_LOCK.md   → SYS_VER_LOCK.md                （上書き）
```

---

## 🎯 適用フロー（Claude Code 実行手順）

### Phase 1: ファイルのコピー

以下を実行する：

```
配布パック/updates/packages/002_files/auth_check.py
→ 顧客プロジェクト/scripts/utils/auth_check.py  （上書き保存）

配布パック/updates/packages/002_files/auth_gate.py
→ 顧客プロジェクト/scripts/auth_gate.py  （上書き保存）

配布パック/updates/packages/002_files/SYS_VER_LOCK.md
→ 顧客プロジェクト/SYS_VER_LOCK.md  （上書き保存）
```

---

### Phase 2: 各スクリプトへの認証チェック追加

以下の各スクリプトに `check_auth()` が呼ばれているか確認する。
未適用のものに対して、`load_dotenv()` の直後に以下を追記する：

```python
from utils.auth_check import check_auth

_auth_ok, _auth_msg = check_auth()
if not _auth_ok:
    import sys as _sys
    print(f"[認証失敗] {_auth_msg}", file=_sys.stderr)
    _sys.exit(1)
```

対象スクリプト（`check_auth` が含まれているものはスキップ）：
- `scripts/hermione_research.py`
- `scripts/luna_write.py`
- `scripts/malfoy_review.py`
- `scripts/ron_post.py`
- `scripts/ron_fetch.py`
- `scripts/ron_auto_measure.py`
- `scripts/ron_scheduled_post.py`
- `scripts/snape_daily.py`
- `scripts/snape_report.py`
- `scripts/urgent_post.py`

---

### Phase 3: GitHub Actions ワークフローに認証ステップを追加

⚠️ **これが今回の核心です。** ここを適用すると月次キーなしで自動投稿が止まります。

以下のワークフロー全てに、`pip install` ステップの直後に認証ステップを追加する：

```yaml
      - name: "🔒 月次トークン認証"
        env:
          HOG_MONTHLY_TOKEN: ${{ secrets.HOG_MONTHLY_TOKEN }}
        run: cd scripts && python auth_gate.py
```

対象ワークフロー（全て `.github/workflows/` 配下）：
- `daily-cycle.yml`
- `approve-and-post.yml`
- `auto-measure.yml`
- `correct.yml`
- `measure.yml`
- `scheduled-post-slot2.yml`
- `scheduled-post-slot3.yml`
- `snape-daily.yml`
- `urgent-post.yml`

すでに `auth_gate.py` が含まれているワークフローはスキップ。

---

### Phase 4: CLAUDE.md の「更新」ハンドラーを修正

顧客プロジェクトの `CLAUDE.md` の **パターン1（.keyファイル）** の処理を以下に更新する：

```
**パターン1：`access_HOG-YYYY-MM.key` ファイルの場合**
1. `operation/auth/` フォルダに保存
2. ファイルを読み込んで valid_until を確認
3. ファイルの1行目（トークン文字列）を取り出す
4. GitHub Secret を更新する：
   Bash で以下を実行：
   TOKEN=$(head -1 operation/auth/access_HOG-*.key | tr -d '[:space:]')
   gh secret set HOG_MONTHLY_TOKEN --body "$TOKEN"
5. 「✅ トークンを更新しました。有効期限：XXXX / GitHub Secret も更新しました」と表示
```

上記の指示を既存の パターン1 の内容と置き換える。

---

### Phase 5: HOG_MONTHLY_TOKEN を今すぐ設定（初回のみ）

ワークフローに認証ステップを追加した直後、現在の .key ファイルから
`HOG_MONTHLY_TOKEN` シークレットを設定する：

```bash
# operation/auth/ に .key ファイルがあるか確認
ls operation/auth/access_HOG-*.key 2>/dev/null

# あれば1行目のトークンを取得してSecretに設定
TOKEN=$(head -1 operation/auth/access_HOG-*.key | tr -d '[:space:]')
if [ -n "$TOKEN" ]; then
    gh secret set HOG_MONTHLY_TOKEN --body "$TOKEN"
    echo "✅ HOG_MONTHLY_TOKEN を設定しました: ${TOKEN:0:20}..."
else
    echo "⚠️ .key ファイルが見つかりません。ステップ①でキーを受け取ってから再実行してください。"
fi
```

**もし .key ファイルがない場合：**
「ステップ① のキーファイルを先に受け取ってドロップしてください。その後「更新」と入力するとGitHub Secretも自動設定されます。」と表示して停止。

---

### Phase 6: git push で GitHub Actions に反映

```bash
git add .
git commit -m "security: 月次認証強化（HOG-2026-06-A）"
git push origin main
```

---

### Phase 7: 完了確認

以下を表示する：
```
✅ セキュリティ強化の適用が完了しました。

【認証が止まるケース（全部カバー）】
  .key ファイルがない（ローカル）   → ✗ Claude Code 停止
  valid_until が過去日付           → ✗ 停止
  チェックサム不正（偽造）          → ✗ 停止
  HOG_MONTHLY_TOKEN 未設定        → ✗ GitHub Actions 停止
  HOG_MONTHLY_TOKEN の月が違う     → ✗ GitHub Actions 停止

【来月以降の操作】
毎月1日にDiscordへキーが届きます。
.key ファイルをドロップして「更新」と入力するだけで
ローカルとGitHub Secret が両方自動更新されます。
```

---

## ✅ 完了チェックリスト

- [ ] Phase 1: auth_check.py・auth_gate.py・SYS_VER_LOCK.md コピー完了
- [ ] Phase 2: 全スクリプトに check_auth() 追加確認
- [ ] Phase 3: 全ワークフローに認証ステップ追加（HOG_MONTHLY_TOKEN使用）
- [ ] Phase 4: CLAUDE.md パターン1 更新（GitHub Secret 自動更新）
- [ ] Phase 5: HOG_MONTHLY_TOKEN シークレット初期設定
- [ ] Phase 6: git push 完了
- [ ] Phase 7: 完了確認表示

---

*アップデート 002 v1.1 / GitHub Actions認証対応 / 2026-06 / 顧客配布用のみ*
