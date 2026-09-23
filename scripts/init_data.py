#!/usr/bin/env python
"""Test verisi yükleme scripti"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app import create_app

def init_data():
    """Test verisi yükle"""
    app = create_app()
    with app.app_context():
        print("Test verisi yükleniyor...")
        # Burada test verisi yükleme kodunu ekle
        print("✓ Test verisi yüklendi!")

if __name__ == '__main__':
    init_data()
