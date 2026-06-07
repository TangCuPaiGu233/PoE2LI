"""Embedding service for generating text embeddings.

Primary: BAAI/bge-m3 via OpenAI-compatible API (SiliconFlow free tier recommended).
Fallback: sentence-transformers local model (optional, for GPU machines).

Configuration via environment variables:
    EMBEDDING_PROVIDER    — "api" (default) or "local"
    EMBEDDING_BASE_URL    — API base URL (default: SiliconFlow https://api.siliconflow.cn/v1)
    EMBEDDING_API_KEY     — API key (get free key at https://cloud.siliconflow.cn)
    EMBEDDING_API_MODEL   — Model name (default: BAAI/bge-m3)
    EMBEDDING_DIM         — Embedding dimension (default: 1024, must match DB schema)
    EMBEDDING_MODEL       — HuggingFace model name for local fallback (default: BAAI/bge-m3)
"""

import os
import logging

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "api").lower()
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# API settings (primary)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", os.getenv("ANTHROPIC_AUTH_TOKEN", ""))
EMBEDDING_API_MODEL = os.getenv("EMBEDDING_API_MODEL", "BAAI/bge-m3")

# Local fallback settings (optional)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

# ── Internal state ─────────────────────────────────────────────

_local_model = None
_api_client = None


# ── Public API ─────────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for the given text.

    Strategy:
      - provider="local" (default): try local BGE-M3 first, fall back to API
      - provider="api": try API first, fall back to local

    Returns a list of floats with dimension EMBEDDING_DIM, or None on failure.
    """
    if not text or not text.strip():
        return None

    if EMBEDDING_PROVIDER == "api":
        # API first, local fallback
        result = _get_api_embedding(text)
        if result is not None:
            return result
        return _get_local_embedding(text)
    else:
        # Local first (default), API fallback
        result = _get_local_embedding(text)
        if result is not None:
            return result
        return _get_api_embedding(text)


# ── Local: sentence-transformers ───────────────────────────────

def _get_local_embedding(text: str) -> list[float] | None:
    """Generate embedding using a local BGE-M3 model via sentence-transformers.

    The model is downloaded on first use (~2.2 GB) and cached locally.
    Outputs 1024-dimensional normalized embeddings.
    """
    global _local_model
    try:
        if _local_model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading local embedding model: {EMBEDDING_MODEL} ...")
            _local_model = SentenceTransformer(EMBEDDING_MODEL)
            actual_dim = _local_model.get_sentence_embedding_dimension()
            logger.info(f"Local embedding model loaded successfully (dim={actual_dim})")
            if actual_dim != EMBEDDING_DIM:
                logger.warning(
                    f"Embedding dim mismatch: model outputs {actual_dim}, "
                    f"DB expects {EMBEDDING_DIM}. Consider setting EMBEDDING_DIM={actual_dim}."
                )

        embedding = _local_model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

    except ImportError:
        logger.warning(
            "sentence-transformers not installed. Local embedding unavailable. "
            "Install with: pip install sentence-transformers torch"
        )
        return None
    except Exception as e:
        logger.warning(f"Local embedding failed: {e}")
        return None


# ── API: OpenAI-compatible ─────────────────────────────────────

def _get_api_embedding(text: str) -> list[float] | None:
    """Generate embedding using an OpenAI-compatible API endpoint."""
    global _api_client
    try:
        if _api_client is None:
            if not EMBEDDING_API_KEY:
                return None
            from openai import OpenAI
            _api_client = OpenAI(
                base_url=EMBEDDING_BASE_URL,
                api_key=EMBEDDING_API_KEY,
            )

        response = _api_client.embeddings.create(
            input=text,
            model=EMBEDDING_API_MODEL,
        )
        embedding = response.data[0].embedding

        if len(embedding) != EMBEDDING_DIM:
            logger.warning(
                f"Embedding dim mismatch: API returned {len(embedding)}, expected {EMBEDDING_DIM}"
            )
        return embedding

    except ImportError:
        logger.warning("openai package not installed. API embedding unavailable.")
        return None
    except Exception as e:
        logger.warning(f"API embedding failed: {e}")
        return None
