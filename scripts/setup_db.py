#!/usr/bin/env python
"""Veritabanı kurulum scripti"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import ProductionConfig
from src.database import Database


def setup():
    """Veritabanını kur"""
    database = Database(ProductionConfig.DATABASE_URL)
    print("Veritabanı tabloları oluşturuluyor...")
    database.create_all()
    print("✓ Kurulum tamamlandı!")


if __name__ == "__main__":
    setup()
