"""
Comet Memory — Short-term (RAM) + Long-term (ChromaDB on disk).
Injected into the browser-use agent prompt as context.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from comet.utils.logger import CometLogger

try:
    import chromadb
    from chromadb.utils import embedding_functions
    _CHROMA_OK = True
except ImportError:
    _CHROMA_OK = False


@dataclass
class MemoryEntry:
    content:    str
    entry_type: str = "observation"
    metadata:   dict = field(default_factory=dict)
    timestamp:  float = field(default_factory=time.time)


class CometMemory:
    """
    Two-level memory:
      - Short-term : Python list (current session RAM)
      - Long-term  : ChromaDB vector store (persisted on disk)
    """

    def __init__(self, logger: CometLogger,
                 memory_dir: str = "comet/memory",
                 collection: str = "comet_memory",
                 session_id: Optional[str] = None):
        self.logger     = logger
        self.session_id = session_id or f"s_{int(time.time())}"
        self._short: list[MemoryEntry] = []
        self._cycle = 0
        self._lt_ok = False

        if _CHROMA_OK:
            try:
                self._client = chromadb.PersistentClient(path=memory_dir)
                emb = embedding_functions.DefaultEmbeddingFunction()
                self._col = self._client.get_or_create_collection(
                    name=collection,
                    embedding_function=emb,
                    metadata={"hnsw:space": "cosine"},
                )
                self._lt_ok = True
                self.logger.info(
                    f"Mémoire long terme : {self._col.count()} souvenirs")
            except Exception as e:
                self.logger.error(f"ChromaDB indisponible : {e}")

    # ── Write ──────────────────────────────────────────────────

    def remember(self, content: str, entry_type: str = "observation",
                 metadata: Optional[dict] = None, persist: bool = False):
        entry = MemoryEntry(
            content    = content,
            entry_type = entry_type,
            metadata   = metadata or {"session": self.session_id},
        )
        self._short.append(entry)
        if persist:
            self._save_lt(entry)

    def remember_cycle(self, thought: str, action: str,
                       args: dict, observation: str):
        self._cycle += 1
        content = (
            f"[Cycle {self._cycle}]\n"
            f"Pensée    : {thought}\n"
            f"Action    : {action}({json.dumps(args, ensure_ascii=False)[:80]})\n"
            f"Résultat  : {observation[:400]}"
        )
        self.remember(
            content    = content,
            entry_type = "cycle",
            metadata   = {"session": self.session_id,
                          "action": action, "cycle": self._cycle},
            persist    = (self._cycle % 5 == 0),
        )

    def save_result(self, task: str, result: str):
        if not self._lt_ok:
            return
        entry = MemoryEntry(
            content    = f"Tâche : {task}\nRésultat : {result}",
            entry_type = "result",
            metadata   = {"session": self.session_id, "task": task[:100]},
        )
        self._save_lt(entry)

    # ── Read ───────────────────────────────────────────────────

    def get_recent_text(self, n: int = 8) -> str:
        return "\n\n".join(
            f"[{e.entry_type.upper()}] {e.content}"
            for e in self._short[-n:]
        )

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._lt_ok or self._col.count() == 0:
            return []
        try:
            res = self._col.query(
                query_texts=[query],
                n_results=min(top_k, self._col.count()),
            )
            memories = []
            for doc, meta, dist in zip(
                res["documents"][0],
                res["metadatas"][0],
                res["distances"][0],
            ):
                memories.append({
                    "content":   doc,
                    "metadata":  meta,
                    "relevance": round(1.0 - float(dist), 3),
                })
            return sorted(memories, key=lambda x: x["relevance"], reverse=True)
        except Exception as e:
            self.logger.error(f"Recall error : {e}")
            return []

    def get_context_for_prompt(self, goal: str) -> str:
        parts = []
        memories = self.recall(goal, top_k=3)
        if memories:
            parts.append("SOUVENIRS PERTINENTS :\n" + "\n".join(
                f"  • {m['content'][:200]}" for m in memories))
        recent = self.get_recent_text(n=8)
        if recent:
            parts.append(f"HISTORIQUE RÉCENT :\n{recent}")
        return "\n\n".join(parts) if parts else "Nouvelle session."

    # ── Internal ───────────────────────────────────────────────

    def _save_lt(self, entry: MemoryEntry):
        if not self._lt_ok:
            return
        try:
            doc_id = f"{self.session_id}_{entry.entry_type}_{int(entry.timestamp*1000)}"
            self._col.add(
                documents=[entry.content],
                metadatas=[{**entry.metadata,
                            "type": entry.entry_type,
                            "ts":   str(entry.timestamp)}],
                ids=[doc_id],
            )
        except Exception as e:
            self.logger.error(f"Erreur save long-terme : {e}")
