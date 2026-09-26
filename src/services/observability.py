"""EM-109: Yapılandırılmış loglama ve gözlemlenebilirlik altyapısı.

Uygulama genelinde JSON-format log çıktısı sağlar. Production'da log
agregatörlerine (ELK, Datadog, CloudWatch) doğrudan beslenebilir.

Kullanım:
    from src.services.observability import get_logger
    log = get_logger(__name__)
    log.info("sync_completed", source="FIRMS", records=42)
"""
import json
import logging
import os
import sys
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach structured extras if present
        extras = getattr(record, "extras", None)
        if extras:
            entry.update(extras)
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None) -> None:
    """Configure root logger with JSON output (one-line structured logs).

    Called once at application startup. Subsequent calls are no-ops unless
    the level changes.
    """
    raw: str = level if level is not None else os.getenv("LOG_LEVEL", "INFO")
    log_level = raw.upper()
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers to avoid duplicates on reload
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (convenience wrapper)."""
    return logging.getLogger(name)


class StructuredAdapter(logging.LoggerAdapter):  # type: ignore[type-arg]
    """Logger adapter that injects structured context into every message."""

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, dict[str, Any]]:
        extras = dict(self.extra or {})
        extras.update(kwargs.pop("extras", {}))
        kwargs["extra"] = {"extras": extras}
        return msg, kwargs


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Log a structured event with key-value fields."""
    logger.log(level, event, extra={"extras": fields})


# ---------------------------------------------------------------------------
# Pipeline timing decorator (observability for sync jobs)
# ---------------------------------------------------------------------------


def timed_pipeline(func):  # type: ignore[no-untyped-def]
    """Decorator that logs execution time for pipeline/sync functions."""
    import functools  # pylint: disable=import-outside-toplevel

    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            log_event(
                logging.getLogger(func.__module__),
                "pipeline_completed",
                function=func.__name__,
                duration_s=round(elapsed, 3),
                status="success",
            )
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - start
            log_event(
                logging.getLogger(func.__module__),
                "pipeline_failed",
                level=logging.ERROR,
                function=func.__name__,
                duration_s=round(elapsed, 3),
                status="error",
                error=str(exc),
            )
            raise

    return wrapper
