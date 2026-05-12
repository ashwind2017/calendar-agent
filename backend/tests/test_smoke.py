"""Smoke tests that don't require live OAuth."""
import os
import sys
import tempfile

# Make backend modules importable when run from project root or backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """All modules import without error."""
    import config  # noqa
    import auth  # noqa
    import calendar_tools  # noqa
    import gmail_tools  # noqa
    import drive_tools  # noqa
    import chat_service  # noqa
    import memory_service  # noqa
    import rag_service  # noqa
    import prep_assistant  # noqa
    import app  # noqa


def test_tools_schema_has_required_tools():
    from chat_service import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "list_events" in names
    assert "find_free_slots" in names
    assert "create_email_draft" in names
    assert "analyze_meeting_time" in names
    assert "retrieve_personal_context" in names


def test_rag_chunking():
    from rag_service import _chunk_text
    chunks = _chunk_text("hello " * 1000, chunk_size=800, overlap=100)
    assert len(chunks) > 1
    # Overlap means each subsequent chunk should share some content
    if len(chunks) > 1:
        assert chunks[0][-50:] != chunks[1][-50:]  # not identical


def test_rag_keyword_score():
    from rag_service import _keyword_score
    score = _keyword_score("dog cat", "the dog runs fast")
    assert score > 0
    zero = _keyword_score("dog cat", "completely different words")
    assert zero == 0.0


def test_rag_index_add_retrieve(tmp_path):
    """Test RAG index can add and retrieve docs without embeddings."""
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from rag_service import RAGIndex
        idx = RAGIndex("test_session")
        idx.add_document(
            source="prefs.md",
            text="I prefer morning meetings before 11am. Afternoons are for deep work.",
        )
        results = idx.retrieve("when do I prefer meetings", k=3)
        assert len(results) > 0
        assert any("morning" in r["chunk"].lower() for r in results)
    finally:
        config.CACHE_DIR = original_cache


def test_memory_add_and_retrieve(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        # Re-import to pick up the patched cache dir
        from memory_service import ConversationMemory
        mem = ConversationMemory()
        sid = "test_user_session"
        mem.add_turn(sid, "user", "hello")
        mem.add_turn(sid, "assistant", "hi there")
        turns = mem.get_turns(sid)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["content"] == "hi there"
    finally:
        config.CACHE_DIR = original_cache


def test_auth_url_generates():
    """Auth URL generation should work when client id is set."""
    from config import config
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        # Skip if creds not configured (e.g., CI without secrets)
        return
    from auth import get_auth_url
    url, state = get_auth_url()
    assert url.startswith("https://accounts.google.com")
    assert "client_id=" in url
    assert state


if __name__ == "__main__":
    # Simple inline runner so this works without pytest installed
    import traceback
    tests = [
        test_imports,
        test_tools_schema_has_required_tools,
        test_rag_chunking,
        test_rag_keyword_score,
        test_auth_url_generates,
    ]
    # Tests needing tmp_path
    import tempfile
    parametrized = [
        (test_rag_index_add_retrieve, "rag_index_add_retrieve"),
        (test_memory_add_and_retrieve, "memory_add_and_retrieve"),
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  pass  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    for t, name in parametrized:
        with tempfile.TemporaryDirectory() as td:
            try:
                import pathlib
                t(pathlib.Path(td))
                print(f"  pass  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
