"""Temel Model Sınıfları"""
from sqlalchemy import Column, DateTime, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class TimestampMixin:
    """Timestamp kolonları ekleyen mixin"""
    created_at = db.Column(db.DateTime, default=func.now())
    updated_at = db.Column(db.DateTime, default=func.now(), onupdate=func.now())

class BaseModel(db.Model, TimestampMixin):
    """Temel model sınıfı"""
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
