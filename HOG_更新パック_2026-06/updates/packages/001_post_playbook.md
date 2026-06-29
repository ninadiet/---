# 📦 アップデート 001: 高インプ投稿プレイブック＋ペルソナ確定ガイド＋CTA設計

**バージョン**: v1.1
**目的**: 投稿のインプレッション・フォロー転換率を体系的に向上させ、ビジネス目的に合ったCTA設計を組み込む
**対象**: SNS発信全般（業種・ジャンル・収益化目的不問）
**実証**: 1投稿で最高7万imp/フォロー+23、別投稿1.0-1.7万imp

---

## 📂 含まれるファイル

このパッケージには以下のファイルが含まれます：

```
updates/packages/001_files/
├── _universal_post_playbook.md      （高インプ必勝テンプレ・汎用版）
├── _persona_setup_guide.md          （ペルソナ確定対話ガイド）
├── _purpose_cta_guide.md            （目的別CTA設計・非アフィリ版）
└── affiliate_appeal_patterns.md     （アフィリ訴求パターン6種・アフィリ用）
```

各ファイルの内容:
1. **`_universal_post_playbook.md`** — 必勝8ステップ構造 / 絶対NGリスト / ジャンル別応用例
2. **`_persona_setup_guide.md`** — 7要素の確定プロセス / Claude Code への質問テンプレ / アンチパターン解説
3. **`_purpose_cta_guide.md`** — サービス業・ブランド・コミュニティ・イベント向けCTA6種（非アフィリ）
4. **`affiliate_appeal_patterns.md`** — 商品訴求パターン6種（アフィリエイト・物販向け）

---

## 🎯 適用フロー（Claude Code 実行手順）

### Phase 1: 状況確認（必須）

顧客に以下を質問：

1. **ペルソナ確定状況**：
   - 完全確定（中の人/数字/看板コピー/周辺情報/ジャンル/発信軸が全部明確）
   - 部分確定（一部曖昧）
   - 未確定（これから決めたい）

2. **既存ファイル状況**：
   - `operation/knowledge/buzz_posts.md` の有無
   - `scripts/writer.py` の有無
   - `scripts/content_review.py` の有無
   - `scripts/compliance_officer.py` の有無

→ ファイルが無い場合、相当するファイルを特定するか作成判断

---

### Phase 1.5: CTA目的の確認（必須）

**以下の質問をして顧客の目的を確認すること：**

```
このアカウントの主な目的を教えてください：

A. アフィリエイト・商品販売（楽天・Amazon等のリンク収益化）
B. サービス業の集客（コーチング・コンサル・治療家・サロン等）
C. ブランド・権威構築（専門家としての認知拡大）
D. コミュニティ形成（LINE/Discord等のグループ拡大）
E. イベント・セミナー集客
F. その他（具体的に）

複数該当する場合はすべて教えてください。
```

**判断ルール：**

| 回答 | 適用するCTAファイル |
|---|---|
| A のみ | `affiliate_appeal_patterns.md` |
| B・C・D・E・F | `_purpose_cta_guide.md` |
| A + (B以降) の両方 | 両方コピー |

---

### Phase 2: ペルソナ確定（部分・未確定の場合のみ）

`operation/knowledge/_persona_setup_guide.md` を配布パックから顧客プロジェクトにコピー後、
そのガイドの Step 1-7 を顧客と対話で実行：

- Step 1: 中の人プロフィール確定
- Step 2: 経験規模の数字を出す
- Step 3: 看板コピー（ギャップ訴求）の設計
- Step 4: 周辺情報（リアリティ作り）
- Step 5: 発信ジャンル・核の確定
- Step 6: NG・固定ルール
- Step 7: 全体統合と検証

確定したペルソナを既存の `buzz_posts.md`（または相当ファイル）に追加。

**ペルソナ完全確定済みの場合はこの Phase スキップ**。

---

### Phase 3: ファイルコピー

配布パックから以下のファイルを顧客プロジェクトにコピー：

**共通（全顧客）：**
```
配布パック/updates/packages/001_files/_universal_post_playbook.md
→ 顧客プロジェクト/operation/knowledge/_universal_post_playbook.md

配布パック/updates/packages/001_files/_persona_setup_guide.md
→ 顧客プロジェクト/operation/knowledge/_persona_setup_guide.md
```

**Phase 1.5 の判断に基づいて追加：**
```
# 非アフィリ（B〜F）の場合：
配布パック/updates/packages/001_files/_purpose_cta_guide.md
→ 顧客プロジェクト/operation/knowledge/_purpose_cta_guide.md

# アフィリ（A）の場合：
配布パック/updates/packages/001_files/affiliate_appeal_patterns.md
→ 顧客プロジェクト/operation/knowledge/affiliate_appeal_patterns.md

# 両方の場合：両方コピー
```

---

### Phase 4: writer.py への組み込み

顧客の `scripts/writer.py`（または相当ファイル）のシステムプロンプトに以下を**追記**（上書きしない）：

```python
■ 【最重要】必勝8ステップ構造（実証パターン）
詳細は operation/knowledge/_universal_post_playbook.md 参照

3スロット教育型は以下の構造を厳守：

【1/3 メイン】
- Step 1. 引用フック『○○』（読者の心の声）
- Step 2. 数字権威「○年、○○人見てきて」
- Step 3. 結果先出し「○○が1つだけあった」

【2/3 リプ1】
- Step 4. 答えは1つだけ『○○』
- Step 5. 理由＋なぜ効くか（短く）
- Step 6. 逆ケース対比「逆に○○な人は」

【3/3 リプ2】
- Step 7. 自分の実践（家・現場・自分の体験）
- Step 8. 低コストCTA「今日1回だけ試してみて✨」

■ 数字権威の使い分け
- 個別経験（深い）→ 「○○年、○○人を担当してきて」
- 広域観察（広い）→ 「○○年、○○人見てきて」
- 現場頻度（日常）→ 「毎日○○人にやってる現場で」
```

**CTA に関する追記（Phase 1.5 の目的に応じて分岐）：**

アフィリ目的の場合：
```python
■ CTA設計
アフィリ訴求は operation/knowledge/affiliate_appeal_patterns.md の6パターンを使い分け。
焦らせ・押し付けは禁止。
```

非アフィリ目的の場合：
```python
■ CTA設計
CTA は operation/knowledge/_purpose_cta_guide.md の6パターンを使い分け。
アカウントの目的（サービス集客/コミュニティ/イベント等）に応じたパターンを選択。
```

**追記位置の判断**:
- 既存のシステムプロンプト末尾、または「ルール」セクションがあればその直下に追加
- 既存のペルソナ固定情報セクションは絶対に消さない・触らない

---

### Phase 5: content_review.py への組み込み

顧客の `scripts/content_review.py`（または相当ファイル）に以下のチェック項目を**追記**：

```python
### 必勝テンプレ準拠チェック（教育型投稿）
1. 引用フック『○○』が含まれているか
2. 数字（年数・人数）が含まれているか
3. 「1つだけ」「1つあった」フレーズが含まれているか
4. 「逆に」対比が含まれているか
5. 自分の実践（家・現場・自分の体験）が含まれているか
6. CTA「○日だけ」「○回だけ」「気軽に」「来れる人は」等が含まれているか

→ 上記6項目のうち4項目以上欠けていたら差し戻し
```

---

### Phase 6: compliance_officer.py への組み込み

顧客の `scripts/compliance_officer.py`（または相当ファイル）に以下のNGパターンを**追記**：

```python
# 焦らせ・押し付け訴求NG（アフィリ・非アフィリ共通）
URGENCY_NG_PATTERNS = [
    r"\d+/\d+.*セール", r"\d+月\d+日まで",
    r"明後日まで", r"明日まで", r"\d+日後",
    r"今すぐ買", r"急いで", r"在庫切れ.*前に",
    r"気になる人はチェック",
    r"DMで聞かれたので置いとくね",
    r"絶対買って", r"リピート確定",
    r"ぜひフォローしてください",
    r"登録しないと損",
]

# 乱暴・命令調NG
RUDE_NG_PATTERNS = [
    r"いいから片せ", r"入れろや", r"知らんが",
    r"うるさい", r"黙れ",
]
```

`review_post()` 関数に両チェックを組み込み：

```python
violations.extend(check_urgency_ng(post_text))
violations.extend(check_rude_tone(post_text))
```

---

### Phase 7: テスト投稿生成（5本）

教育型投稿を5本生成。各投稿が以下を満たしているか自己評価：

- ✅ 引用フック『○○』が冒頭にあるか
- ✅ 数字権威があるか
- ✅ 「1つだけ」「1つあった」があるか
- ✅ 逆ケース対比があるか
- ✅ 自分の実践があるか
- ✅ 低コストCTAがあるか（目的に合ったパターンで）
- ✅ NG表現がないか

**5本中4本以上クリアなら適用成功**。
3本以下なら writer.py のプロンプト追記位置を見直し。

---

### Phase 8: 適用記録

顧客プロジェクトの `updates/_APPLIED.md` に以下を追記（ファイルがなければ作成）：

```markdown
# 適用済みアップデート

## 001: 高インプ投稿プレイブック＋ペルソナ確定ガイド＋CTA設計
- 適用日: YYYY-MM-DD
- 適用バージョン: v1.1
- CTA種別: アフィリ / 非アフィリ（サービス業/ブランド/コミュニティ/イベント等）/ 両方
- 適用範囲: 全Phase完了 / Phase 2 スキップ（既存ペルソナ確定済み）/ etc
- テスト投稿準拠度: X/5
- 備考:
```

---

## ✅ 完了チェックリスト

- [ ] Phase 1: 状況確認完了
- [ ] Phase 1.5: CTA目的確認完了（アフィリ/非アフィリ判断済み）
- [ ] Phase 2: ペルソナ確定（必要な場合のみ）
- [ ] Phase 3: ファイルコピー完了（目的に応じたCTAファイル含む）
- [ ] Phase 4: writer.py 追記完了
- [ ] Phase 5: content_review.py 追記完了
- [ ] Phase 6: compliance_officer.py 追記完了
- [ ] Phase 7: テスト投稿5本生成・準拠度確認
- [ ] Phase 8: _APPLIED.md 記録完了

---

## ⚠️ 失敗時のフォールバック

| 問題 | 対応 |
|---|---|
| 既存 writer.py のプロンプト構造が大きく異なる | 顧客と相談して追記位置を確認 |
| ペルソナ確定が30分以上かかる | 一旦中断し、Phase 2を後日再開 |
| テスト投稿で準拠度3本以下 | プロンプト追記位置を見直し |
| CTAの目的が複数あって迷う | 両方のファイルをコピーし、投稿種別で使い分けを提案 |

---

*アップデート 001 v1.1 / CTA分岐対応 / 2026-06*
