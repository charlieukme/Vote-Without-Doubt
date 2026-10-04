"""
Base Model - Phase 1
Vote Without Doubt - Backend
"""

from datetime import datetime
from app.extensions import db


class BaseModel(db.Model):
    """
    Base model with common fields
    """
    __abstract__ = True
    
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, 
                          onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.String(100), nullable=True)
    updated_by = db.Column(db.String(100), nullable=True)
    
    def to_dict(self) -> dict:
        """Convert model to dictionary"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
