#!/usr/bin/env python
"""Veritabanı kurulum scripti"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import create_app, db

def setup():
    """Veritabanını kur"""
    app = create_app()
    with app.app_context():
        print("Veritabanı tabloları oluşturuluyor...")
        db.create_all()
        print("✓ Kurulum tamamlandı!")

if __name__ == '__main__':
    setup()
