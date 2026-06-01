"""Unit tests for agentmesh.a2a._log (StructuredLogger / LogLevel / LoggerConfig)."""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile

import pytest

from agentmesh.a2a._log import LogLevel, LoggerConfig, StructuredLogger
from agentmesh.a2a._trace import TraceProvider, with_trace_context


# ======================================================================
# LogLevel
# ======================================================================


class TestLogLevel:
    def test_enum_values(self) -> None:
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARN.value == "WARN"
        assert LogLevel.ERROR.value == "ERROR"

    def test_to_stdlib(self) -> None:
        assert LogLevel.DEBUG.to_stdlib() == logging.DEBUG
        assert LogLevel.INFO.to_stdlib() == logging.INFO
        assert LogLevel.WARN.to_stdlib() == logging.WARN
        assert LogLevel.ERROR.to_stdlib() == logging.ERROR

    def test_from_stdlib(self) -> None:
        assert LogLevel.from_stdlib(logging.DEBUG) == LogLevel.DEBUG
        assert LogLevel.from_stdlib(logging.INFO) == LogLevel.INFO
        assert LogLevel.from_stdlib(logging.WARNING) == LogLevel.WARN
        assert LogLevel.from_stdlib(logging.ERROR) == LogLevel.ERROR
        assert LogLevel.from_stdlib(logging.CRITICAL) == LogLevel.ERROR

    def test_from_stdlib_zero(self) -> None:
        assert LogLevel.from_stdlib(0) == LogLevel.DEBUG


# ======================================================================
# LoggerConfig
# ======================================================================


class TestLoggerConfig:
    def test_default_config(self) -> None:
        cfg = LoggerConfig()
        assert cfg.level == LogLevel.INFO
        assert cfg.output == "stderr"
        assert cfg.format == "json"
        assert cfg.extra_fields == {}

    def test_custom_config(self) -> None:
        cfg = LoggerConfig(
            level=LogLevel.DEBUG,
            output="stdout",
            format="json",
            extra_fields={"service": "my-agent"},
        )
        assert cfg.level == LogLevel.DEBUG
        assert cfg.extra_fields["service"] == "my-agent"


# ======================================================================
# StructuredLogger
# ======================================================================


class TestStructuredLogger:
    """Helper to create a logger that writes to a StringIO buffer."""

    @staticmethod
    def _make_logger(
        component: str = "test",
        level: LogLevel = LogLevel.DEBUG,
        extra_fields: dict | None = None,
    ) -> tuple[StructuredLogger, io.StringIO]:
        buf = io.StringIO()
        cfg = LoggerConfig(
            level=level,
            output="ignored",
            extra_fields=extra_fields or {},
        )
        log = StructuredLogger(component, config=cfg)
        # Replace handler with our StringIO handler
        log._stdlib.handlers.clear()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        log._stdlib.addHandler(handler)
        log._stdlib.setLevel(level.to_stdlib())
        return log, buf

    def _parse(self, buf: io.StringIO) -> dict:
        raw = buf.getvalue().strip()
        if not raw:
            return {}
        return json.loads(raw)

    # -- Basic logging ----------------------------------------------------

    def test_info_log(self) -> None:
        log, buf = self._make_logger()
        log.info("card_sent", message="Task dispatched")
        parsed = self._parse(buf)
        assert parsed["level"] == "INFO"
        assert parsed["event"] == "card_sent"
        assert parsed["component"] == "test"
        assert parsed["message"] == "Task dispatched"
        assert "timestamp" in parsed

    def test_debug_log(self) -> None:
        log, buf = self._make_logger()
        log.debug("debug_event")
        parsed = self._parse(buf)
        assert parsed["level"] == "DEBUG"
        assert parsed["event"] == "debug_event"

    def test_warn_log(self) -> None:
        log, buf = self._make_logger()
        log.warn("warning_event")
        parsed = self._parse(buf)
        assert parsed["level"] == "WARN"

    def test_error_log(self) -> None:
        log, buf = self._make_logger()
        log.error("error_event")
        parsed = self._parse(buf)
        assert parsed["level"] == "ERROR"

    def test_all_methods_emit(self) -> None:
        log, buf = self._make_logger()
        log.debug("d")
        log.info("i")
        log.warn("w")
        log.error("e")
        lines = [l for l in buf.getvalue().split("\n") if l.strip()]
        assert len(lines) == 4

    # -- Extra fields -----------------------------------------------------

    def test_extra_kwargs(self) -> None:
        log, buf = self._make_logger()
        log.info("with_extra", peer="agent-a", msg_count=42)
        parsed = self._parse(buf)
        assert parsed["peer"] == "agent-a"
        assert parsed["msg_count"] == 42

    def test_extra_fields_in_config(self) -> None:
        log, buf = self._make_logger(extra_fields={"app": "mesh", "env": "test"})
        log.info("config_extra")
        parsed = self._parse(buf)
        assert parsed["app"] == "mesh"
        assert parsed["env"] == "test"

    def test_per_call_extra_overrides_config(self) -> None:
        log, buf = self._make_logger(extra_fields={"app": "default"})
        log.info("override_test", app="custom")
        parsed = self._parse(buf)
        assert parsed["app"] == "custom"

    # -- Duration ---------------------------------------------------------

    def test_duration_ms(self) -> None:
        log, buf = self._make_logger()
        log.info("timed_op", duration_ms=150.5)
        parsed = self._parse(buf)
        assert parsed["duration_ms"] == 150.5

    def test_duration_rounding(self) -> None:
        log, buf = self._make_logger()
        log.info("precise", duration_ms=0.1234567)
        parsed = self._parse(buf)
        assert parsed["duration_ms"] == 0.123
        # Only 3 decimal places after rounding

    # -- Error handling ---------------------------------------------------

    def test_error_exception(self) -> None:
        log, buf = self._make_logger()
        try:
            raise ValueError("invalid input")
        except ValueError as exc:
            log.error("failed", error=exc)
        parsed = self._parse(buf)
        assert parsed["error"]["type"] == "ValueError"
        assert parsed["error"]["message"] == "invalid input"

    def test_error_str(self) -> None:
        log, buf = self._make_logger()
        log.error("failed", error="connection timeout")
        parsed = self._parse(buf)
        assert parsed["error"] == "connection timeout"

    def test_error_dict(self) -> None:
        log, buf = self._make_logger()
        log.error("failed", error={"code": 503, "detail": "unavailable"})
        parsed = self._parse(buf)
        assert parsed["error"]["code"] == 503
        assert parsed["error"]["detail"] == "unavailable"

    # -- Trace context integration ----------------------------------------

    def test_trace_context_injected(self) -> None:
        log, buf = self._make_logger()
        ctx = TraceProvider().new_context()
        with with_trace_context(ctx):
            log.info("traced_op")
        parsed = self._parse(buf)
        assert parsed["trace_id"] == ctx.trace_id
        assert parsed["span_id"] == ctx.span_id

    def test_no_trace_context_when_none(self) -> None:
        log, buf = self._make_logger()
        log.info("no_trace")
        parsed = self._parse(buf)
        assert "trace_id" not in parsed
        assert "span_id" not in parsed

    def test_trace_context_with_baggage(self) -> None:
        log, buf = self._make_logger()
        ctx = TraceProvider().new_context(baggage={"env": "staging"})
        with with_trace_context(ctx):
            log.info("baggage_test")
        parsed = self._parse(buf)
        assert parsed["trace_baggage"]["env"] == "staging"

    # -- Level filtering --------------------------------------------------

    def test_level_filtering_above_threshold(self) -> None:
        log, buf = self._make_logger(level=LogLevel.ERROR)
        log.info("should_not_appear")
        log.warn("should_not_appear")
        log.error("should_appear")
        parsed = self._parse(buf)
        assert parsed["level"] == "ERROR"
        assert parsed["event"] == "should_appear"

    def test_level_filtering_debug_allows_all(self) -> None:
        log, buf = self._make_logger(level=LogLevel.DEBUG)
        log.debug("d")
        log.info("i")
        log.warn("w")
        log.error("e")
        lines = [l for l in buf.getvalue().split("\n") if l.strip()]
        assert len(lines) == 4

    # -- Global configure -------------------------------------------------

    def test_global_configure(self) -> None:
        original_cfg = LoggerConfig(level=LogLevel.DEBUG)
        StructuredLogger.configure(original_cfg)
        log = StructuredLogger("global-test")
        assert log._config.level == LogLevel.DEBUG

    # -- File output ------------------------------------------------------

    def test_file_output(self) -> None:
        with tempfile.NamedTemporaryFile(mode="r", suffix=".log", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cfg = LoggerConfig(level=LogLevel.INFO, output=tmp_path)
            log = StructuredLogger("file-test", config=cfg)
            log.info("written_to_file")

            # Re-read and verify
            with open(tmp_path) as f:
                content = f.read().strip()
            parsed = json.loads(content)
            assert parsed["event"] == "written_to_file"
            assert parsed["component"] == "file-test"
        finally:
            os.unlink(tmp_path)

    # -- Component name validation ----------------------------------------

    def test_empty_component_raises(self) -> None:
        with pytest.raises(ValueError, match="component"):
            StructuredLogger("")

    # -- JSON output format -----------------------------------------------

    def test_output_is_json(self) -> None:
        log, buf = self._make_logger()
        log.info("json_test")
        raw = buf.getvalue().strip()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_unicode_content(self) -> None:
        log, buf = self._make_logger()
        log.info("chinese", message="你好世界")
        parsed = self._parse(buf)
        assert parsed["message"] == "你好世界"

    def test_non_serializable_value(self) -> None:
        log, buf = self._make_logger()

        class Custom:
            def __str__(self) -> str:
                return "custom_str"

        log.info("custom_obj", data=Custom())
        parsed = self._parse(buf)
        assert parsed["data"] == "custom_str"


# ======================================================================
# Performance / edge cases
# ======================================================================


class TestEdgeCases:
    def test_rapid_logs(self) -> None:
        """Ensure rapid logging produces valid JSON lines."""
        log, buf = TestStructuredLogger._make_logger()
        for i in range(50):
            log.info("batch", index=i)
        lines = [l for l in buf.getvalue().split("\n") if l.strip()]
        assert len(lines) == 50
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["index"] == i

    def test_trace_context_span_lifecycle(self) -> None:
        """Span ID should match the active context, not linger."""
        log, buf = TestStructuredLogger._make_logger()
        ctx = TraceProvider().new_context()

        with with_trace_context(ctx):
            log.info("inside")
        log.info("outside")

        lines = [l for l in buf.getvalue().split("\n") if l.strip()]
        inside = json.loads(lines[0])
        outside = json.loads(lines[1])

        assert inside["trace_id"] == ctx.trace_id
        assert "trace_id" not in outside

    def test_large_extra_fields(self) -> None:
        """Large extra fields should not break JSON serialisation."""
        log, buf = TestStructuredLogger._make_logger()
        big_val = "x" * 10_000
        log.info("big_extra", payload=big_val)
        parsed = json.loads(buf.getvalue().strip())
        assert len(parsed["payload"]) == 10_000
