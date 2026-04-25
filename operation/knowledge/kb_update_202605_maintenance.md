---
sys_ver: HOG-2026-05-A
pack_id: HOG-2026-05
expires: 2026-07-31
update_type: append
issued_by: ai-community-hogwarts
---

# 月次更新パック：2026年5月 システム改善・機能追加

> 適用方法：Claude Codeを開き、このファイルを添付して「更新」と入力するだけ

---

## 📦 今月の更新内容

**システム保守：**
- 投稿文への禁止文字（* " ' `）混入を機械的にゼロにする仕組みを実装
- Threadsトークン自動更新を週1回（日曜AM8:00）に変更、失敗時はDiscord通知
- SLOT_2/SLOT_3もGAS主系化済み（cron遅延の影響を排除）
- トークンリフレッシュ順序バグを修正（失敗してもDiscord即通知）

**新機能：**
- Discord `/add-idea` コマンドで外出先からネタを即時投稿できる仕組みを追加

---

## 🔔 Discord通知パターン別 対応ガイド

通知が来ない = 気づけない を根絶するため、全失敗ケースでDiscord通知が届きます。

| 通知内容 | 意味 | 対応 |
|---|---|---|
| ✅ 緊急投稿完了 | /add-idea が成功 | 対応不要 |
| 🧪 テスト投稿案（未投稿） | dry_run実行 | 内容確認のみ |
| ⚠️ Threadsトークン自動更新に失敗 | 週次リフレッシュ失敗 | 手動更新が必要（下記手順） |
| ❌ 緊急投稿に失敗 | /add-idea エラー | GitHubのActionsログ確認 |
| ⛔ ファクトチェック不通過 | ネタに問題あり | 内容を見直して再送信 |

### 緊急時：Threadsトークン手動更新手順

1. Threadsアプリを開く
2. プロフィール → 設定 → アカウント → Metaとのリンク
3. 「リンクを解除して再リンク」を実行
4. Meta Developers から新しいトークンを取得
5. GitHubリポジトリ → Settings → Secrets → THREADS_ACCESS_TOKEN を更新

---

## 📱 新機能：Discord /add-idea の使い方

iPhoneのDiscordから外出先でネタを思いついたとき、その場で投稿できます。

### セットアップ（初回のみ・約30分）

1. **Discord Developer Portal でアプリ作成**
   - https://discord.com/developers/applications → 「New Application」
   - 「Bot」メニュー → 「Add Bot」→ トークンをコピー

2. **Botをサーバーに招待**
   - 「OAuth2」→「URL Generator」→ 「bot」「applications.commands」にチェック
   - 生成したURLをブラウザで開いてサーバーに追加

3. **Cloudflare Worker をデプロイ**（無料枠で運用）
   - https://workers.cloudflare.com → ダッシュボードを開く
   - 「Create a Worker」→ 以下のコードを貼り付けてデプロイ

```javascript
export default {
  async fetch(request, env) {
    if (request.method !== 'POST') return new Response('OK');
    const body = await request.json();

    // Discord署名検証
    const signature = request.headers.get('X-Signature-Ed25519');
    const timestamp = request.headers.get('X-Signature-Timestamp');
    // (署名検証コードは省略 - 本番では必須)

    const { type, data } = body;
    if (type === 1) return Response.json({ type: 1 }); // PING

    if (data?.name === 'add-idea') {
      const idea = data.options?.find(o => o.name === 'idea')?.value || '';
      await triggerGitHubActions(idea, false, env);
      return Response.json({ type: 4, data: { content: `✅ ネタを受け取りました！1〜3分で投稿されます。\n\n> ${idea}` } });
    }
    if (data?.name === 'add-idea-dry') {
      const idea = data.options?.find(o => o.name === 'idea')?.value || '';
      await triggerGitHubActions(idea, true, env);
      return Response.json({ type: 4, data: { content: `🧪 テストモードで実行します。投稿案がDiscordに届きます。` } });
    }
    return Response.json({ type: 4, data: { content: '不明なコマンドです' } });
  }
};

async function triggerGitHubActions(idea, dryRun, env) {
  await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/urgent-post.yml/dispatches`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      ref: 'master',
      inputs: { idea, dry_run: String(dryRun) }
    }),
  });
}
```

4. **Cloudflare Worker の環境変数を設定**
   - Settings → Variables → 以下を追加：
     - `GITHUB_REPO` : あなたのリポジトリ名（例：yamada/hogwarts-taro）
     - `GITHUB_TOKEN` : GitHubトークン（repoスコープ）

5. **Discord側にWorker URLを登録**
   - Developer Portal → アプリ → General Information
   - 「Interactions Endpoint URL」にCloudflareのURLを貼り付け

### 使い方

```
/add-idea idea:AI運用で1日30分が5分になった話
/add-idea-dry idea:テスト投稿です
```

---

## 🎯 ジャンル絞り込みカスタマイズ

幅広いテーマより、絞ったテーマの方がフォロワーが定着します。

### 設定方法

`operation/knowledge/kb_sys_ref_v001.md` の「🎤 自分のアカウントの声」セクションの
「発信テーマ・ポジション」を書き換えるだけです。

### 絞り方の例

| 型 | 例 |
|---|---|
| ツール特化型 | Claude Code × 個人事業主の業務改善 |
| 読者層特化型 | 副業初心者 × AI自動化入門 |
| 成果特化型 | フォロワー1000人突破の仕組み化ノウハウ |
| 業界特化型 | フリーランスデザイナー × AI活用時短術 |

希望ジャンルが決まったら Claude Code で「ジャンルを◯◯に変更したい」と伝えると、
リサーチキーワードや実体験バンクも一括で調整します。

---

## ⏰ SLOT_2 / SLOT_3 GASトリガー追加（未設定の方）

SLOT_1（7時）しか動いていない場合、以下を追加してください。

1. https://script.google.com/ を開く
2. 既存のプロジェクトを開く（設定済みの場合）
3. 「トリガー」→ 「+トリガーを追加」で2つ追加：

| 関数名 | 時間帯 |
|---|---|
| `triggerScheduledPostSlot2` | 午後5時〜6時 |
| `triggerScheduledPostSlot3` | 午後8時〜9時 |

詳細手順：`SETUP_GAS_TRIGGER.md` を参照してください。
