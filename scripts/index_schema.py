"""Extract database schema and index into ChromaDB vector store."""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from querypilot.config import settings
from querypilot.db.schema_extractor import SchemaExtractor
from querypilot.rag.schema_documents import build_all_schema_documents
from querypilot.rag.vector_store import SchemaVectorStore


def index_schema(force: bool = False) -> None:
    """Index or re-index the SQLite database schema into ChromaDB."""
    db_path = settings.db_path
    print(f"Connecting to database at {db_path}...")
    extractor = SchemaExtractor(db_path=db_path)
    schema = extractor.extract()
    print(f"Extracted {len(schema.tables)} tables. Schema hash: {schema.schema_hash[:16]}...")

    vector_store = SchemaVectorStore()
    if not force and vector_store.is_index_current(schema.schema_hash):
        print("Vector index is already up-to-date with current database schema.")
        return

    print("Building annotated schema documents...")
    documents = build_all_schema_documents(schema)
    print(f"Indexing {len(documents)} documents into ChromaDB collection...")
    vector_store.index_documents(documents, schema_hash=schema.schema_hash)
    print("Schema indexing completed successfully!")

    # Verify retrieval
    test_query = "monthly revenue trend"
    sample_results = vector_store.query(test_query, n_results=3)
    print(f"\nVerification query: '{test_query}'")
    print(f"Top retrieved tables: {[r['table_name'] for r in sample_results]}")


if __name__ == "__main__":
    force_reindex = "--force" in sys.argv
    index_schema(force=force_reindex)
