"""SQLAlchemy database factory independent of any web framework."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


class Database:
    """Own an engine and session factory for one application environment."""

    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
        if url.startswith("sqlite") and ":memory:" in url:
            engine_options["poolclass"] = StaticPool
        self.engine = create_engine(url, **engine_options)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    def create_all(self) -> None:
        """Create all registered tables."""
        Base.metadata.create_all(self.engine)

    def reset_all(self) -> None:
        """Drop then recreate every registered table (clean demo/CI state).

        Only the tables whose models are imported into :data:`Base` are
        affected; callers that need a *complete* reset must import the model
        package first (``import src.models``) so the metadata is populated.
        """
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a transactional session and close it after use."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
