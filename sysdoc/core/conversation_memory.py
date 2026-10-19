import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List


FOLLOWUP_SIGNALS = {
    "it", "that", "this", "those", "them", "same", "again", "also", "too",
    "why", "still", "more", "another", "else", "instead", "better", "worse",
}
FOLLOWUP_PHRASES = ("what about", "what if", "how about", "can you", "does it", "is it")


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


class ConversationMemory:
    def __init__(self, path: str, max_turns: int = 50) -> None:
        self.path = path
        self.max_turns = max_turns
        self.turns: List[ConversationTurn] = []
        self._load()

    def add(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]
        # Fix #13 — only write after the model reply (both sides of exchange saved at once)
        if role == "model":
            self._save()

    def is_followup(self, user_input: str) -> bool:
        if not self.turns:
            return False
        lower = user_input.lower()
        if set(lower.split()) & FOLLOWUP_SIGNALS:
            return True
        if any(phrase in lower for phrase in FOLLOWUP_PHRASES):
            return True
        if len(lower.split()) < 5 and len(self.turns) >= 2:
            return True
        return False

    def get_history(self, n: int = 12) -> List[Dict]:
        recent = self.turns[-(n * 2):]
        return [{"role": t.role, "parts": [t.content]} for t in recent]

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([asdict(t) for t in self.turns], f, indent=2)
            os.replace(tmp, self.path)  # atomic rename
        except Exception:
            pass

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.turns = [ConversationTurn(**item) for item in data]
        except Exception:
            self.turns = []
