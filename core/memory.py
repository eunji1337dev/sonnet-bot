from __future__ import annotations

import os
from datetime import datetime
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.utils import embedding_functions
import structlog

log = structlog.get_logger(__name__)


class MemoryManager:
    """Enterprise RAG and Semantic Memory Manager 2026."""
    
    def __init__(self) -> None:
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")
        os.makedirs(self.db_path, exist_ok=True)
        
        # Initialize Persistent Client
        self._client = chromadb.PersistentClient(path=self.db_path)
        
        # Elite local embedding model for lightning speed 
        # (Default is all-MiniLM-L6-v2 which is great for fast text embeddings)
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        
        # Chat history collection
        self._history = self._client.get_or_create_collection(
            name="chat_history", 
            embedding_function=self._ef
        )
        
        # Knowledge base collection for static RAG (optional usage)
        self._knowledge = self._client.get_or_create_collection(
            name="knowledge_base", 
            embedding_function=self._ef
        )
        
        log.info("MemoryManager initialized with ChromaDB", path=self.db_path)

    async def add_chat_message(self, user_id: int, text: str, role: str = "user") -> None:
        """Silently logs meaningful context to long-term vector memory."""
        if not text or len(text.strip()) < 5:
            return  # Skip extremely short messages like "ok" to save vector space
            
        timestamp = datetime.now().timestamp()
        doc_id = f"msg_{user_id}_{timestamp}"
        
        try:
            self._history.add(
                documents=[text],
                metadatas=[{"user_id": user_id, "role": role, "timestamp": datetime.now().isoformat()}],
                ids=[doc_id]
            )
        except Exception as e:
            log.error("Failed to add message to vector memory", error=str(e), user_id=user_id)

    async def semantic_search(self, user_id: int, query: str, n_results: int = 5) -> str:
        """Retrieves dense context based on cosine similarity."""
        try:
            results = self._history.query(
                query_texts=[query],
                n_results=n_results,
                where={"user_id": user_id}
            )
            
            if not results.get('documents') or not results['documents'][0]:
                return ""
            
            context = []
            docs = results['documents'][0]
            metadatas = results['metadatas'][0]
            
            for doc, meta in zip(docs, metadatas):
                role_str = str(meta.get('role', 'unknown')).upper()
                time_str = str(meta.get('timestamp', ''))[:16]
                context.append(f"[{time_str}] {role_str}: {doc}")
            
            return "\n".join(context)
            
        except Exception as e:
            log.error("Failed to perform semantic search", error=str(e), user_id=user_id)
            return ""
