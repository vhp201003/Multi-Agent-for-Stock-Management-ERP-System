import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from qdrant_client.http import models

from src.communication import get_qdrant_connection
from src.communication.embedding import DEFAULT_DIMENSION, get_embedding_model
from src.typing.redis.conversation import Message

logger = logging.getLogger(__name__)

COLLECTION_NAME = "semantic_cache"
SIMILARITY_THRESHOLD = 0.90  # Độ giống nhau 90% mới coi là Cache Hit

# Conversation indexing constants
CONVERSATION_COLLECTION_NAME = "conversation_messages"
CONVERSATION_SEARCH_THRESHOLD = 0.75  # In-conversation search
CROSS_CONVERSATION_THRESHOLD = 0.70  # Cross-conversation search


class SemanticCacheService:
    def __init__(self):
        self.qdrant = get_qdrant_connection().client
        self.embedder = get_embedding_model()
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            collections = self.qdrant.get_collections()
            exists = any(c.name == COLLECTION_NAME for c in collections.collections)
            if not exists:
                self.qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=DEFAULT_DIMENSION,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {COLLECTION_NAME}")
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collection: {e}")

    async def search_cache(self, query_text: str) -> Optional[Dict[str, Any]]:
        """Tìm kiếm câu trả lời đã cache"""
        try:
            # 1. Vector hóa câu hỏi
            vector = self.embedder.embed_query(query_text)

            # 2. Tìm kiếm trong Qdrant
            search_result = self.qdrant.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                limit=1,
                with_payload=True,
            )

            # 3. Kiểm tra độ tương đồng
            if search_result and search_result[0].score >= SIMILARITY_THRESHOLD:
                payload = search_result[0].payload
                logger.info(
                    f"✅ Cache HIT for query: '{query_text}' (Score: {search_result[0].score:.4f})"
                )
                return payload.get("response_data")

            logger.info(f"❌ Cache MISS for query: '{query_text}'")
            return None

        except Exception as e:
            logger.error(f"Cache lookup failed: {e}")
            return None

    async def save_to_cache(
        self,
        query_text: str,
        response_data: Dict[str, Any],
        conversation_id: Optional[str] = None,
        query_id: Optional[str] = None,
    ):
        """Lưu kết quả mới vào cache với conversation context"""
        try:
            vector = self.embedder.embed_query(query_text)

            payload = {
                "original_query": query_text,
                "response_data": response_data,
                "timestamp": datetime.now().isoformat(),
            }

            # Add conversation context if available
            if conversation_id:
                payload["conversation_id"] = conversation_id
            if query_id:
                payload["query_id"] = query_id

            self.qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            logger.info(f"💾 Saved query to cache: '{query_text}'")
        except Exception as e:
            logger.error(f"Failed to save to cache: {e}")


# Singleton instance
semantic_cache = SemanticCacheService()


class ConversationIndexService:
    """
    Service for indexing and searching conversation messages.
    Indexes assistant responses with rich metadata for semantic search.
    """

    def __init__(self):
        self.qdrant = get_qdrant_connection().client
        self.embedder = get_embedding_model()
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection with payload indexes for filtering."""
        try:
            collections = self.qdrant.get_collections()
            exists = any(
                c.name == CONVERSATION_COLLECTION_NAME for c in collections.collections
            )

            if not exists:
                # Create collection
                self.qdrant.create_collection(
                    collection_name=CONVERSATION_COLLECTION_NAME,
                    vectors_config=models.VectorParams(
                        size=DEFAULT_DIMENSION,
                        distance=models.Distance.COSINE,
                    ),
                )

                # Create payload indexes for efficient filtering
                self.qdrant.create_payload_index(
                    collection_name=CONVERSATION_COLLECTION_NAME,
                    field_name="conversation_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

                self.qdrant.create_payload_index(
                    collection_name=CONVERSATION_COLLECTION_NAME,
                    field_name="user_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

                self.qdrant.create_payload_index(
                    collection_name=CONVERSATION_COLLECTION_NAME,
                    field_name="agent_type",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

                self.qdrant.create_payload_index(
                    collection_name=CONVERSATION_COLLECTION_NAME,
                    field_name="timestamp",
                    field_schema=models.PayloadSchemaType.DATETIME,
                )

                logger.info(f"✓ Created Qdrant collection: {CONVERSATION_COLLECTION_NAME}")
        except Exception as e:
            logger.error(f"✗ Failed to ensure Qdrant collection: {e}")

    def _build_searchable_text(self, message: Message) -> str:
        """
        Build comprehensive searchable text from message content and metadata.
        Combines multiple sources for better semantic search.
        """
        parts = []

        # 1. Original content (highest priority)
        if message.content:
            parts.append(message.content)

        # Extract from metadata if available
        if message.metadata:
            # 2. Layout markdown content
            if layout := message.metadata.get("layout"):
                for field in layout:
                    if isinstance(field, dict):
                        field_type = field.get("field_type")

                        # Extract markdown content
                        if field_type == "markdown":
                            if content := field.get("content"):
                                parts.append(content)

                        # Extract graph/table titles and descriptions
                        elif field_type in ["graph", "table"]:
                            if title := field.get("title"):
                                parts.append(title)
                            if desc := field.get("description"):
                                parts.append(desc)

            # 3. Tool result summaries from full_data
            if full_data := message.metadata.get("full_data"):
                for agent_type, tools_data in full_data.items():
                    if isinstance(tools_data, dict):
                        parts.append(f"Agent: {agent_type}")

                        for tool_name, tool_result in tools_data.items():
                            parts.append(f"Tool: {tool_name}")

                            # Extract key text fields from tool results
                            if isinstance(tool_result, dict):
                                for key in ["summary", "description", "result", "message"]:
                                    if val := tool_result.get(key):
                                        parts.append(str(val))

            # 4. Query ID context (for cross-referencing)
            if query_id := message.metadata.get("query_id"):
                parts.append(f"Query: {query_id}")

        return "\n".join(filter(None, parts))

    def _extract_message_metadata(self, message: Message) -> Dict[str, Any]:
        """Extract structured metadata for filtering and search."""
        metadata = message.metadata or {}

        # Initialize extraction results
        layout_types = []
        graph_types = []
        has_graphs = False
        has_tables = False
        tools_used = []
        agents_involved = []

        # Extract layout information
        if layout := metadata.get("layout"):
            for field in layout:
                if isinstance(field, dict):
                    field_type = field.get("field_type")
                    if field_type:
                        layout_types.append(field_type)

                        if field_type == "graph":
                            has_graphs = True
                            if graph_type := field.get("graph_type"):
                                graph_types.append(graph_type)
                        elif field_type == "table":
                            has_tables = True

        # Extract tool usage information
        if full_data := metadata.get("full_data"):
            if isinstance(full_data, dict):
                agents_involved = list(full_data.keys())

                for tools_data in full_data.values():
                    if isinstance(tools_data, dict):
                        tools_used.extend(tools_data.keys())

        return {
            "layout_types": list(set(layout_types)),
            "has_graphs": has_graphs,
            "has_tables": has_tables,
            "graph_types": list(set(graph_types)),
            "tools_used": list(set(tools_used)),
            "agents_involved": agents_involved,
        }

    async def index_message(
        self,
        message: Message,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Index a single message to Qdrant.
        Only indexes assistant messages.
        """
        try:
            # Only index assistant messages
            if message.role != "assistant":
                logger.debug(f"Skipping non-assistant message (role={message.role})")
                return False

            # Build searchable text
            searchable_text = self._build_searchable_text(message)

            if not searchable_text.strip():
                logger.warning("Empty searchable text, skipping indexing")
                return False

            # Extract metadata
            extracted_meta = self._extract_message_metadata(message)

            # Generate embedding
            vector = self.embedder.embed(searchable_text)

            # Create payload
            payload = {
                "message_id": str(uuid.uuid4()),
                "conversation_id": conversation_id,
                "user_id": user_id,
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp.isoformat(),
                "agent_type": message.metadata.get("agent_type") if message.metadata else None,
                "searchable_text": searchable_text,
                "full_metadata": message.metadata,
                **extracted_meta,
            }

            # Upsert to Qdrant
            self.qdrant.upsert(
                collection_name=CONVERSATION_COLLECTION_NAME,
                points=[
                    models.PointStruct(
                        id=payload["message_id"],
                        vector=vector,
                        payload=payload,
                    )
                ],
            )

            logger.info(
                f"✓ Indexed message in conversation {conversation_id} "
                f"(agent={payload['agent_type']}, tools={len(extracted_meta['tools_used'])})"
            )
            return True

        except Exception as e:
            logger.error(f"✗ Failed to index message: {e}")
            return False

    async def search_messages(
        self,
        query_text: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        has_graphs: Optional[bool] = None,
        has_tables: Optional[bool] = None,
        limit: int = 10,
        score_threshold: float = CONVERSATION_SEARCH_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: semantic + metadata filters.

        Args:
            query_text: Text to search for
            conversation_id: Filter by specific conversation
            user_id: Filter by user
            agent_type: Filter by agent type
            has_graphs: Filter messages with graphs
            has_tables: Filter messages with tables
            limit: Max results to return
            score_threshold: Minimum similarity score

        Returns:
            List of matching messages with scores
        """
        try:
            # Generate query vector
            query_vector = self.embedder.embed_query(query_text)

            # Build filters
            must_conditions = []

            if conversation_id:
                must_conditions.append(
                    models.FieldCondition(
                        key="conversation_id",
                        match=models.MatchValue(value=conversation_id),
                    )
                )

            if user_id:
                must_conditions.append(
                    models.FieldCondition(
                        key="user_id",
                        match=models.MatchValue(value=user_id),
                    )
                )

            if agent_type:
                must_conditions.append(
                    models.FieldCondition(
                        key="agent_type",
                        match=models.MatchValue(value=agent_type),
                    )
                )

            if has_graphs is not None:
                must_conditions.append(
                    models.FieldCondition(
                        key="has_graphs",
                        match=models.MatchValue(value=has_graphs),
                    )
                )

            if has_tables is not None:
                must_conditions.append(
                    models.FieldCondition(
                        key="has_tables",
                        match=models.MatchValue(value=has_tables),
                    )
                )

            query_filter = None
            if must_conditions:
                query_filter = models.Filter(must=must_conditions)

            # Search
            search_result = self.qdrant.search(
                collection_name=CONVERSATION_COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                score_threshold=score_threshold,
            )

            results = []
            for hit in search_result:
                results.append({
                    "score": hit.score,
                    "message": hit.payload,
                })

            logger.info(
                f"✓ Found {len(results)} messages for query: '{query_text[:50]}...' "
                f"(conversation_id={conversation_id}, filters={len(must_conditions)})"
            )
            return results

        except Exception as e:
            logger.error(f"✗ Search failed: {e}")
            return []

    async def delete_conversation_messages(self, conversation_id: str) -> bool:
        """Delete all messages from a conversation."""
        try:
            self.qdrant.delete(
                collection_name=CONVERSATION_COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="conversation_id",
                                match=models.MatchValue(value=conversation_id),
                            )
                        ]
                    )
                ),
            )
            logger.info(f"✓ Deleted messages for conversation {conversation_id}")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to delete messages for conversation {conversation_id}: {e}")
            return False


# Singleton instances
conversation_index = ConversationIndexService()
