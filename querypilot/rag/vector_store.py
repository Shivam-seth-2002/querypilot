"""Persistent vector store wrapper for schema indexing and retrieval using ChromaDB."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import chromadb

from querypilot.config import settings
from querypilot.rag.schema_documents import SchemaDocument

COLLECTION_NAME = "schema_docs"
HASH_METADATA_FILE = "schema_hash.json"


class SchemaVectorStore:
    """Manages ChromaDB persistent collection and schema hash tracking."""

    def __init__(self, chroma_path: Optional[str] = None):
        self.chroma_path = Path(chroma_path or settings.chroma_path).resolve()
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.chroma_path))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "QueryPilot Schema Documents"},
        )

    def get_stored_hash(self) -> Optional[str]:
        """Read currently indexed schema hash from persistent store."""
        hash_file = self.chroma_path / HASH_METADATA_FILE
        if hash_file.exists():
            try:
                data = json.loads(hash_file.read_text(encoding="utf-8"))
                return data.get("schema_hash")
            except Exception:
                return None
        return None

    def save_stored_hash(self, schema_hash: str) -> None:
        """Save indexed schema hash to track database schema versions."""
        hash_file = self.chroma_path / HASH_METADATA_FILE
        hash_file.write_text(
            json.dumps({"schema_hash": schema_hash}, indent=2),
            encoding="utf-8",
        )

    def is_index_current(self, current_schema_hash: str) -> bool:
        """Check if vector index matches current database schema."""
        stored = self.get_stored_hash()
        return stored is not None and stored == current_schema_hash

    def index_documents(
        self, documents: List[SchemaDocument], schema_hash: Optional[str] = None
    ) -> None:
        """Idempotently upsert schema documents into ChromaDB collection."""
        if not documents:
            return

        ids = [doc.doc_id for doc in documents]
        contents = [doc.content for doc in documents]
        metadatas = [
            {
                "table_name": doc.table_name,
                "doc_type": "table",
                "columns": ",".join(doc.columns),
            }
            for doc in documents
        ]

        self.collection.upsert(
            ids=ids,
            documents=contents,
            metadatas=metadatas,
        )

        if schema_hash:
            self.save_stored_hash(schema_hash)

    def query(
        self, query_text: str, n_results: int = 4
    ) -> List[Dict[str, Any]]:
        """Query vector store for relevant schema documents."""
        count = self.collection.count()
        if count == 0:
            return []

        k = min(n_results, count)
        results = self.collection.query(
            query_texts=[query_text],
            n_results=k,
        )

        retrieved: List[Dict[str, Any]] = []
        if not results or not results["ids"] or not results["ids"][0]:
            return retrieved

        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else [0.0] * len(ids)
        documents = results.get("documents", [[]])[0] if results.get("documents") else [""] * len(ids)
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{}] * len(ids)

        for doc_id, dist, doc_text, meta in zip(ids, distances, documents, metadatas):
            tbl = meta.get("table_name", doc_id.replace("table::", ""))
            retrieved.append({
                "table_name": tbl,
                "distance": dist,
                "content": doc_text,
                "columns": meta.get("columns", "").split(","),
            })

        return retrieved
