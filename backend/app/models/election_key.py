"""
Election pseudonym keys - Phase 8 (ballot plane)
"""

from app.extensions import db
from app.models.base import BaseModel


class ElectionPseudonymKey(BaseModel):
    __tablename__ = 'election_pseudonym_keys'
    __table_args__ = {'mysql_engine': 'InnoDB', 'extend_existing': True}
    
    election_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    key_hash = db.Column(db.String(128), nullable=False)
    key_ciphertext = db.Column(db.Text, nullable=False)
    
    def __repr__(self):
        return f"<ElectionKey election={self.election_id}>"
