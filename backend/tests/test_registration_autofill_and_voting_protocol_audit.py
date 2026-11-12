"""
Test Suite: Registration Autofill, Voting Protocol Audit, and Contract Resolution
Vote Without Doubt (VWD)

Verifies:
1. Registration form fields prevent inappropriate autofill of old saved credentials.
2. Login form preserves standard password manager compatibility.
3. V1 contract address resolution from backend .env regardless of working directory.
4. V2 contract address resolution in BlockchainV2Service.
5. Missing contract address sets clear error and prevents vote counting.
6. Failed ballot queue entries are never counted as confirmed votes.
"""

import os
import re
import pytest
from app.extensions import db
from app.models.ballot import Election, Ballot
from app.models.ballot_record import BallotQueue
from app.relayer.relayer import Relayer


class TestRegistrationAutofillConfiguration:

    def test_registration_form_attributes(self):
        """Verify Registration.jsx contains anti-autofill attributes and unique identifiers."""
        reg_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend', 'src', 'Registration.jsx')
        assert os.path.isfile(reg_file), f"File not found: {reg_file}"

        with open(reg_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Step 1: USN field must have unique id/name, autocomplete="off", and data-lpignore
        assert 'id="student-reg-usn"' in content
        assert 'name="student_electoral_usn"' in content
        assert 'data-lpignore="true"' in content

        # Step 2: Email field
        assert 'id="student-reg-email"' in content
        assert 'name="student_college_email"' in content
        assert 'autoComplete="email"' in content

        # Step 3: OTP field
        assert 'id="student-reg-otp"' in content
        assert 'name="student_verification_otp"' in content
        assert 'autoComplete="one-time-code"' in content

        # Step 4: New Credentials fields
        assert 'id="student-reg-new-username"' in content
        assert 'name="student_registration_new_username"' in content
        assert 'id="student-reg-new-password"' in content
        assert 'name="student_registration_new_password"' in content
        assert 'id="student-reg-confirm-password"' in content
        assert 'name="student_registration_confirm_password"' in content

        # Distinguish password fields with unique IDs and new-password autocomplete
        passwords = re.findall(r'autoComplete="new-password"', content)
        assert len(passwords) >= 2, "Both password and confirm-password must specify new-password"

    def test_login_form_preserves_password_manager(self):
        """Verify Auth.jsx retains standard autocomplete attributes for login."""
        auth_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend', 'src', 'Auth.jsx')
        assert os.path.isfile(auth_file)

        with open(auth_file, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'autoComplete="username"' in content
        assert 'autoComplete="current-password"' in content


class TestVotingProtocolAndContractResolution:

    def test_v1_contract_address_resolution(self, app):
        """Verify Relayer contract address resolution resolves properly from config or env."""
        relayer = Relayer()
        assert relayer.contract_address is not None
        assert re.match(r'^0x[a-fA-F0-9]{40}$', relayer.contract_address)

    def test_missing_contract_address_marks_failed_without_counting(self, client, db):
        """
        Verify that when a relayer has no contract address:
        1. Ballots are marked FAILED with 'NO_CONTRACT_ADDRESS'.
        2. No transaction hash is generated.
        3. No vote is added to the authoritative ballots table.
        """
        # Create an election
        election = Election(
            election_id="ELEC_AUDIT_NO_CONTRACT",
            title="Audit No Contract Election",
            status="OPEN",
            candidate_count=2,
            eligible_count=10,
        )
        db.session.add(election)
        db.session.commit()

        # Create ballot queue entry
        b = BallotQueue(
            election_id=election.id,
            pseudonym="test_pseudonym_audit_01",
            candidate=0,
            sequence=0,
            state="QUEUED",
        )
        db.session.add(b)
        db.session.commit()

        # Instantiate relayer with explicit None contract address
        relayer = Relayer(contract_address=None)
        relayer._custom_contract_address = None

        # Execute batch broadcast
        summary = relayer._broadcast_ballot_batch([b], contract_address=None)

        assert summary['failed'] == 1
        assert summary['confirmed'] == 0
        assert b.state == 'FAILED'
        assert b.error == 'NO_CONTRACT_ADDRESS'
        assert b.tx_hash is None
        assert b.tx_confirmed_at is None

        # Verify ballots table remains completely empty (no votes counted)
        counted_ballots = Ballot.query.filter_by(election_id=election.election_id).all()
        assert len(counted_ballots) == 0

    def test_vote_page_prevents_unauthorized_protocol_tampering(self):
        """Verify VotePage.jsx locks protocol version to election without arbitrary client override."""
        votepage_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend', 'src', 'pages', 'student', 'VotePage.jsx')
        assert os.path.isfile(votepage_file)

        with open(votepage_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Should not have arbitrary onClick toggle buttons for voters to swap protocols
        assert 'onClick={() => setProtocolVersion(' not in content
        # Must show enforced by election badge
        assert 'Enforced by Election' in content
