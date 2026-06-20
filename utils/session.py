"""
Session 数据管理模块。

整个工作流用一个 session.json 贯穿，保证每一步可追溯。
"""

import json
import os
from datetime import datetime
from pathlib import Path

# 默认 session 存储路径
DEFAULT_STORE = Path(__file__).parent.parent / "sessions"


def ensure_store(path=None):
    store = Path(path) if path else DEFAULT_STORE
    store.mkdir(parents=True, exist_ok=True)
    return store


def create_session(teacher_name, article, vocabulary, video_path, store_path=None):
    """创建新的 session 对象（初始化状态）"""
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "session_id": session_id,
        "teacher": teacher_name,
        "created_at": datetime.now().isoformat(),
        "status": "submitted",
        "inputs": {
            "article": article,
            "vocabulary": vocabulary,
            "video_path": str(video_path),
        },
        "asr_result": None,
        "ai_outputs": None,
        "teacher_review": None,
        "outputs": None,
    }


def save_session(session, store_path=None):
    """保存 session 到 JSON 文件"""
    store = ensure_store(store_path)
    path = store / f"{session['session_id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    return str(path)


def load_session(session_id, store_path=None):
    """加载已有 session"""
    store = ensure_store(store_path)
    path = store / f"{session_id}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_sessions(store_path=None):
    """列出所有 session"""
    store = ensure_store(store_path)
    sessions = []
    for p in sorted(store.glob("*.json"), reverse=True):
        with open(p, "r", encoding="utf-8") as f:
            s = json.load(f)
            sessions.append({
                "id": s["session_id"],
                "teacher": s.get("teacher", ""),
                "created": s.get("created_at", ""),
                "status": s.get("status", "unknown"),
            })
    return sessions
