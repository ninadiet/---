---
sys_ver: HOG-2026-05-A
lock_date: 2026-05-01
integrity_chain:
  - file: CLAUDE.md
    ref_id: CLAUDE-2026-04-A
  - file: operation/knowledge/kb_sys_ref_v001.md
    ref_id: KB-2026-05-A
    integrity_tag: 7731
  - file: .github/agents/luna.agent.md
    ref_id: LW-2026-04-A
    ref_integrity: 7731
  - file: operation/auth/access_HOG-2026-05.key
    ref_id: AUTH-2026-05
  - file: operation/auth/access_AFFI-2026-05.key
    ref_id: AUTH-AFFI-2026-05
---

## バージョン整合性ロック（編集禁止）

このファイルはシステムの全ファイルバージョンを管理します。
各ファイルのref_idが一致しない場合、システムはdegraded_modeで動作します。

next_update_ref: HOG-2026-06-A（更新パックで自動更新）
