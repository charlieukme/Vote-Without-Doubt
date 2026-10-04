"""
Test models foundation - Phase 1
Identity and Ballot planes separation
"""

import pytest
from app import create_app
from app.extensions import db
from app.models import VoterIdentity, Ballot, Election, BaseModel


def test_models_can_be_imported():
    """Test models import successfully"""
    assert VoterIdentity is not None
    assert Ballot is not None
    assert Election is not None
    assert BaseModel is not None


def test_voter_identity_creation():
    """Test VoterIdentity model structure (identity plane)"""
    vi = VoterIdentity(
        voter_id='V001',
        full_name='Test Voter',
        email='test@example.com',
        is_eligible=True,
        is_registered=False
    )
    assert vi.voter_id == 'V001'
    assert vi.full_name == 'Test Voter'
    assert vi.email == 'test@example.com'
    assert vi.is_eligible is True


def test_ballot_creation():
    """Test Ballot model structure (ballot plane)"""
    ballot = Ballot(
        ballot_id='B001',
        election_id='E001',
        ballot_state='QUEUED'
    )
    assert ballot.ballot_id == 'B001'
    assert ballot.election_id == 'E001'
    assert ballot.ballot_state == 'QUEUED'


def test_election_creation():
    """Test Election model structure"""
    election = Election(
        election_id='E001',
        title='Test Election',
        status='DRAFT'
    )
    assert election.election_id == 'E001'
    assert election.title == 'Test Election'
    assert election.status == 'DRAFT'


def test_ballot_plane_separation():
    """
    Verify ballot plane has no direct identity reference
    Enforces identity/ballot separation design principle
    """
    ballot = Ballot(ballot_id='B002', election_id='E001')
    # Ballot should not have voter_id field directly (separation)
    assert not hasattr(ballot, 'voter_id') or ballot.__table__.c.get('voter_id') is None
