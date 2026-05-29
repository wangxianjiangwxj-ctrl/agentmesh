"""Unit tests for agentmesh.a2a._trace (TraceProvider / TraceContext)."""

from __future__ import annotations

import threading
import time

import pytest

from agentmesh.a2a._trace import (
    TraceContext,
    TraceProvider,
    with_trace_context,
)


# ======================================================================
# TraceContext
# ======================================================================


class TestTraceContext:
    def test_create_root_context(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
        )
        assert ctx.trace_id == "a" * 32
        assert ctx.parent_span_id == ""
        assert ctx.span_id == "b" * 16
        assert ctx.baggage == {}

    def test_create_with_baggage(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
            baggage={"env": "prod", "region": "us-east"},
        )
        assert ctx.baggage["env"] == "prod"
        assert ctx.baggage["region"] == "us-east"

    def test_invalid_trace_id_short(self) -> None:
        with pytest.raises(ValueError, match="trace_id"):
            TraceContext(trace_id="a" * 31, parent_span_id="", span_id="b" * 16)

    def test_invalid_trace_id_long(self) -> None:
        with pytest.raises(ValueError, match="trace_id"):
            TraceContext(trace_id="a" * 33, parent_span_id="", span_id="b" * 16)

    def test_invalid_span_id(self) -> None:
        with pytest.raises(ValueError, match="span_id"):
            TraceContext(trace_id="a" * 32, parent_span_id="", span_id="b" * 15)

    def test_invalid_parent_span_id(self) -> None:
        with pytest.raises(ValueError, match="parent_span_id"):
            TraceContext(
                trace_id="a" * 32,
                parent_span_id="x" * 16,
                span_id="b" * 16,
            )

    def test_non_hex_trace_id(self) -> None:
        with pytest.raises(ValueError):
            TraceContext(
                trace_id="z" * 32,
                parent_span_id="",
                span_id="b" * 16,
            )

    def test_frozen_immutable(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
        )
        with pytest.raises(AttributeError):
            ctx.trace_id = "c" * 32  # type: ignore[misc]

    # -- Serialisation round-trip -----------------------------------------

    def test_to_header(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
            baggage={"k": "v"},
        )
        hdrs = ctx.to_header()
        assert hdrs["trace_id"] == "a" * 32
        assert hdrs["parent_span_id"] == ""
        assert hdrs["span_id"] == "b" * 16
        assert hdrs["baggage"] == "k=v"

    def test_from_header_valid(self) -> None:
        hdrs = {
            "trace_id": "a" * 32,
            "parent_span_id": "b" * 16,
            "span_id": "c" * 16,
            "baggage": "env=test,region=us",
        }
        ctx = TraceContext.from_header(hdrs)
        assert ctx is not None
        assert ctx.trace_id == "a" * 32
        assert ctx.parent_span_id == "b" * 16
        assert ctx.span_id == "c" * 16
        assert ctx.baggage == {"env": "test", "region": "us"}

    def test_from_header_missing_fields(self) -> None:
        assert TraceContext.from_header({}) is None
        assert TraceContext.from_header({"trace_id": "a" * 32}) is None
        assert TraceContext.from_header({"span_id": "b" * 16}) is None

    def test_from_header_empty_trace_id(self) -> None:
        assert TraceContext.from_header({"trace_id": "", "span_id": "b" * 16}) is None

    def test_from_header_malformed_baggage(self) -> None:
        hdrs = {
            "trace_id": "a" * 32,
            "parent_span_id": "",
            "span_id": "b" * 16,
            "baggage": "no-equals",
        }
        ctx = TraceContext.from_header(hdrs)
        assert ctx is not None
        assert ctx.baggage == {}

    def test_roundtrip(self) -> None:
        original = TraceContext(
            trace_id="a" * 32,
            parent_span_id="b" * 16,
            span_id="c" * 16,
            baggage={"foo": "bar"},
        )
        restored = TraceContext.from_header(original.to_header())
        assert restored == original

    # -- Child spans -------------------------------------------------------

    def test_new_child(self) -> None:
        parent = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
        )
        child = parent.new_child()
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id
        assert child.span_id != parent.span_id
        assert len(child.span_id) == 16

    def test_child_preserves_baggage(self) -> None:
        parent = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
            baggage={"env": "staging"},
        )
        child = parent.new_child()
        assert child.baggage == {"env": "staging"}

    def test_child_baggage_independent(self) -> None:
        parent = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
            baggage={"shared": "yes"},
        )
        child = parent.new_child().with_baggage("extra", "value")
        assert "extra" not in parent.baggage
        assert child.baggage["extra"] == "value"

    # -- with_baggage -----------------------------------------------------

    def test_with_baggage_immutability(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
            baggage={"existing": "val"},
        )
        new_ctx = ctx.with_baggage("new_key", "new_val")
        assert "new_key" not in ctx.baggage  # original unchanged
        assert new_ctx.baggage["new_key"] == "new_val"
        assert new_ctx.baggage["existing"] == "val"


# ======================================================================
# TraceProvider
# ======================================================================


class TestTraceProvider:
    def test_new_context(self) -> None:
        provider = TraceProvider()
        ctx = provider.new_context()
        assert len(ctx.trace_id) == 32
        assert len(ctx.span_id) == 16
        assert ctx.parent_span_id == ""

    def test_new_context_with_baggage(self) -> None:
        provider = TraceProvider()
        ctx = provider.new_context(baggage={"from": "provider"})
        assert ctx.baggage == {"from": "provider"}

    def test_unique_trace_ids(self) -> None:
        provider = TraceProvider()
        ids = {provider.new_context().trace_id for _ in range(100)}
        assert len(ids) == 100  # all unique

    def test_unique_span_ids(self) -> None:
        ids = {TraceProvider.new_span_id() for _ in range(100)}
        assert len(ids) == 100

    def test_child_context(self) -> None:
        provider = TraceProvider()
        parent = provider.new_context()
        child = provider.child_context(parent)
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id

    def test_child_context_with_extra_baggage(self) -> None:
        provider = TraceProvider()
        parent = provider.new_context(baggage={"base": "val"})
        child = provider.child_context(parent, baggage={"extra": "data"})
        assert child.baggage["base"] == "val"
        assert child.baggage["extra"] == "data"

    def test_inject(self) -> None:
        provider = TraceProvider()
        ctx = provider.new_context()
        headers = {"content-type": "application/json"}
        result = provider.inject(ctx, headers)
        assert result is headers  # mutated in place
        assert result["trace_id"] == ctx.trace_id
        assert result["span_id"] == ctx.span_id

    def test_inject_default_headers(self) -> None:
        provider = TraceProvider()
        ctx = provider.new_context()
        headers = provider.inject(ctx)
        assert "trace_id" in headers

    def test_extract(self) -> None:
        provider = TraceProvider()
        ctx = provider.new_context()
        headers = provider.inject(ctx)
        extracted = TraceProvider.extract(headers)
        assert extracted is not None
        assert extracted.trace_id == ctx.trace_id

    def test_extract_none(self) -> None:
        assert TraceProvider.extract({}) is None


# ======================================================================
# with_trace_context (context manager)
# ======================================================================


class TestWithTraceContext:
    def test_sets_current_context(self) -> None:
        ctx = TraceContext(
            trace_id="a" * 32,
            parent_span_id="",
            span_id="b" * 16,
        )
        assert TraceProvider.get_current_context() is None
        with with_trace_context(ctx):
            assert TraceProvider.get_current_context() is ctx
        assert TraceProvider.get_current_context() is None

    def test_auto_generates_context(self) -> None:
        with with_trace_context() as ctx:
            assert ctx is not None
            assert len(ctx.trace_id) == 32
            assert len(ctx.span_id) == 16
            assert TraceProvider.get_current_context() is ctx

    def test_thread_isolation(self) -> None:
        """Context should be thread-local — not visible in other threads."""
        main_ctx = TraceProvider().new_context()
        captured_main: list[str] = []
        captured_thread: list[str] = []

        def worker() -> None:
            captured_thread.append(
                str(TraceProvider.get_current_context() is not None)
            )

        with with_trace_context(main_ctx):
            captured_main.append(str(TraceProvider.get_current_context() is not None))
            t = threading.Thread(target=worker)
            t.start()
            t.join()

        assert captured_main == ["True"]
        # Thread should not see the main thread's context
        assert captured_thread == ["False"]

    def test_restores_previous_context(self) -> None:
        outer = TraceProvider().new_context()
        inner = TraceContext(
            trace_id="c" * 32,
            parent_span_id="",
            span_id="d" * 16,
        )

        with with_trace_context(outer):
            with with_trace_context(inner):
                assert TraceProvider.get_current_context() is inner
            assert TraceProvider.get_current_context() is outer
        assert TraceProvider.get_current_context() is None

    def test_nested_restores_on_exception(self) -> None:
        outer = TraceProvider().new_context()
        try:
            with with_trace_context(outer):
                with with_trace_context() as inner_ctx:
                    assert TraceProvider.get_current_context() is inner_ctx
                    raise RuntimeError("boom")
        except RuntimeError:
            pass
        # outer should be restored after the inner block's exception
        assert TraceProvider.get_current_context() is None

    def test_provider_argument(self) -> None:
        provider = TraceProvider()
        with with_trace_context(provider=provider) as ctx:
            assert len(ctx.trace_id) == 32
            assert len(ctx.span_id) == 16


# ======================================================================
# Edge cases
# ======================================================================


class TestEdgeCases:
    def test_context_manager_yields_correct_ctx(self) -> None:
        ctx = TraceProvider().new_context()
        with with_trace_context(ctx) as yielded:
            assert yielded is ctx

    def test_baggage_encode_decode_roundtrip(self) -> None:
        baggage = {"key1": "val1", "key2": "val2"}
        from agentmesh.a2a._trace import _encode_baggage, _decode_baggage

        encoded = _encode_baggage(baggage)
        decoded = _decode_baggage(encoded)
        assert decoded == baggage

    def test_baggage_empty(self) -> None:
        from agentmesh.a2a._trace import _encode_baggage, _decode_baggage

        assert _encode_baggage({}) == ""
        assert _decode_baggage("") == {}
        assert _decode_baggage("  ") == {}

    def test_timer_accuracy(self) -> None:
        """Context manager does not interfere with timing."""
        import time

        start = time.monotonic()
        with with_trace_context():
            time.sleep(0.01)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.009
