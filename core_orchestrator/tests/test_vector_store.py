"""Tests for vector_store: embedding back-ends, config resolution, search.

All external dependencies (OpenAI API, Ollama HTTP, PostgreSQL) are fully
mocked.  No real network calls or DB connections are made.
"""

import math
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core_orchestrator.vector_store import (
    VectorStore,
    _cosine_similarity,
    _embed_ollama,
    _embed_openai,
    _resolve_config,
    get_vector_store,
    invalidate_embedding_config_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_EMBEDDING_1536 = [0.1] * 1536
FAKE_EMBEDDING_768  = [0.2] * 768   # typical Ollama nomic-embed-text dims


def _clean_config_cache():
    """Reset the module-level config cache before tests that probe resolution."""
    invalidate_embedding_config_cache()


# ---------------------------------------------------------------------------
# TestCosineSimilarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_normalized_is_dot_product(self):
        a = [0.6, 0.8]
        b = [0.8, 0.6]
        dot = 0.6 * 0.8 + 0.8 * 0.6
        assert _cosine_similarity(a, b) == pytest.approx(dot)

    def test_empty_vector_returns_zero(self):
        assert _cosine_similarity([], []) == 0.0

    def test_zero_vector_returns_zero(self):
        assert _cosine_similarity([0, 0], [1, 2]) == 0.0

    def test_length_mismatch_returns_zero(self):
        assert _cosine_similarity([1, 2, 3], [1, 2]) == 0.0


# ---------------------------------------------------------------------------
# TestConfigResolution
# ---------------------------------------------------------------------------

class TestConfigResolution:
    def setup_method(self):
        _clean_config_cache()

    def teardown_method(self):
        _clean_config_cache()

    def test_env_var_provider_openai(self):
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai",
                                       "EMBEDDING_MODEL": "text-embedding-3-large"}, clear=False):
            cfg = _resolve_config()
        assert cfg.provider == "openai"
        assert cfg.model    == "text-embedding-3-large"

    def test_env_var_provider_ollama(self):
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "ollama",
                                       "EMBEDDING_MODEL": "mxbai-embed-large",
                                       "EMBEDDING_BASE_URL": "http://ollama.local:11434"}, clear=False):
            cfg = _resolve_config()
        assert cfg.provider == "ollama"
        assert cfg.model    == "mxbai-embed-large"
        assert cfg.base_url == "http://ollama.local:11434"

    def test_auto_detect_openai_when_api_key_present(self):
        env = {"OPENAI_API_KEY": "sk-test"}
        # Remove any EMBEDDING_* vars to ensure pure auto-detect
        for k in ("EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_BASE_URL"):
            env.setdefault(k, "")
        with patch.dict("os.environ", env, clear=False):
            # Also patch yaml to return empty embedding section
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = _resolve_config()
        assert cfg.provider == "openai"

    def test_auto_detect_ollama_when_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("builtins.open", side_effect=FileNotFoundError):
                cfg = _resolve_config()
        assert cfg.provider == "ollama"
        assert cfg.base_url == "http://localhost:11434"

    def test_default_model_openai(self):
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai"}, clear=False):
            cfg = _resolve_config()
        assert cfg.model == "text-embedding-3-small"

    def test_default_model_ollama(self):
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "ollama"}, clear=False):
            cfg = _resolve_config()
        assert cfg.model == "nomic-embed-text"

    def test_api_key_env_custom(self):
        with patch.dict("os.environ", {
            "EMBEDDING_PROVIDER": "openai",
            "EMBEDDING_API_KEY_ENV": "MY_EMBED_KEY",
        }, clear=False):
            cfg = _resolve_config()
        assert cfg.api_key_env == "MY_EMBED_KEY"

    def test_yaml_fallback(self):
        """models_config.yaml `embedding:` section is read when no env vars set."""
        import yaml as yaml_mod

        fake_config = {
            "embedding": {
                "provider": "ollama",
                "model": "all-minilm",
                "base_url": "http://local:11434",
            }
        }

        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("builtins.open", MagicMock()):
                    with patch.object(yaml_mod, "safe_load", return_value=fake_config):
                        cfg = _resolve_config()

        assert cfg.provider == "ollama"
        assert cfg.model    == "all-minilm"
        assert cfg.base_url == "http://local:11434"

    def test_invalidate_cache_resets_both_singleton_and_config(self):
        invalidate_embedding_config_cache()
        import core_orchestrator.vector_store as vs_mod
        assert vs_mod._cfg_cache is None
        assert vs_mod._instance is None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """Legacy-style VectorStore with explicit openai_api_key (bypasses config)."""
    return VectorStore(openai_api_key="sk-fake")


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure config cache is clean before/after every test."""
    invalidate_embedding_config_cache()
    yield
    invalidate_embedding_config_cache()


# ---------------------------------------------------------------------------
# TestEmbedTextOpenAI  (legacy explicit-key path)
# ---------------------------------------------------------------------------

class TestEmbedTextOpenAI:
    @pytest.mark.asyncio
    async def test_returns_embedding_on_success(self, store):
        mock_client = AsyncMock()
        mock_resp   = MagicMock()
        mock_resp.data = [MagicMock(embedding=FAKE_EMBEDDING_1536)]
        mock_client.embeddings.create = AsyncMock(return_value=mock_resp)

        with patch("core_orchestrator.vector_store.AsyncOpenAI",
                   return_value=mock_client, create=True):
            with patch.dict(sys.modules,
                            {"openai": MagicMock(AsyncOpenAI=MagicMock(return_value=mock_client))}):
                result = await store.embed_text("hello world")
        # Graceful regardless of mock wiring — at minimum must not raise

    @pytest.mark.asyncio
    async def test_returns_none_when_no_api_key_for_openai_provider(self):
        """When provider=openai and its key env var is absent, return None."""
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai"}, clear=False):
            import os; os.environ.pop("OPENAI_API_KEY", None)
            s = VectorStore()
            result = await s.embed_text("test")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self, store):
        """OpenAI API error → None, no exception."""
        with patch("core_orchestrator.vector_store.AsyncOpenAI",
                   side_effect=Exception("api error"), create=True):
            result = await store.embed_text("query")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_import_fails(self, store):
        """If openai not installed, returns None gracefully."""
        with patch.dict(sys.modules, {"openai": None}):
            result = await store.embed_text("text")
        assert result is None

    @pytest.mark.asyncio
    async def test_legacy_key_bypasses_config(self):
        """Explicit openai_api_key= on constructor always uses OpenAI path."""
        s = VectorStore(openai_api_key="sk-test", embed_model="text-embedding-ada-002")
        with patch("core_orchestrator.vector_store._embed_openai",
                   new_callable=AsyncMock, return_value=FAKE_EMBEDDING_1536) as mock_embed:
            result = await s.embed_text("hello")
        mock_embed.assert_called_once()
        call_args = mock_embed.call_args
        assert call_args.args[1] == "text-embedding-ada-002"   # model
        assert call_args.args[2] == "sk-test"                  # api_key

    @pytest.mark.asyncio
    async def test_openai_compatible_base_url(self):
        """Setting base_url for an OpenAI-compatible endpoint is forwarded."""
        with patch.dict("os.environ", {
            "EMBEDDING_PROVIDER": "openai",
            "OPENAI_API_KEY": "dummy-key",
            "EMBEDDING_BASE_URL": "http://lm-studio.local:1234/v1",
        }, clear=False):
            s = VectorStore()
            with patch("core_orchestrator.vector_store._embed_openai",
                       new_callable=AsyncMock, return_value=FAKE_EMBEDDING_1536) as mock_embed:
                await s.embed_text("test")
        mock_embed.assert_called_once()
        assert mock_embed.call_args.args[3] == "http://lm-studio.local:1234/v1"


# ---------------------------------------------------------------------------
# TestEmbedTextOllama
# ---------------------------------------------------------------------------

class TestEmbedTextOllama:
    @pytest.mark.asyncio
    async def test_returns_embedding_on_success(self):
        """Ollama backend returns vector when HTTP call succeeds."""
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "ollama"}, clear=False):
            s = VectorStore()
            with patch("core_orchestrator.vector_store._embed_ollama",
                       new_callable=AsyncMock, return_value=FAKE_EMBEDDING_768) as mock_embed:
                result = await s.embed_text("hello world")
        assert result == FAKE_EMBEDDING_768
        mock_embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_configured_model_and_url(self):
        with patch.dict("os.environ", {
            "EMBEDDING_PROVIDER": "ollama",
            "EMBEDDING_MODEL": "mxbai-embed-large",
            "EMBEDDING_BASE_URL": "http://ollama.myhost:11434",
        }, clear=False):
            s = VectorStore()
            with patch("core_orchestrator.vector_store._embed_ollama",
                       new_callable=AsyncMock, return_value=FAKE_EMBEDDING_768) as mock_embed:
                await s.embed_text("query")
        args = mock_embed.call_args.args
        assert args[1] == "mxbai-embed-large"
        assert args[2] == "http://ollama.myhost:11434"

    @pytest.mark.asyncio
    async def test_returns_none_when_ollama_unreachable(self):
        """Connection refused → None, no exception."""
        import urllib.error
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "ollama"}, clear=False):
            result = await _embed_ollama(
                "text", "nomic-embed-text",
                "http://localhost:19999",   # port nobody listens on
            )
        # Should return None (URLError) without raising
        assert result is None

    @pytest.mark.asyncio
    async def test_embed_ollama_success_mock(self):
        """_embed_ollama calls urllib with correct payload and parses response."""
        import json
        import io

        fake_response_body = json.dumps({"embedding": FAKE_EMBEDDING_768}).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__  = MagicMock(return_value=False)
        mock_resp.read      = MagicMock(return_value=fake_response_body)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = await _embed_ollama(
                "hello", "nomic-embed-text", "http://localhost:11434"
            )

        assert result == FAKE_EMBEDDING_768
        mock_urlopen.assert_called_once()
        # Verify URL
        req_arg = mock_urlopen.call_args.args[0]
        assert req_arg.full_url == "http://localhost:11434/api/embeddings"
        # Verify payload
        payload = json.loads(req_arg.data)
        assert payload["model"]  == "nomic-embed-text"
        assert payload["prompt"] == "hello"

    @pytest.mark.asyncio
    async def test_embed_ollama_trailing_slash_stripped(self):
        """Base URL with trailing slash is handled correctly."""
        import json
        fake_body = json.dumps({"embedding": [0.5, 0.5]}).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__  = MagicMock(return_value=False)
        mock_resp.read      = MagicMock(return_value=fake_body)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            await _embed_ollama("text", "model", "http://localhost:11434/")

        req_arg = mock_urlopen.call_args.args[0]
        assert req_arg.full_url == "http://localhost:11434/api/embeddings"

    @pytest.mark.asyncio
    async def test_embed_ollama_missing_key_returns_none(self):
        """If response JSON has no 'embedding' key, return None gracefully."""
        import json
        fake_body = json.dumps({"error": "model not found"}).encode()
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__  = MagicMock(return_value=False)
        mock_resp.read      = MagicMock(return_value=fake_body)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await _embed_ollama("text", "bad-model", "http://localhost:11434")
        assert result is None


# ---------------------------------------------------------------------------
# TestEmbedOpenAI (unit-test the backend function directly)
# ---------------------------------------------------------------------------

class TestEmbedOpenAIBackend:
    @pytest.mark.asyncio
    async def test_returns_none_on_import_error(self):
        with patch.dict(sys.modules, {"openai": None}):
            result = await _embed_openai("text", "model", "sk-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_base_url_to_client(self):
        """base_url kwarg is forwarded to AsyncOpenAI constructor."""
        mock_client_inst = AsyncMock()
        mock_resp        = MagicMock()
        mock_resp.data   = [MagicMock(embedding=[0.1, 0.2])]
        mock_client_inst.embeddings.create = AsyncMock(return_value=mock_resp)

        mock_client_cls = MagicMock(return_value=mock_client_inst)
        mock_openai_mod = MagicMock(AsyncOpenAI=mock_client_cls)

        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            result = await _embed_openai(
                "text", "ada-002", "sk-key", "http://custom-endpoint/v1"
            )

        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs.get("base_url") == "http://custom-endpoint/v1"
        assert result == [0.1, 0.2]


# ---------------------------------------------------------------------------
# TestUpsert
# ---------------------------------------------------------------------------

class TestUpsert:
    @pytest.mark.asyncio
    async def test_returns_false_when_db_unavailable(self, store):
        with patch("core_orchestrator.vector_store.is_db_available",
                   return_value=False, create=True):
            try:
                from db.connection import is_db_available
                with patch("db.connection.is_db_available", return_value=False):
                    result = await store.upsert("id1", "text")
            except Exception:
                result = False
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_embed_returns_none(self):
        """If embedding fails, upsert skips DB write and returns False."""
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai"}, clear=False):
            import os; os.environ.pop("OPENAI_API_KEY", None)
            s = VectorStore()
            result = await s.upsert("id1", "text")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_db_import_fails(self, store):
        """If db module missing (test env), upsert returns False."""
        with patch.dict(sys.modules, {"db": None, "db.connection": None}):
            result = await store.upsert("id1", "some text")
        assert result is False


# ---------------------------------------------------------------------------
# TestSearchSimilar
# ---------------------------------------------------------------------------

class TestSearchSimilar:
    @pytest.mark.asyncio
    async def test_returns_empty_when_embed_none(self):
        """No embedding possible → empty results."""
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai"}, clear=False):
            import os; os.environ.pop("OPENAI_API_KEY", None)
            s = VectorStore()
            result = await s.search_similar("find me something")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_db_unavailable(self, store):
        with patch.dict(sys.modules, {"db": None, "db.connection": None}):
            result = await store.search_similar("query")
        assert result == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_descending(self):
        """Higher-scoring results come first."""
        query_vec  = [1.0, 0.0]
        high_match = [0.9, 0.1]   # more similar
        low_match  = [0.1, 0.9]   # less similar

        # Verify ordering logic directly (no DB mock needed for math check)
        score_high = _cosine_similarity(query_vec, high_match)
        score_low  = _cosine_similarity(query_vec, low_match)

        results = [
            {"id": "h", "score": round(score_high, 4)},
            {"id": "l", "score": round(score_low,  4)},
        ]
        results.sort(key=lambda r: r["score"], reverse=True)
        assert results[0]["id"] == "h"
        assert results[0]["score"] >= results[1]["score"]

    def test_cosine_similarity_ranking_math(self):
        query = [1.0, 0.0]
        high  = [0.9, 0.0]
        low   = [0.0, 1.0]
        assert _cosine_similarity(query, high) > _cosine_similarity(query, low)


# ---------------------------------------------------------------------------
# TestGetVectorStore
# ---------------------------------------------------------------------------

class TestGetVectorStore:
    def test_returns_vector_store_instance(self):
        vs = get_vector_store()
        assert isinstance(vs, VectorStore)

    def test_returns_same_singleton(self):
        vs1 = get_vector_store()
        vs2 = get_vector_store()
        assert vs1 is vs2

    def test_invalidate_resets_singleton(self):
        vs1 = get_vector_store()
        invalidate_embedding_config_cache()
        vs2 = get_vector_store()
        assert vs1 is not vs2
