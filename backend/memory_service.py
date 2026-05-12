"""Per-session conversation memory."""
import json
import os
from datetime import datetime
from typing import Dict, List, Any
from config import config


class ConversationMemory:
    """In-memory + on-disk session conversation store."""

    def __init__(self):
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        self._load_all()

    def _session_path(self, session_id: str) -> str:
        return os.path.join(config.CACHE_DIR, f"conv_{session_id}.json")

    def _load_all(self):
        if not os.path.isdir(config.CACHE_DIR):
            return
        for fname in os.listdir(config.CACHE_DIR):
            if not fname.startswith("conv_") or not fname.endswith(".json"):
                continue
            sid = fname[len("conv_"):-len(".json")]
            try:
                with open(os.path.join(config.CACHE_DIR, fname), "r") as f:
                    self.sessions[sid] = json.load(f)
            except Exception:
                self.sessions[sid] = []

    def add_turn(self, session_id: str, role: str, content: str, tool_calls: List[Dict] = None):
        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if tool_calls:
            turn["tool_calls"] = tool_calls
        self.sessions.setdefault(session_id, []).append(turn)
        self._persist(session_id)

    def get_turns(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.sessions.get(session_id, [])[-limit:]

    def clear(self, session_id: str):
        self.sessions.pop(session_id, None)
        path = self._session_path(session_id)
        if os.path.exists(path):
            os.remove(path)

    def _persist(self, session_id: str):
        try:
            with open(self._session_path(session_id), "w") as f:
                json.dump(self.sessions[session_id], f)
        except Exception as e:
            print(f"Memory persist error: {e}")


memory = ConversationMemory()
