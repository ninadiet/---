# -*- coding: utf-8 -*-
"""
kb_fetch.py — 在籍中だけ、運営のKVから配信ファイルを取得して operation/knowledge/ を更新する。

なぜ在るか（2026-08-11 新設）
──────────────────────────────────────────────────────────────
Geminiのモデルが引退したとき（例：新規アカウントでの gemini-2.5 系 404）、
モデルの試行順（gemini_model_chain.txt）を運営が遠隔更新できるようにする。
これが無いと、モデル変更のたびに全員へZIP再配布が必要になる。

安全設計（現行ユーザーを絶対に壊さないための約束）
──────────────────────────────────────────────────────────────
1. どんな失敗でも exit 0（このスクリプトが理由でサイクルは止まらない）
2. 取得成功時だけ差し替える（一時ファイル→置換。失敗時はローカルの現物を温存）
3. 取得できなくても動く（読む側 gemini_client.py は内蔵連鎖で動く）

使い方: python scripts/utils/kb_fetch.py   （daily-cycle が自動で呼ぶ）
配信ファイル一覧: キット直下の hog_kb_list.txt（1行1ファイル・#はコメント）
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth_check import _read_member_id, _U2_ENDPOINT_DEFAULT, _U2_KIT_DEFAULT

ROOT = Path(__file__).resolve().parent.parent.parent
LIST_PATH = ROOT / "hog_kb_list.txt"
DEST_DIR = ROOT / "operation" / "knowledge"


def _fetch_doc(endpoint: str, kit: str, uid: str, doc: str) -> str | None:
    sep = "&" if "?" in endpoint else "?"
    url = (f"{endpoint}{sep}id={urllib.parse.quote(uid)}"
           f"&kit={urllib.parse.quote(kit)}&doc={urllib.parse.quote(doc)}")
    # CloudflareがUA無し（Python-urllib）を403でブロックするためUA必須（auth_check.pyと同じ）
    req = urllib.request.Request(url, headers={"User-Agent": "lm-kit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("ok") and isinstance(d.get("text"), str) and d["text"].strip():
            return d["text"]
    except Exception:
        pass
    return None


def main() -> int:
    uid = _read_member_id()
    if not uid:
        print("[kb_fetch] DISCORD_USER_ID なし → スキップ（内蔵設定で動作）")
        return 0
    try:
        lines = LIST_PATH.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        print("[kb_fetch] hog_kb_list.txt なし → スキップ")
        return 0
    endpoint = os.environ.get("LM_AUTH_ENDPOINT", _U2_ENDPOINT_DEFAULT)
    kit = os.environ.get("LM_AUTH_KIT", _U2_KIT_DEFAULT)
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for line in lines:
        doc = line.split("#", 1)[0].strip()
        # パス区切りを含む名前は不正（DEST_DIR の外に書かせない）
        if not doc or "/" in doc or "\\" in doc or ".." in doc:
            continue
        text = _fetch_doc(endpoint, kit, uid, doc)
        if text is None:
            print(f"[kb_fetch] {doc}: 取得できず → ローカル温存")
            continue
        tmp = DEST_DIR / (doc + ".tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(DEST_DIR / doc)
            print(f"[kb_fetch] {doc}: 更新（{len(text)}文字）")
        except OSError as e:
            print(f"[kb_fetch] {doc}: 書き込み失敗 → 温存（{e}）")
            try:
                tmp.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
