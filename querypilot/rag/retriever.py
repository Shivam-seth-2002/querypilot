"""Schema retriever combining vector similarity, keyword fallbacks, and FK graph expansion."""

import logging
import re
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, Field

from querypilot.config import settings
from querypilot.db.schema_extractor import DatabaseSchema, SchemaExtractor
from querypilot.rag.schema_documents import (
    TABLE_ANNOTATIONS,
    build_all_schema_documents,
)
from querypilot.rag.vector_store import SchemaVectorStore

logger = logging.getLogger(__name__)

# Foreign key adjacency graph (undirected) connecting tables in the retail schema
FK_GRAPH: Dict[str, Set[str]] = {
    "customers": {"orders"},
    "orders": {"customers", "order_items", "returns"},
    "order_items": {"orders", "products"},
    "products": {"order_items", "returns", "inventory"},
    "returns": {"orders", "products"},
    "inventory": {"products", "warehouses"},
    "warehouses": {"inventory"},
    "marketing_campaigns": set(),
    "employees": set(),
}

# Domain keyword to table mapping for deterministic keyword fallback
KEYWORD_MAPPINGS: Dict[str, List[str]] = {
    "revenue": ["order_items", "orders"],
    "sales": ["order_items", "orders"],
    "spend": ["order_items", "customers", "orders"],
    "spending": ["order_items", "customers", "orders"],
    "order": ["orders"],
    "orders": ["orders"],
    "customer": ["customers"],
    "customers": ["customers"],
    "product": ["products"],
    "products": ["products"],
    "category": ["products"],
    "categories": ["products"],
    "brand": ["products"],
    "return": ["returns", "orders"],
    "returns": ["returns", "orders"],
    "refund": ["returns"],
    "stock": ["inventory", "warehouses"],
    "inventory": ["inventory", "warehouses"],
    "warehouse": ["warehouses"],
    "campaign": ["marketing_campaigns"],
    "marketing": ["marketing_campaigns"],
    "employee": ["employees"],
    "employees": ["employees"],
    "staff": ["employees"],
    "maharashtra": ["customers"],
    "karnataka": ["customers"],
    "delhi": ["customers"],
    "monthly": ["orders"],
    "trend": ["orders"],
    "2024": ["orders"],
    "2023": ["orders"],
    "2025": ["orders"],
}


class RetrievedSchema(BaseModel):
    """Result of schema retrieval containing selected tables and formatted context."""
    tables: List[str]
    context_text: str
    vector_tables: List[str] = Field(default_factory=list)
    keyword_tables: List[str] = Field(default_factory=list)
    fk_expanded_tables: List[str] = Field(default_factory=list)


class SchemaRetriever:
    """Retrieves relevant schema context using Vector Search + Keyword Fallback + FK Graph Expansion."""

    def __init__(
        self,
        vector_store: Optional[SchemaVectorStore] = None,
        schema: Optional[DatabaseSchema] = None,
        top_k: Optional[int] = None,
    ):
        self.vector_store = vector_store or SchemaVectorStore()
        self.top_k = top_k or settings.top_k_tables

        # Ensure schema is extracted and indexed
        if schema is None:
            extractor = SchemaExtractor()
            self.schema = extractor.extract()
        else:
            self.schema = schema

        self._ensure_index()
        self.schema_docs = {
            doc.table_name: doc.content for doc in build_all_schema_documents(self.schema)
        }

    def _ensure_index(self) -> None:
        """Check if vector store needs indexing or updating."""
        if not self.vector_store.is_index_current(self.schema.schema_hash):
            docs = build_all_schema_documents(self.schema)
            self.vector_store.index_documents(docs, schema_hash=self.schema.schema_hash)

    def _keyword_fallback(self, question: str) -> Set[str]:
        """Detect tables from keywords, synonyms, and literal table names in question."""
        matched_tables: Set[str] = set()
        clean_q = question.lower()
        tokens = set(re.findall(r"\b\w+\b", clean_q))

        # 1. Direct table name match
        for table_name in self.schema.tables.keys():
            if table_name in tokens or table_name in clean_q:
                matched_tables.add(table_name)

        # 2. Domain keyword match
        for kw, tbls in KEYWORD_MAPPINGS.items():
            if kw in tokens or kw in clean_q:
                for t in tbls:
                    if t in self.schema.tables:
                        matched_tables.add(t)

        return matched_tables

    def _expand_foreign_keys(self, current_tables: Set[str]) -> Set[str]:
        """Find intermediate bridging tables needed to join retrieved tables (max 1 hop BFS)."""
        expanded: Set[str] = set()
        table_list = list(current_tables)

        for i in range(len(table_list)):
            for j in range(i + 1, len(table_list)):
                t1, t2 = table_list[i], table_list[j]
                # If they already have a direct FK link, no bridge needed
                if t2 in FK_GRAPH.get(t1, set()):
                    continue

                # 1-hop BFS: search for any table connected to BOTH t1 and t2
                t1_neighbors = FK_GRAPH.get(t1, set())
                t2_neighbors = FK_GRAPH.get(t2, set())
                common = t1_neighbors.intersection(t2_neighbors)
                for bridge in common:
                    if bridge in self.schema.tables and bridge not in current_tables:
                        expanded.add(bridge)

        return expanded

    def retrieve(self, question: str) -> RetrievedSchema:
        """Execute full schema retrieval pipeline for a natural language question."""
        # 1. Vector similarity search
        vector_results = self.vector_store.query(question, n_results=self.top_k)
        vector_tables = [r["table_name"] for r in vector_results if r["table_name"] in self.schema.tables]

        # 2. Keyword fallback
        keyword_tables = list(self._keyword_fallback(question))

        # Combine vector + keyword tables
        active_tables = set(vector_tables).union(keyword_tables)

        # 3. Foreign Key Graph Expansion
        fk_expanded = self._expand_foreign_keys(active_tables)
        final_tables_set = active_tables.union(fk_expanded)

        # Ensure order is deterministic and preserves relevance
        final_tables = [t for t in vector_tables if t in final_tables_set]
        for t in keyword_tables:
            if t not in final_tables:
                final_tables.append(t)
        for t in fk_expanded:
            if t not in final_tables:
                final_tables.append(t)

        # Format context text for prompt
        context_blocks = []
        for tbl in final_tables:
            doc_content = self.schema_docs.get(tbl, f"TABLE: {tbl}")
            context_blocks.append(doc_content)

        context_text = "\n\n" + ("=" * 50) + "\n\n".join(context_blocks)

        logger.info(
            f"Schema retrieval for '{question}': "
            f"Vector={vector_tables}, Keywords={keyword_tables}, FK_Expanded={list(fk_expanded)} -> Total={final_tables}"
        )

        return RetrievedSchema(
            tables=final_tables,
            context_text=context_text,
            vector_tables=vector_tables,
            keyword_tables=keyword_tables,
            fk_expanded_tables=list(fk_expanded),
        )
