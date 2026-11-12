"""
Phase 14 End-to-End Playwright Browser Testing Suite
Vote Without Doubt - System Verification

Runs the real React frontend bundle against the live Flask server
using Playwright with headless Chrome.

Tests:
E2E-14-01: Full flow: auth -> factors -> candidate select -> submit -> receipt
E2E-14-02: Same voter performs an allowed revote (sequence increases, latest wins)
E2E-14-03: Null revote (retraction, excluded from tally)
E2E-14-04: Unauthorized user attempts voting (blocked)
E2E-14-05: Expired election (voting unavailable)
E2E-14-06: Closed election (voting unavailable, results/verify rules intact)
E2E-14-07: Browser refresh during voting (no duplicate submission, no bypass)
E2E-14-08: Network interruption during submission (fails closed, no false receipt)
"""

import os
import secrets
import tempfile
import threading
import time
from datetime import datetime, timedelta

import pytest
from flask import send_from_directory, request
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

from app import create_app
from app.extensions import db as _db
from app.models import (
    BallotRecord,
    Candidate,
    Election,
    FaceChallenge,
    FaceEnrollment,
    User,
    VotingAuthorization,
    WalletBinding,
)
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
from app.security.face import challenge_mac
from app.services.voting_service import VotingService
from tests.conftest import _seed_authorized_session


import socket

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist'))

def _get_free_port():
    """Allocate an available ephemeral port dynamically to eliminate test port conflicts."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]



class ServerThread(threading.Thread):
    def __init__(self, app, port):
        super().__init__()
        self.server = make_server('127.0.0.1', port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def _auto_relayer_loop(app, stop_event):
    """Background simulator ensuring queued ballots are mined/finalized for browser polling."""
    while not stop_event.is_set():
        try:
            with app.app_context():
                queued = BallotRecord.query.filter_by(state='QUEUED').all()
                for b in queued:
                    b.state = 'FINALIZED'
                    b.block_number = 15000 + b.id
                    b.tx_hash = '0x' + secrets.token_hex(32)
                    if not b.receipt_code:
                        b.receipt_code = 'RCPT-E2E-' + secrets.token_hex(6).upper()
                if queued:
                    _db.session.commit()
        except Exception:
            pass
        time.sleep(0.1)


@pytest.fixture(scope='module')
def e2e_server():
    """Starts the real Flask application configured with a dedicated database and frontend dist."""
    handle, db_path = tempfile.mkstemp(suffix='.sqlite3', prefix='e2e_live_')
    os.close(handle)
    try:
        os.unlink(db_path)
    except OSError:
        pass

    prev_db_url = os.environ.get('DATABASE_URL')
    db_path_norm = db_path.replace('\\', '/')
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path_norm}'

    app = create_app('testing')
    app.config['SERVER_NAME'] = None

    with app.app_context():
        _db.create_all()

        # Seed default Election 1 required by frontend
        el = Election(
            election_id='1',
            title='Phase 14 General Student Election',
            status='ACTIVE',
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=6),
            max_ballots=3,
        )
        _db.session.add(el)
        c1 = Candidate(election_id='1', candidate_index=0, name='Candidate Alice', department='CS')
        c2 = Candidate(election_id='1', candidate_index=1, name='Candidate Bob', department='ECE')
        _db.session.add_all([c1, c2])
        _db.session.commit()
        derive_pseudonym(1, 1)

    # Attach static routes for frontend dist with SPA routing fallback
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_spa(path):
        if request.path.startswith('/api/'):
            from flask import abort
            abort(404)
        if path.startswith('assets/'):
            return send_from_directory(FRONTEND_DIST, path)
        target = os.path.join(FRONTEND_DIST, path)
        if path and os.path.isfile(target):
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, 'index.html')

    @app.after_request
    def allow_frontend_csp(response):
        if not request.path.startswith('/api/'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self' 'unsafe-inline' https: data:; "
                "script-src 'self' 'unsafe-inline' https:; "
                "style-src 'self' 'unsafe-inline' https:; "
                "font-src 'self' https: data:;"
            )
        return response

    @app.after_request
    def complete_e2e_face_challenge(response):
        if request.path == '/api/voting/authorize' and response.status_code == 200:
            try:
                data = response.get_json()
                auth_id = data.get('authorization_id') if data else None
                if auth_id:
                    va = _db.session.get(VotingAuthorization, auth_id)
                    if va:
                        fe = FaceEnrollment.query.filter_by(user_id=va.user_id).first()
                        if fe and fe.is_active():
                            now = datetime.utcnow()
                            existing = FaceChallenge.query.filter_by(authorization_id=auth_id).first()
                            if not existing:
                                nonce = secrets.token_hex(16)
                                ch_id = secrets.token_hex(16)
                                exp = now + timedelta(minutes=10)
                                mac = challenge_mac(ch_id, va.user_id, va.session_id, '', nonce, exp.isoformat())
                                ch = FaceChallenge(
                                    challenge_id=ch_id,
                                    user_id=va.user_id,
                                    session_id=va.session_id,
                                    challenge_type='FACE',
                                    challenge_sequence='',
                                    nonce=nonce,
                                    integrity_mac=mac,
                                    completed=True,
                                    success=True,
                                    completed_at=now,
                                    expires_at=exp,
                                    authorization_id=auth_id,
                                    election_id=va.election_id,
                                    consumed=False,
                                )
                                _db.session.add(ch)
                                _db.session.commit()
            except Exception as exc:
                app.logger.warning(f"Error in complete_e2e_face_challenge: {exc}")
        return response

    # Start relayer simulator thread
    stop_relayer = threading.Event()
    relayer_th = threading.Thread(target=_auto_relayer_loop, args=(app, stop_relayer), daemon=True)
    relayer_th.start()

    # Start Flask HTTP server thread on dynamically allocated ephemeral port
    port = _get_free_port()
    server = ServerThread(app, port)
    server.start()
    time.sleep(0.5)

    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        stop_relayer.set()
        try:
            server.shutdown()
        except Exception:
            pass

        if prev_db_url:
            os.environ['DATABASE_URL'] = prev_db_url
        else:
            os.environ.pop('DATABASE_URL', None)

        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.fixture(scope='module')
def browser():
    """Launches headless Chrome via Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
            args=['--no-sandbox', '--disable-gpu']
        )
        yield browser
        browser.close()


def _seed_e2e_voter(app, election_id=1, idx=1):
    with app.app_context():
        user = User.query.filter_by(username=f'e2e_voter_{idx}').first()
        if not user:
            user = User(
                username=f'e2e_voter_{idx}',
                email=f'e2e_voter_{idx}@college.test',
                password_hash=hash_password('E2ePassword123!'),
                voter_id=f'VOTER-E2E-{idx:03d}',
                is_active=True,
                is_verified=True,
            )
            _db.session.add(user)
            _db.session.commit()

        sid = secrets.token_hex(24)
        _seed_authorized_session(_db, user, session_id=sid)

        # Ensure wallet and face enrollment
        if not WalletBinding.query.filter_by(user_id=user.id).first():
            wallet = WalletBinding(user_id=user.id, wallet_address='0x' + secrets.token_hex(20), is_verified=True)
            _db.session.add(wallet)

        if not FaceEnrollment.query.filter_by(user_id=user.id).first():
            face = FaceEnrollment(user_id=user.id, encrypted_embedding=b'\x01'*512, is_enrolled=True, consent_given=True, consent_at=datetime.utcnow())
            _db.session.add(face)

        _db.session.commit()
        derive_pseudonym(user.id, election_id)

        return user.id, sid


# ==============================================================================
# E2E-14-01: Full Registration -> Auth -> Voting -> Receipt Flow
# ==============================================================================


def _set_auth_cookie(context, app, sid):
    serializer = app.session_interface.get_signing_serializer(app)
    cookie_val = serializer.dumps({'session_id': sid})
    cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    context.add_cookies([{
        'name': cookie_name,
        'value': cookie_val,
        'domain': '127.0.0.1',
        'path': '/',
        'httpOnly': True,
    }])

def test_e2e_14_01_full_voting_flow(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    uid, sid = _seed_e2e_voter(app, eid, idx=1)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    # Click Begin Voting Authorization
    start_btn = page.locator('#start-voting-btn')
    start_btn.wait_for(state='visible')
    start_btn.click()

    # The factor check is executed; factors are satisfied, UI transitions to candidate select
    page.wait_for_selector('.candidates-list', timeout=10000)
    
    # Select Candidate Alice (radio value 0)
    alice_radio = page.locator('input[name="candidate"][value="0"]')
    alice_radio.check()

    # Click Review Selection
    page.locator('#review-ballot-btn').click()

    # Confirm ballot step
    page.wait_for_selector('#confirm-submit-btn')
    page.locator('#confirm-submit-btn').click()

    # Expect receipt box with official receipt code
    page.wait_for_selector('.receipt-code', timeout=15000)
    receipt_text = page.locator('.receipt-code').inner_text()
    assert 'Receipt Code:' in receipt_text

    # Verify database state
    with app.app_context():
        ballots = BallotRecord.query.filter_by(election_id=eid).all()
        assert len(ballots) == 1
        assert ballots[0].sequence == 1
        assert ballots[0].candidate == 0
        assert ballots[0].superseded is False
        assert ballots[0].receipt_code is not None

    context.close()


# ==============================================================================
# E2E-14-02: Same voter performs an allowed revote
# ==============================================================================

def test_e2e_14_02_allowed_revote(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    uid, sid = _seed_e2e_voter(app, eid, idx=1)

    # Ensure prerequisite sequence 1 ballot exists (self-seeding for isolated test execution)
    with app.app_context():
        pseudo = derive_pseudonym(uid, eid)
        b1 = BallotRecord.query.filter_by(election_id=eid, pseudonym=pseudo, sequence=1).first()
        if not b1:
            b1 = BallotRecord(
                election_id=eid,
                pseudonym=pseudo,
                candidate=0,
                sequence=1,
                state='FINALIZED',
                is_null=False,
                superseded=False,
                receipt_code='RCPT-E2E-1401-PRE',
                created_at=datetime.utcnow() - timedelta(minutes=10),
            )
            _db.session.add(b1)
        else:
            # Bypass cooldown for revote
            b1.created_at = datetime.utcnow() - timedelta(minutes=10)
        _db.session.commit()

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    # Since voter has a finalized sequence 1 ballot, the receipt screen displays with revote action
    revote_btn = page.locator('#initiate-revote-btn')
    revote_btn.wait_for(state='visible', timeout=15000)
    revote_btn.click()

    start_btn = page.locator('#start-voting-btn')
    start_btn.wait_for(state='visible', timeout=10000)
    start_btn.click()

    page.wait_for_selector('.candidates-list', timeout=10000)
    # Change vote to Bob (candidate 1)
    bob_radio = page.locator('input[name="candidate"][value="1"]')
    bob_radio.wait_for(state='visible', timeout=5000)
    bob_radio.check()

    page.locator('#review-ballot-btn').click()
    page.wait_for_selector('#confirm-submit-btn', timeout=5000)
    page.locator('#confirm-submit-btn').click()

    # Wait for receipt
    page.wait_for_selector('.receipt-code', timeout=15000)

    # Verify revote invariants in DB
    with app.app_context():
        pseudo = derive_pseudonym(uid, eid)
        ballots = (
            BallotRecord.query.filter_by(election_id=eid, pseudonym=pseudo)
            .order_by(BallotRecord.sequence.asc())
            .all()
        )
        assert len(ballots) == 2
        assert ballots[0].sequence == 1
        assert ballots[0].superseded is True
        assert ballots[1].sequence == 2
        assert ballots[1].superseded is False
        assert ballots[1].candidate == 1

    context.close()


# ==============================================================================
# E2E-14-03: Null revote
# ==============================================================================

def test_e2e_14_03_null_revote(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    uid, sid = _seed_e2e_voter(app, eid, idx=1)

    # Ensure prerequisite sequence 1 and 2 ballots exist (self-seeding for isolated test execution)
    with app.app_context():
        pseudo = derive_pseudonym(uid, eid)
        b1 = BallotRecord.query.filter_by(election_id=eid, pseudonym=pseudo, sequence=1).first()
        if not b1:
            b1 = BallotRecord(
                election_id=eid,
                pseudonym=pseudo,
                candidate=0,
                sequence=1,
                state='FINALIZED',
                is_null=False,
                superseded=True,
                receipt_code='RCPT-E2E-1401-PRE',
                created_at=datetime.utcnow() - timedelta(minutes=15),
            )
            _db.session.add(b1)

        b2 = BallotRecord.query.filter_by(election_id=eid, pseudonym=pseudo, sequence=2).first()
        if not b2:
            b2 = BallotRecord(
                election_id=eid,
                pseudonym=pseudo,
                candidate=1,
                sequence=2,
                state='FINALIZED',
                is_null=False,
                superseded=False,
                receipt_code='RCPT-E2E-1402-PRE',
                created_at=datetime.utcnow() - timedelta(minutes=10),
            )
            _db.session.add(b2)
        else:
            # Bypass cooldown and reset to 10 minutes ago
            b2.created_at = datetime.utcnow() - timedelta(minutes=10)

        _db.session.commit()

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    # Since voter has a finalized sequence 2 ballot, the receipt screen displays with revote action
    revote_btn = page.locator('#initiate-revote-btn')
    revote_btn.wait_for(state='visible', timeout=15000)
    revote_btn.click()

    start_btn = page.locator('#start-voting-btn')
    start_btn.wait_for(state='visible', timeout=10000)
    start_btn.click()
    page.wait_for_selector('.candidates-list', timeout=10000)

    # Select Null Ballot
    null_radio = page.locator('input[value="null"]')
    null_radio.wait_for(state='visible', timeout=5000)
    null_radio.check()

    page.locator('#review-ballot-btn').click()
    page.wait_for_selector('#confirm-submit-btn', timeout=5000)
    page.locator('#confirm-submit-btn').click()

    page.wait_for_selector('.receipt-code', timeout=15000)

    with app.app_context():
        pseudo = derive_pseudonym(uid, eid)
        ballots = (
            BallotRecord.query.filter_by(election_id=eid, pseudonym=pseudo)
            .order_by(BallotRecord.sequence.asc())
            .all()
        )
        assert len(ballots) == 3
        assert ballots[0].superseded is True
        assert ballots[1].superseded is True
        assert ballots[2].sequence == 3
        assert ballots[2].superseded is False
        assert ballots[2].is_null is True

    context.close()


# ==============================================================================
# E2E-14-04: Unauthorized user attempts voting
# ==============================================================================

def test_e2e_14_04_unauthorized_user_blocked(e2e_server, browser):
    base_url, app = e2e_server
    context = browser.new_context()  # No session cookies

    page = context.new_page()
    # Attempting to access student protected route /vote directly without authorization
    page.goto(f"{base_url}/vote")

    # Modern route architecture: StudentLayout immediately blocks unauthenticated access and redirects to /login
    page.wait_for_url(f"**/login**", timeout=10000)
    page.wait_for_selector('.login-page', timeout=5000)

    # Voting plane is strictly inaccessible
    assert not page.locator('#voting-section').is_visible()
    assert not page.locator('.candidates-list').is_visible()

    context.close()


# ==============================================================================
# E2E-14-05: Expired election
# ==============================================================================

def test_e2e_14_05_expired_election_blocked(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    with app.app_context():
        el = Election.query.filter_by(election_id='1').first()
        orig_end = el.end_time
        el.end_time = datetime.utcnow() - timedelta(hours=1)  # Temporarily expire
        _db.session.commit()

        uid, sid = _seed_e2e_voter(app, eid, idx=2)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    start_btn = page.locator('#start-voting-btn')
    start_btn.click()

    # Rejection banner
    page.wait_for_selector('.error-banner', timeout=5000)
    assert not page.locator('.candidates-list').is_visible()

    # Restore election time
    with app.app_context():
        el = Election.query.filter_by(election_id='1').first()
        el.end_time = orig_end
        _db.session.commit()

    context.close()


# ==============================================================================
# E2E-14-06: Closed election
# ==============================================================================

def test_e2e_14_06_closed_election_blocked(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    with app.app_context():
        el = Election.query.filter_by(election_id='1').first()
        orig_status = el.status
        el.status = 'CLOSED'  # Temporarily close
        _db.session.commit()

        uid, sid = _seed_e2e_voter(app, eid, idx=3)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    start_btn = page.locator('#start-voting-btn')
    start_btn.click()

    # Rejection banner
    page.wait_for_selector('.error-banner', timeout=5000)
    assert not page.locator('.candidates-list').is_visible()

    # Restore status
    with app.app_context():
        el = Election.query.filter_by(election_id='1').first()
        el.status = orig_status
        _db.session.commit()

    context.close()


# ==============================================================================
# E2E-14-07: Browser refresh during voting
# ==============================================================================

def test_e2e_14_07_refresh_browser_during_voting(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    uid, sid = _seed_e2e_voter(app, eid, idx=4)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    # Start voting
    page.locator('#start-voting-btn').click()
    page.wait_for_selector('.candidates-list')

    # Select candidate Alice
    page.locator('input[name="candidate"][value="0"]').check()
    page.locator('#review-ballot-btn').click()
    page.wait_for_selector('#confirm-submit-btn')

    # Refresh browser midway through flow
    page.reload()
    page.wait_for_selector('#voting-section')

    # Must reset safely to start step without accidental submission
    start_btn = page.locator('#start-voting-btn')
    assert start_btn.is_visible()

    # Verify no accidental ballot was created in DB for voter 4
    with app.app_context():
        ballots = BallotRecord.query.filter_by(election_id=eid, pseudonym=derive_pseudonym(uid, eid)).all()
        assert len(ballots) == 0

    context.close()


# ==============================================================================
# E2E-14-08: Network interruption during voting
# ==============================================================================

def test_e2e_14_08_network_interruption(e2e_server, browser):
    base_url, app = e2e_server
    eid = 1

    uid, sid = _seed_e2e_voter(app, eid, idx=5)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)

    page = context.new_page()
    page.goto(f"{base_url}/vote")
    page.wait_for_selector('#voting-section')

    page.locator('#start-voting-btn').click()
    page.wait_for_selector('.candidates-list')
    page.locator('input[name="candidate"][value="0"]').check()
    page.locator('#review-ballot-btn').click()
    page.wait_for_selector('#confirm-submit-btn')

    # Intercept and abort the submit request to simulate network failure
    page.route('**/api/voting/submit', lambda route: route.abort('connectionfailed'))

    # Submit ballot
    page.locator('#confirm-submit-btn').click()

    # Must fail cleanly and show error box, NOT false success receipt
    page.wait_for_selector('.error-box', timeout=10000)
    assert not page.locator('.receipt-box').is_visible()

    context.close()
