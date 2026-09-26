#!/usr/bin/env python3
"""EM-109: Demo ortamı veritabanı tohumlama betiği.

Docker compose demo profilinde konteyner başlangıcında çalışır.
SQLite'a tablo şemasını + sentetik senaryo verisini yazar.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database  # noqa: E402
from src.services.synthetic import (  # noqa: E402
    build_dataset,
    persist_dataset,
    record_run,
)


def main() -> None:
    """Seed the demo database with base tables + synthetic scenario."""
    db_path = os.getenv("DATABASE_URL", "sqlite:///instance/wildfire-demo.db")
    seed = int(os.getenv("DEMO_SYNTHETIC_SEED", "7"))
    preset = os.getenv("DEMO_SYNTHETIC_PRESET", "standart")

    # Ensure SQLite parent directory exists (CI-safe)
    if db_path.startswith("sqlite:///"):
        rel = db_path.replace("sqlite:///", "")
        parent = os.path.dirname(rel)
        if parent:
            os.makedirs(parent, exist_ok=True)

    print(f"[demo_seed] DB: {db_path}")
    database = Database(db_path)
    database.create_all()

    # Generate synthetic scenario (EM-104)
    dataset = build_dataset(seed, preset=preset)
    with database.session() as session:
        counts = persist_dataset(session, dataset)
        record_run(session, dataset, persisted=True, preset=preset)

    print(
        f"[demo_seed] Sentetik senaryo: seed={seed} preset={preset} "
        f"tag={dataset['meta']['scenario_tag']} counts={counts}"
    )
    print("[demo_seed] Tamamlandı.")


if __name__ == "__main__":
    main()
