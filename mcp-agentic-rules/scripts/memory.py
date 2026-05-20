"""
Persistent Memory System
========================
Cross-session knowledge base for AI agents.

Usage:
    python mcp.py remember "key" "value"
    python mcp.py recall "query"
    python mcp.py forget "key"
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json
import sys
import sqlite3

from .embeddings import embed_text, cosine_similarity
from .utils import Console, find_project_root, get_mcp_dir

@dataclass
class Memory:
    """A memory item."""
    key: str
    value: str
    tags: List[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    access_count: int = 0
    embedding: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Memory':
        return cls(**data)


class MemoryStore:
    """Persistent memory storage."""

    def __init__(self, storage_path: Path = None):
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            import os
            workspace = os.environ.get('MCP_WORKSPACE')
            if workspace:
                self.storage_path = get_mcp_dir() / 'memory'
            else:
                # Use user-level storage for cross-project memory
                home = Path.home()
                self.storage_path = home / '.mcp' / 'memory'

        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_path / 'knowledge.db'
        self.memories: Dict[str, Memory] = {}
        self.conn = None
        self._init_db()
        self.migrate_from_json()
        self.load()

    def _init_db(self):
        """Initialize SQLite database schema."""
        try:
            self.conn = sqlite3.connect(self.db_path, timeout=10.0)
            # Enable WAL mode for high concurrency
            self.conn.execute("PRAGMA journal_mode=WAL")
            with self.conn:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        tags TEXT,
                        created TEXT,
                        updated TEXT,
                        access_count INTEGER DEFAULT 0,
                        embedding TEXT
                    )
                """)
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        arguments TEXT,
                        result_status TEXT,
                        summary TEXT,
                        embedding TEXT
                    )
                """)
        except Exception as e:
            Console.warn(f"Failed to initialize SQLite database: {e}")

    def migrate_from_json(self):
        """Automatically migrate legacy JSON memories to SQLite database."""
        json_path = self.storage_path / 'knowledge.json'
        if json_path.exists() and self.conn:
            try:
                Console.info("Legacy knowledge.json found. Migrating to SQLite...")
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                with self.conn:
                    for key, val in data.items():
                        tags_str = ",".join(val.get('tags', []))
                        emb_str = json.dumps(val.get('embedding', []))
                        self.conn.execute("""
                            INSERT OR IGNORE INTO memories (key, value, tags, created, updated, access_count, embedding)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            key,
                            val.get('value', ''),
                            tags_str,
                            val.get('created', ''),
                            val.get('updated', ''),
                            val.get('access_count', 0),
                            emb_str
                        ))
                
                # Archive the legacy file
                backup_path = json_path.with_suffix('.json.bak')
                json_path.rename(backup_path)
                Console.ok(f"Migrated memories to SQLite and backed up to {backup_path.name}")
            except Exception as e:
                Console.warn(f"Failed to migrate legacy memories: {e}")

    def load(self):
        """Load memories from SQLite."""
        self.memories = {}
        if not self.conn:
            return
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT key, value, tags, created, updated, access_count, embedding FROM memories")
            for row in cursor.fetchall():
                tags = row[2].split(",") if row[2] else []
                embedding = json.loads(row[6]) if row[6] else []
                self.memories[row[0]] = Memory(
                    key=row[0],
                    value=row[1],
                    tags=tags,
                    created=row[3],
                    updated=row[4],
                    access_count=row[5],
                    embedding=embedding
                )
        except Exception as e:
            Console.warn(f"Failed to load memories from SQLite: {e}")

    def save(self):
        """Sync local dictionary state to SQLite database."""
        if not self.conn:
            return
        try:
            with self.conn:
                self.conn.execute("DELETE FROM memories")
                for key, memory in self.memories.items():
                    tags_str = ",".join(memory.tags) if memory.tags else ""
                    emb_str = json.dumps(memory.embedding) if memory.embedding else "[]"
                    self.conn.execute("""
                        INSERT INTO memories (key, value, tags, created, updated, access_count, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        memory.key,
                        memory.value,
                        tags_str,
                        memory.created,
                        memory.updated,
                        memory.access_count,
                        emb_str
                    ))
        except Exception as e:
            Console.warn(f"Failed to sync memories to SQLite: {e}")

    def remember(self, key: str, value: str, tags: List[str] = None) -> Memory:
        """Store a memory in SQLite and update local cache."""
        now = datetime.utcnow().isoformat() + 'Z'

        # Generate embedding for semantic search
        combined = f"{key} {value}"
        embedding = embed_text(combined) or []

        existing = self.get_by_key(key)
        if existing:
            memory = existing
            memory.value = value
            memory.updated = now
            memory.tags = tags or memory.tags
            memory.embedding = embedding
        else:
            memory = Memory(
                key=key,
                value=value,
                tags=tags or [],
                created=now,
                updated=now,
                embedding=embedding
            )

        self.memories[key] = memory

        if self.conn:
            try:
                tags_str = ",".join(memory.tags) if memory.tags else ""
                emb_str = json.dumps(memory.embedding) if memory.embedding else "[]"
                with self.conn:
                    self.conn.execute("""
                        INSERT OR REPLACE INTO memories (key, value, tags, created, updated, access_count, embedding)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        memory.key,
                        memory.value,
                        tags_str,
                        memory.created,
                        memory.updated,
                        memory.access_count,
                        emb_str
                    ))
            except Exception as e:
                Console.warn(f"Failed to write memory to SQLite: {e}")
        return memory

    def recall(self, query: str, limit: int = 10) -> List[Memory]:
        """Search memories semantically (queries fresh SQLite state)."""
        self.load()
        if not self.memories:
            return []

        # Generate query embedding
        query_emb = embed_text(query)

        results = []
        for key, memory in self.memories.items():
            # Update access count
            memory.access_count += 1

            score = 0.0

            # Exact key match
            if query.lower() in key.lower():
                score += 1.0

            # Value match
            if query.lower() in memory.value.lower():
                score += 0.5

            # Tag match
            for tag in memory.tags:
                if query.lower() in tag.lower():
                    score += 0.3

            # Semantic similarity
            if query_emb and memory.embedding:
                semantic_score = cosine_similarity(query_emb, memory.embedding)
                score += semantic_score * 0.5

            if score > 0:
                results.append((memory, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        self.save()  # Save access counts
        return [r[0] for r in results[:limit]]

    def forget(self, key: str) -> bool:
        """Remove a memory from SQLite and local cache."""
        rows_affected = 0
        if self.conn:
            try:
                with self.conn:
                    cursor = self.conn.execute("DELETE FROM memories WHERE key = ?", (key,))
                    rows_affected = cursor.rowcount
            except Exception as e:
                Console.warn(f"Failed to delete memory from SQLite: {e}")

        if key in self.memories:
            del self.memories[key]
            return True
        return rows_affected > 0

    def list_all(self, tag: str = None) -> List[Memory]:
        """List all memories, optionally filtered by tag."""
        self.load()
        if tag:
            return [m for m in self.memories.values() if tag in m.tags]
        return list(self.memories.values())

    def get_by_key(self, key: str) -> Optional[Memory]:
        """Get memory by exact key."""
        if self.conn:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT key, value, tags, created, updated, access_count, embedding FROM memories WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    tags = row[2].split(",") if row[2] else []
                    embedding = json.loads(row[6]) if row[6] else []
                    return Memory(
                        key=row[0],
                        value=row[1],
                        tags=tags,
                        created=row[3],
                        updated=row[4],
                        access_count=row[5],
                        embedding=embedding
                    )
            except Exception as e:
                Console.warn(f"Failed to get memory by key from SQLite: {e}")
        return self.memories.get(key)

    def export_all(self) -> str:
        """Export all memories as JSON."""
        self.load()
        return json.dumps({k: v.to_dict() for k, v in self.memories.items()}, indent=2)

    def import_memories(self, json_str: str) -> int:
        """Import memories from JSON."""
        try:
            data = json.loads(json_str)
            count = 0
            for key, mem_data in data.items():
                if key not in self.memories:
                    self.memories[key] = Memory.from_dict(mem_data)
                    count += 1
            self.save()
            return count
        except Exception:
            return 0

    def record_agent_action(self, tool_name: str, args: str, status: str, summary: str) -> int:
        """Record an agent action in the activity ledger with embedding."""
        now = datetime.utcnow().isoformat() + 'Z'
        combined = f"{tool_name} {args} {summary}"
        embedding = embed_text(combined) or []
        emb_str = json.dumps(embedding)
        
        if self.conn:
            try:
                with self.conn:
                    cursor = self.conn.execute("""
                        INSERT INTO activity_ledger (timestamp, tool_name, arguments, result_status, summary, embedding)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (now, tool_name, args, status, summary, emb_str))
                    return cursor.lastrowid
            except Exception as e:
                Console.warn(f"Failed to record action in activity ledger: {e}")
        return 0

    def search_activity_stream(self, query: str, limit: int = 20) -> List[dict]:
        """Search past actions semantically using embeddings and keyword matching."""
        if not self.conn:
            return []
        
        try:
            query_emb = embed_text(query)
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, timestamp, tool_name, arguments, result_status, summary, embedding FROM activity_ledger")
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                row_id, timestamp, tool_name, arguments, result_status, summary, emb_json = row
                embedding = json.loads(emb_json) if emb_json else []
                
                score = 0.0
                
                # Keyword matches
                q_low = query.lower()
                if q_low in tool_name.lower():
                    score += 1.0
                if arguments and q_low in arguments.lower():
                    score += 0.5
                if summary and q_low in summary.lower():
                    score += 0.5
                    
                # Semantic match
                if query_emb and embedding:
                    semantic_score = cosine_similarity(query_emb, embedding)
                    score += semantic_score * 0.5
                    
                if score > 0:
                    results.append(({
                        "id": row_id,
                        "timestamp": timestamp,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "result_status": result_status,
                        "summary": summary
                    }, score))
                    
            # Sort by score descending
            results.sort(key=lambda x: x[1], reverse=True)
            return [r[0] for r in results[:limit]]
        except Exception as e:
            Console.warn(f"Failed to search activity stream: {e}")
            return []

    def __del__(self):
        if hasattr(self, 'conn') and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass



# Global store instance
_store: Optional[MemoryStore] = None


def get_store() -> MemoryStore:
    """Get or create memory store."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def remember(key: str, value: str, tags: List[str] = None) -> Memory:
    """Store a memory."""
    return get_store().remember(key, value, tags)


def recall(query: str, limit: int = 10) -> List[Memory]:
    """Search memories."""
    return get_store().recall(query, limit)


def forget(key: str) -> bool:
    """Forget a memory."""
    return get_store().forget(key)


def record_agent_action(tool_name: str, args: str, status: str, summary: str) -> int:
    """Record an agent action."""
    return get_store().record_agent_action(tool_name, args, status, summary)


def search_activity_stream(query: str, limit: int = 20) -> List[dict]:
    """Search past actions."""
    return get_store().search_activity_stream(query, limit)


def main():
    """CLI entry point."""
    Console.header("Persistent Memory")

    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    store = get_store()

    Console.info(f"Memory storage: {store.storage_path}")
    Console.info(f"Total memories: {len(store.memories)}")

    if len(args) >= 2:
        key = args[0]
        value = args[1]
        tags = args[2:] if len(args) > 2 else []

        memory = store.remember(key, value, tags)
        Console.ok(f"Remembered: {key}")
        print(f"  Value: {value}")
        if tags:
            print(f"  Tags: {', '.join(tags)}")
        return 0

    if len(args) == 1:
        query = args[0]

        if '--forget' in sys.argv or '--delete' in sys.argv:
            if store.forget(query):
                Console.ok(f"Forgot: {query}")
            else:
                Console.warn(f"Not found: {query}")
            return 0

        # Search
        Console.info(f"Recalling: {query}")
        results = store.recall(query)

        if results:
            for mem in results:
                print(f"\n  [{mem.key}]")
                print(f"  {mem.value}")
                if mem.tags:
                    print(f"  Tags: {', '.join(mem.tags)}")
        else:
            Console.warn("No matching memories")
        return 0

    # List all
    if '--list' in sys.argv or not args:
        memories = store.list_all()
        Console.info(f"All memories ({len(memories)}):")
        for mem in memories[:20]:
            print(f"  [{mem.key}] {mem.value[:50]}...")

    if '--export' in sys.argv:
        print(store.export_all())

    return 0


if __name__ == "__main__":
    sys.exit(main())
