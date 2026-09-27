"""EM-109: Ortam konfigürasyonu ve gözlemlenebilirlik testleri."""
import json
import logging

import pytest

from src.config.settings import (
    DemoConfig,
    DevelopmentConfig,
    ProductionConfig,
    TestingConfig,
    get_config,
)
from src.services.observability import (
    JsonFormatter,
    setup_logging,
    timed_pipeline,
)


# ---------------------------------------------------------------------------
# Config factory tests
# ---------------------------------------------------------------------------


class TestGetConfig:
    """get_config() environment factory."""

    def test_returns_testing_config(self) -> None:
        assert get_config("testing") is TestingConfig

    def test_returns_demo_config(self) -> None:
        assert get_config("demo") is DemoConfig

    def test_returns_development_config(self) -> None:
        assert get_config("development") is DevelopmentConfig

    def test_returns_production_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Production boot guard requires a real server-side database URL.
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/wildfire")
        assert get_config("production") is ProductionConfig

    def test_production_guard_rejects_missing_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="must be set explicitly"):
            get_config("production")

    def test_production_guard_rejects_sqlite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "sqlite:///wildfire.db")
        with pytest.raises(RuntimeError, match="refuses a SQLite"):
            get_config("production")

    def test_unknown_falls_back_to_development(self) -> None:
        assert get_config("nonexistent") is DevelopmentConfig

    def test_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "demo")
        assert get_config() is DemoConfig

    def test_case_insensitive(self) -> None:
        assert get_config("DEMO") is DemoConfig
        assert get_config("Testing") is TestingConfig


class TestDemoConfig:
    """DemoConfig specifics."""

    def test_no_external_api_keys(self) -> None:
        assert DemoConfig.FIRMS_API_KEY == ""
        assert DemoConfig.OPENWEATHER_API_KEY == ""

    def test_sqlite_database(self) -> None:
        assert "sqlite" in DemoConfig.DATABASE_URL

    def test_memory_celery(self) -> None:
        assert DemoConfig.CELERY_BROKER_URL == "memory://"


# ---------------------------------------------------------------------------
# Observability tests
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    """JSON log formatter output."""

    def test_formats_record(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["msg"] == "hello"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert "ts" in parsed

    def test_includes_extras(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="svc",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="stale",
            args=(),
            exc_info=None,
        )
        record.extras = {"source": "FIRMS", "age_min": 45}  # type: ignore[attr-defined]
        parsed = json.loads(formatter.format(record))
        assert parsed["source"] == "FIRMS"
        assert parsed["age_min"] == 45


class TestSetupLogging:
    """setup_logging() configures root logger."""

    def test_adds_handler(self) -> None:
        setup_logging("DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) >= 1
        # Cleanup
        for h in root.handlers[:]:
            root.removeHandler(h)


class TestTimedPipeline:
    """@timed_pipeline decorator."""

    def test_successful_call(self) -> None:
        @timed_pipeline
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_exception_propagates(self) -> None:
        @timed_pipeline
        def fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()
