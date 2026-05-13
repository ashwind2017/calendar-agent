"""Smoke tests that don't require live OAuth or live LLM/Google API calls.

The inline runner at the bottom dispatches tests with the right fixtures
(none, tmp_path, or a shared cache override). No pytest dependency.
"""
import json
import os
import sys
import tempfile

# Make backend modules importable when run from project root or backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Existing baseline tests
# =============================================================================


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
    import middleware  # noqa
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
        return
    from auth import get_auth_url
    url, state = get_auth_url()
    assert url.startswith("https://accounts.google.com")
    assert "client_id=" in url
    assert state


# =============================================================================
# chat_service.py logic tests (no live LLM calls)
# =============================================================================


def test_parse_iso_valid():
    from chat_service import _parse_iso
    dt = _parse_iso("2026-05-12T10:00:00Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 12


def test_parse_iso_with_offset():
    from chat_service import _parse_iso
    dt = _parse_iso("2026-05-12T10:00:00-04:00")
    assert dt is not None
    assert dt.hour == 10


def test_parse_iso_invalid_returns_none():
    from chat_service import _parse_iso
    assert _parse_iso("not-a-date") is None
    assert _parse_iso("") is None
    assert _parse_iso(None) is None


def test_execute_tool_unknown_returns_error():
    from chat_service import execute_tool
    result = execute_tool("nonexistent_tool", {}, creds=None, session_id="x")
    assert result["ok"] is False
    assert "Unknown tool" in result["error"]


def test_execute_tool_find_free_slots_missing_inputs():
    from chat_service import execute_tool
    # No start_iso or end_iso provided
    result = execute_tool("find_free_slots", {"duration_minutes": 30}, creds=None, session_id="x")
    assert result["ok"] is False
    assert "start_iso" in result["error"] or "end_iso" in result["error"]


def test_execute_tool_propose_event_missing_inputs():
    from chat_service import execute_tool
    result = execute_tool("propose_calendar_event", {"summary": "test"}, creds=None, session_id="x")
    assert result["ok"] is False
    assert "start_iso" in result["error"] or "end_iso" in result["error"]


def test_execute_tool_propose_event_happy_path():
    from chat_service import execute_tool
    result = execute_tool(
        "propose_calendar_event",
        {
            "summary": "Sync",
            "start_iso": "2026-05-12T10:00:00Z",
            "end_iso": "2026-05-12T10:30:00Z",
            "attendees": ["a@x.com"],
        },
        creds=None,
        session_id="x",
    )
    assert result["ok"] is True
    assert result["proposal"]["summary"] == "Sync"
    assert result["proposal"]["attendees"] == ["a@x.com"]


def test_execute_tool_create_event_missing_inputs():
    from chat_service import execute_tool
    result = execute_tool("create_calendar_event", {"summary": "test"}, creds=None, session_id="x")
    assert result["ok"] is False


def test_preview_short_unchanged():
    from chat_service import _preview
    s = _preview({"ok": True, "count": 1})
    assert "ok" in s
    assert "..." not in s


def test_preview_truncates_long():
    from chat_service import _preview
    big = {"ok": True, "events": ["x" * 100 for _ in range(50)]}
    out = _preview(big)
    assert len(out) <= 410
    assert out.endswith("...")


def test_execute_tool_retrieve_personal_context_no_entries(tmp_path):
    """Dispatch routes retrieve_personal_context to the RAG index."""
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        # Reset the module-level index cache so we get a fresh one with our patched path
        import rag_service
        rag_service._indexes = {}
        from chat_service import execute_tool
        result = execute_tool(
            "retrieve_personal_context",
            {"query": "anything", "k": 3},
            creds=None,
            session_id="empty_session",
        )
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["chunks"] == []
    finally:
        config.CACHE_DIR = original_cache


# =============================================================================
# rag_service.py edge cases
# =============================================================================


def test_chunk_text_empty():
    from rag_service import _chunk_text
    assert _chunk_text("") == []
    assert _chunk_text("   ") == []


def test_chunk_text_small_input_single_chunk():
    from rag_service import _chunk_text
    chunks = _chunk_text("short text", chunk_size=800, overlap=100)
    assert len(chunks) == 1
    assert chunks[0] == "short text"


def test_chunk_text_large_input_many_chunks():
    from rag_service import _chunk_text
    text = "a" * 5000
    chunks = _chunk_text(text, chunk_size=800, overlap=100)
    # Effective stride is 700, so ceil(5000/700) ish
    assert len(chunks) >= 6
    # Each chunk except potentially the last should be 800 chars
    for c in chunks[:-1]:
        assert len(c) == 800


def test_retrieve_no_entries_returns_empty(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from rag_service import RAGIndex
        idx = RAGIndex("fresh_session")
        results = idx.retrieve("any query", k=5)
        assert results == []
    finally:
        config.CACHE_DIR = original_cache


def test_all_text_concatenation(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from rag_service import RAGIndex
        idx = RAGIndex("alltext_session")
        idx.add_document(source="a.md", text="first doc content")
        idx.add_document(source="b.md", text="second doc content")
        all_text = idx.all_text()
        assert "[a.md]" in all_text
        assert "[b.md]" in all_text
        assert "first doc content" in all_text
        assert "second doc content" in all_text
    finally:
        config.CACHE_DIR = original_cache


def test_cosine_zero_vectors():
    from rag_service import _cosine
    assert _cosine([], []) == 0.0
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert _cosine([1.0, 1.0], [0.0, 0.0]) == 0.0


def test_cosine_mismatched_lengths():
    from rag_service import _cosine
    assert _cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_cosine_identical_vectors():
    from rag_service import _cosine
    sim = _cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert abs(sim - 1.0) < 1e-6


def test_cosine_orthogonal_vectors():
    from rag_service import _cosine
    sim = _cosine([1.0, 0.0], [0.0, 1.0])
    assert abs(sim) < 1e-6


def test_rag_index_clear_removes_disk(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from rag_service import RAGIndex
        idx = RAGIndex("clearme")
        idx.add_document(source="x", text="some text here for clearing")
        assert os.path.exists(idx.path)
        idx.clear()
        assert idx.entries == []
        assert not os.path.exists(idx.path)
    finally:
        config.CACHE_DIR = original_cache


# =============================================================================
# prep_assistant.py tests (use a stub for calendar_tools, no API calls)
# =============================================================================


def test_past_meetings_with_filters_by_attendee():
    import prep_assistant
    import calendar_tools

    fake_events = [
        {
            "id": "1",
            "summary": "Sync with Sarah",
            "attendees": [{"email": "sarah@x.com"}, {"email": "user@me.com"}],
        },
        {
            "id": "2",
            "summary": "Solo block",
            "attendees": [],
        },
        {
            "id": "3",
            "summary": "Random unrelated",
            "attendees": [{"email": "bob@y.com"}],
        },
        {
            "id": "4",
            "summary": "Sarah follow-up",
            "attendees": [{"email": "Sarah@X.com"}],  # case differs
        },
    ]

    original_list = calendar_tools.list_events
    calendar_tools.list_events = lambda creds, start=None, end=None, max_results=500: fake_events
    try:
        results = prep_assistant._past_meetings_with(creds=None, attendees=["sarah@x.com"])
        ids = sorted(r["id"] for r in results)
        assert ids == ["1", "4"]
    finally:
        calendar_tools.list_events = original_list


def test_past_meetings_with_no_matches():
    import prep_assistant
    import calendar_tools

    fake_events = [
        {"id": "1", "summary": "Solo", "attendees": []},
        {"id": "2", "summary": "Other", "attendees": [{"email": "z@z.com"}]},
    ]
    original_list = calendar_tools.list_events
    calendar_tools.list_events = lambda creds, start=None, end=None, max_results=500: fake_events
    try:
        results = prep_assistant._past_meetings_with(creds=None, attendees=["nobody@x.com"])
        assert results == []
    finally:
        calendar_tools.list_events = original_list


def test_list_upcoming_with_prep_readiness_flags():
    import prep_assistant
    import calendar_tools

    fake_events = [
        {
            "id": "solo1",
            "summary": "Focus block",
            "start": "2026-05-13T09:00:00Z",
            "end": "2026-05-13T11:00:00Z",
            "attendees": [],
        },
        {
            "id": "meet1",
            "summary": "1:1 with Sarah",
            "start": "2026-05-13T14:00:00Z",
            "end": "2026-05-13T14:30:00Z",
            "attendees": [
                {"email": "user@me.com"},
                {"email": "sarah@x.com"},
            ],
        },
        {
            "id": "self_only",
            "summary": "Self event",
            "start": "2026-05-14T09:00:00Z",
            "end": "2026-05-14T10:00:00Z",
            "attendees": [{"email": "user@me.com"}],
        },
    ]
    original_list = calendar_tools.list_events
    original_email = calendar_tools.get_user_email
    calendar_tools.list_events = lambda creds, start=None, end=None, max_results=100: fake_events
    calendar_tools.get_user_email = lambda creds: "user@me.com"
    try:
        out = prep_assistant.list_upcoming_with_prep_readiness(creds=None, days_ahead=7)
        by_id = {m["id"]: m for m in out}
        assert by_id["solo1"]["prep_eligible"] is False
        assert by_id["solo1"]["attendee_count"] == 0
        assert by_id["meet1"]["prep_eligible"] is True
        assert by_id["meet1"]["attendee_count"] == 1
        # Self-only event (only the user is an attendee) is not prep-eligible
        assert by_id["self_only"]["prep_eligible"] is False
        assert by_id["self_only"]["attendee_count"] == 0
    finally:
        calendar_tools.list_events = original_list
        calendar_tools.get_user_email = original_email


# =============================================================================
# memory_service.py tests
# =============================================================================


def test_memory_persists_across_instances(tmp_path):
    """A new ConversationMemory instance picks up turns written by an earlier one."""
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from memory_service import ConversationMemory
        sid = "persist_test"
        mem1 = ConversationMemory()
        mem1.add_turn(sid, "user", "first message")
        mem1.add_turn(sid, "assistant", "first reply")

        # New instance should re-load from disk
        mem2 = ConversationMemory()
        turns = mem2.get_turns(sid)
        assert len(turns) == 2
        assert turns[0]["content"] == "first message"
        assert turns[1]["content"] == "first reply"
    finally:
        config.CACHE_DIR = original_cache


def test_memory_clear_removes_disk_and_memory(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from memory_service import ConversationMemory
        mem = ConversationMemory()
        sid = "clear_test"
        mem.add_turn(sid, "user", "hi")
        path = mem._session_path(sid)
        assert os.path.exists(path)
        mem.clear(sid)
        assert mem.get_turns(sid) == []
        assert not os.path.exists(path)
    finally:
        config.CACHE_DIR = original_cache


def test_memory_get_turns_respects_limit(tmp_path):
    from config import config
    original_cache = config.CACHE_DIR
    config.CACHE_DIR = str(tmp_path)
    try:
        from memory_service import ConversationMemory
        mem = ConversationMemory()
        sid = "limit_test"
        for i in range(10):
            mem.add_turn(sid, "user", f"msg {i}")
        turns = mem.get_turns(sid, limit=3)
        assert len(turns) == 3
        # Should be the last 3
        assert turns[-1]["content"] == "msg 9"
        assert turns[0]["content"] == "msg 7"
    finally:
        config.CACHE_DIR = original_cache


# =============================================================================
# middleware.py tests
# =============================================================================


def test_record_tool_call_updates_counters():
    import middleware
    # Reset state for a clean comparison
    middleware._tool_metrics["total_tool_calls"] = 0
    middleware._tool_metrics["by_tool_count"] = {}
    middleware._tool_metrics["by_tool_total_ms"] = {}

    middleware.record_tool_call("list_events", 12.5)
    middleware.record_tool_call("list_events", 7.5)
    middleware.record_tool_call("find_free_slots", 100.0)

    assert middleware._tool_metrics["total_tool_calls"] == 3
    assert middleware._tool_metrics["by_tool_count"]["list_events"] == 2
    assert middleware._tool_metrics["by_tool_count"]["find_free_slots"] == 1
    assert middleware._tool_metrics["by_tool_total_ms"]["list_events"] == 20.0


def test_get_metrics_snapshot_shape():
    import middleware
    # Reset and then record a couple things
    middleware._tool_metrics["total_tool_calls"] = 0
    middleware._tool_metrics["by_tool_count"] = {}
    middleware._tool_metrics["by_tool_total_ms"] = {}
    middleware._metrics["total_requests"] = 0
    middleware._metrics["errors"] = 0
    middleware._metrics["by_path_count"] = {}
    middleware._metrics["by_path_total_ms"] = {}

    middleware.record_tool_call("list_events", 10.0)
    middleware.record_tool_call("list_events", 20.0)

    snap = middleware.get_metrics_snapshot()
    assert "requests" in snap
    assert "tools" in snap
    assert snap["tools"]["total_calls"] == 2
    assert snap["tools"]["by_tool_count"]["list_events"] == 2
    assert snap["tools"]["avg_latency_ms_by_tool"]["list_events"] == 15.0
    assert "total" in snap["requests"]
    assert "by_path_count" in snap["requests"]
    assert "avg_latency_ms_by_path" in snap["requests"]


def test_metrics_isolated_per_tool_name():
    import middleware
    middleware._tool_metrics["total_tool_calls"] = 0
    middleware._tool_metrics["by_tool_count"] = {}
    middleware._tool_metrics["by_tool_total_ms"] = {}

    middleware.record_tool_call("tool_a", 50.0)
    middleware.record_tool_call("tool_b", 100.0)

    assert middleware._tool_metrics["by_tool_count"]["tool_a"] == 1
    assert middleware._tool_metrics["by_tool_count"]["tool_b"] == 1
    assert middleware._tool_metrics["by_tool_total_ms"]["tool_a"] == 50.0
    assert middleware._tool_metrics["by_tool_total_ms"]["tool_b"] == 100.0
    # No cross-contamination
    assert "tool_a" in middleware._tool_metrics["by_tool_count"]
    assert "tool_b" in middleware._tool_metrics["by_tool_count"]


# =============================================================================
# app.py validation tests (TestClient, no live OAuth/LLM)
# =============================================================================


def _make_test_client():
    """Build a FastAPI TestClient. We import app fresh so middleware state is sane."""
    from fastapi.testclient import TestClient
    import app as app_module
    return TestClient(app_module.app)


def test_chat_endpoint_rejects_empty_message():
    client = _make_test_client()
    resp = client.post("/chat", json={"session_id": "anything", "message": ""})
    assert resp.status_code == 400
    assert "Empty message" in resp.json()["detail"]


def test_chat_endpoint_rejects_whitespace_only_message():
    client = _make_test_client()
    resp = client.post("/chat", json={"session_id": "anything", "message": "    "})
    assert resp.status_code == 400


def test_chat_endpoint_rejects_overlong_message():
    client = _make_test_client()
    long_msg = "x" * 4001
    resp = client.post("/chat", json={"session_id": "anything", "message": long_msg})
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"].lower()


def test_chat_endpoint_unauthenticated_session():
    """Valid-shaped request with an unknown session should fail auth, not validation."""
    client = _make_test_client()
    resp = client.post("/chat", json={"session_id": "no_such_session", "message": "hi"})
    assert resp.status_code == 401


def test_rag_upload_text_rejects_empty():
    client = _make_test_client()
    resp = client.post(
        "/rag/upload-text",
        json={"session_id": "any", "source": "note", "content": ""},
    )
    assert resp.status_code == 400
    assert "Empty content" in resp.json()["detail"]


def test_rag_upload_text_rejects_overlong():
    client = _make_test_client()
    resp = client.post(
        "/rag/upload-text",
        json={"session_id": "any", "source": "note", "content": "x" * 200_001},
    )
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"].lower()


def test_calendar_upcoming_missing_session_id():
    """GET without session_id should fail validation (422) before auth check."""
    client = _make_test_client()
    resp = client.get("/calendar/upcoming")
    assert resp.status_code == 422


def test_calendar_upcoming_unknown_session_id():
    client = _make_test_client()
    resp = client.get("/calendar/upcoming?session_id=nope")
    assert resp.status_code == 401


def test_auth_check_missing_session_id():
    client = _make_test_client()
    resp = client.get("/auth/check")
    assert resp.status_code == 422


def test_root_endpoint_ok():
    client = _make_test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "calendar-agent"


def test_metrics_endpoint_returns_snapshot():
    client = _make_test_client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "requests" in body
    assert "tools" in body


def test_prep_list_missing_session_id():
    client = _make_test_client()
    resp = client.get("/prep/list/upcoming")
    assert resp.status_code == 422


def test_rag_list_missing_session_id():
    client = _make_test_client()
    resp = client.get("/rag/list")
    assert resp.status_code == 422


# =============================================================================
# rate_limit.py tests
# =============================================================================


def test_rate_limit_under_budget_allows():
    from rate_limit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, retry_after = limiter.check("user1")
        assert allowed is True
        assert retry_after == 0


def test_rate_limit_over_budget_denies():
    from rate_limit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.check("user1")
    allowed, retry_after = limiter.check("user1")
    assert allowed is False
    assert retry_after >= 1


def test_rate_limit_different_keys_isolated():
    from rate_limit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60)
    # Burn key "a" to the limit
    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is False
    # Key "b" should still have full budget
    assert limiter.check("b")[0] is True
    assert limiter.check("b")[0] is True
    assert limiter.check("b")[0] is False


def test_rate_limit_window_expiration():
    import time
    from rate_limit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=0.5)
    assert limiter.check("k")[0] is True
    assert limiter.check("k")[0] is True
    # 3rd and 4th calls denied
    assert limiter.check("k")[0] is False
    assert limiter.check("k")[0] is False
    # Wait for window to expire
    time.sleep(0.6)
    allowed, _ = limiter.check("k")
    assert allowed is True


def test_rate_limit_enforce_raises_429():
    from fastapi import HTTPException
    from rate_limit import SlidingWindowLimiter, enforce
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60)
    # Use up the budget
    enforce(limiter, "user1", "test")
    enforce(limiter, "user1", "test")
    # Next call should raise
    raised = False
    try:
        enforce(limiter, "user1", "test")
    except HTTPException as exc:
        raised = True
        assert exc.status_code == 429
        assert "test" in exc.detail
        assert exc.headers is not None
        assert "Retry-After" in exc.headers
        assert int(exc.headers["Retry-After"]) >= 1
    assert raised, "enforce() should have raised HTTPException"


def test_rate_limit_reset_clears_state():
    from rate_limit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter(max_requests=2, window_seconds=60)
    limiter.check("a")
    limiter.check("a")
    assert limiter.check("a")[0] is False
    # Reset just key "a"
    limiter.reset("a")
    assert limiter.check("a")[0] is True
    # Reset all keys
    limiter.check("b")
    limiter.check("b")
    assert limiter.check("b")[0] is False
    limiter.reset()
    assert limiter.check("a")[0] is True
    assert limiter.check("b")[0] is True


def test_chat_endpoint_returns_429_when_spammed():
    """Spamming /chat past the chat_limiter budget should return 429."""
    import rate_limit
    # Reset limiter state so this test is isolated from any prior client calls
    rate_limit.chat_limiter.reset()
    client = _make_test_client()
    session_id = "spam_session_for_rate_limit"
    got_429 = False
    # chat_limiter is 30/60s. Fire 35 to guarantee we cross the budget.
    for _ in range(35):
        resp = client.post("/chat", json={"session_id": session_id, "message": "hi"})
        if resp.status_code == 429:
            got_429 = True
            assert "Retry-After" in resp.headers
            break
    # Clean up so later tests aren't impacted
    rate_limit.chat_limiter.reset()
    assert got_429, "Expected at least one 429 response after 35 rapid /chat calls"


# =============================================================================
# Inline runner (no pytest required)
# =============================================================================


if __name__ == "__main__":
    import pathlib
    import traceback

    # Tests with no fixtures
    simple_tests = [
        test_imports,
        test_tools_schema_has_required_tools,
        test_rag_chunking,
        test_rag_keyword_score,
        test_auth_url_generates,
        # chat_service
        test_parse_iso_valid,
        test_parse_iso_with_offset,
        test_parse_iso_invalid_returns_none,
        test_execute_tool_unknown_returns_error,
        test_execute_tool_find_free_slots_missing_inputs,
        test_execute_tool_propose_event_missing_inputs,
        test_execute_tool_propose_event_happy_path,
        test_execute_tool_create_event_missing_inputs,
        test_preview_short_unchanged,
        test_preview_truncates_long,
        # rag_service
        test_chunk_text_empty,
        test_chunk_text_small_input_single_chunk,
        test_chunk_text_large_input_many_chunks,
        test_cosine_zero_vectors,
        test_cosine_mismatched_lengths,
        test_cosine_identical_vectors,
        test_cosine_orthogonal_vectors,
        # prep_assistant
        test_past_meetings_with_filters_by_attendee,
        test_past_meetings_with_no_matches,
        test_list_upcoming_with_prep_readiness_flags,
        # middleware
        test_record_tool_call_updates_counters,
        test_get_metrics_snapshot_shape,
        test_metrics_isolated_per_tool_name,
        # app endpoints
        test_chat_endpoint_rejects_empty_message,
        test_chat_endpoint_rejects_whitespace_only_message,
        test_chat_endpoint_rejects_overlong_message,
        test_chat_endpoint_unauthenticated_session,
        test_rag_upload_text_rejects_empty,
        test_rag_upload_text_rejects_overlong,
        test_calendar_upcoming_missing_session_id,
        test_calendar_upcoming_unknown_session_id,
        test_auth_check_missing_session_id,
        test_root_endpoint_ok,
        test_metrics_endpoint_returns_snapshot,
        test_prep_list_missing_session_id,
        test_rag_list_missing_session_id,
        # rate_limit
        test_rate_limit_under_budget_allows,
        test_rate_limit_over_budget_denies,
        test_rate_limit_different_keys_isolated,
        test_rate_limit_window_expiration,
        test_rate_limit_enforce_raises_429,
        test_rate_limit_reset_clears_state,
        test_chat_endpoint_returns_429_when_spammed,
    ]

    # Tests needing a tmp_path fixture
    tmp_tests = [
        (test_rag_index_add_retrieve, "rag_index_add_retrieve"),
        (test_memory_add_and_retrieve, "memory_add_and_retrieve"),
        (test_execute_tool_retrieve_personal_context_no_entries, "execute_tool_retrieve_personal_context_no_entries"),
        (test_retrieve_no_entries_returns_empty, "retrieve_no_entries_returns_empty"),
        (test_all_text_concatenation, "all_text_concatenation"),
        (test_rag_index_clear_removes_disk, "rag_index_clear_removes_disk"),
        (test_memory_persists_across_instances, "memory_persists_across_instances"),
        (test_memory_clear_removes_disk_and_memory, "memory_clear_removes_disk_and_memory"),
        (test_memory_get_turns_respects_limit, "memory_get_turns_respects_limit"),
    ]

    passed = 0
    failed = 0
    for t in simple_tests:
        try:
            t()
            print(f"  pass  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    for t, name in tmp_tests:
        with tempfile.TemporaryDirectory() as td:
            try:
                t(pathlib.Path(td))
                print(f"  pass  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                traceback.print_exc()
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
