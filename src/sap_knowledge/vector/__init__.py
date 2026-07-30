"""Provider-neutral vector embedding and retrieval contracts."""

from sap_knowledge.vector.embeddings import TextEmbedder
from sap_knowledge.vector.models import SearchHit
from sap_knowledge.vector.rag import build_rag_prompt

__all__ = ["SearchHit", "TextEmbedder", "build_rag_prompt"]
