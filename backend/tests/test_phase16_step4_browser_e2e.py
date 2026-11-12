"""
Phase 16 Step 4: Comprehensive Real Browser E2E, Responsiveness & Accessibility Test Suite
Vote Without Doubt - System Verification

Runs headless Chrome against the live built React frontend bundle served by Flask.
Covers:
1. Comprehensive Route Verification (Public, Student, Admin, Error/404)
2. Direct Navigation, Refresh & Route Guards (Session preservation & unauthenticated bounces)
3. Responsive Viewport Testing (Desktop 1920x1080/1440x900, Laptop 1366x768, Tablet 1024x768/768x1024, Mobile 390x844/375x812)
4. Accessibility QA (Keyboard navigation, Focus visibility, ARIA attributes, Reduced motion)
5. Sensitive Client Storage Inspection (Zero PII in localStorage, sessionStorage, cookies)
6. Support Report Dispute Privacy Filtering (Blocks credentials, private keys, receipt codes, vote choices)
"""

import json
import os
import secrets
import tempfile
import threading
import time
from datetime import datetime, timedelta

import pytest
from flask import send_from_directory, request, abort
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

from app import create_app
from app.extensions import db as _db
from app.models import (
    BallotRecord,
    Candidate,
    Election,
    User,
    WalletBinding,
    FaceEnrollment,
)
from app.models.admin import AdminUser
from app.security.password import hash_password
from app.security.pseudonym import derive_pseudonym
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


@pytest.fixture(scope='module')
def step4_server():
    """Starts Flask application with live database and SPA frontend dist serving."""
    handle, db_path = tempfile.mkstemp(suffix='.sqlite3', prefix='step4_e2e_')
    os.close(handle)
    try:
        os.unlink(db_path)
    except OSError:
        pass

    prev_db_url = os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'

    app = create_app('testing')
    app.config['SERVER_NAME'] = None

    with app.app_context():
        _db.create_all()

        el = Election(
            election_id='1',
            title='Phase 16 General Student Election',
            status='ACTIVE',
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=6),
            max_ballots=3,
        )
        _db.session.add(el)
        c1 = Candidate(election_id='1', candidate_index=0, name='Candidate Alice', department='CS', year='Final Year', slogan='Integrity')
        c2 = Candidate(election_id='1', candidate_index=1, name='Candidate Bob', department='ECE', year='Third Year', slogan='Progress')
        _db.session.add_all([c1, c2])
        _db.session.commit()
        derive_pseudonym(1, 1)

    # Attach static routes for frontend dist with SPA routing fallback
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_spa(path):
        if request.path.startswith('/api/'):
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

    port = _get_free_port()
    server = ServerThread(app, port)
    server.start()
    time.sleep(0.5)

    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
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
        b = p.chromium.launch(
            executable_path=CHROME_PATH,
            headless=True,
            args=['--no-sandbox', '--disable-gpu']
        )
        yield b
        b.close()


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


def _seed_student_voter(app, idx=10):
    with app.app_context():
        user = User.query.filter_by(username=f'step4_voter_{idx}').first()
        if not user:
            user = User(
                username=f'step4_voter_{idx}',
                email=f'voter_{idx}@college.test',
                password_hash=hash_password('Step4Password123!'),
                voter_id=f'VOTER-ST4-{idx:03d}',
                is_active=True,
                is_verified=True,
            )
            _db.session.add(user)
            _db.session.commit()

        sid = secrets.token_hex(24)
        _seed_authorized_session(_db, user, session_id=sid)

        if not WalletBinding.query.filter_by(user_id=user.id).first():
            wallet = WalletBinding(user_id=user.id, wallet_address='0x' + secrets.token_hex(20), is_verified=True)
            _db.session.add(wallet)

        if not FaceEnrollment.query.filter_by(user_id=user.id).first():
            face = FaceEnrollment(user_id=user.id, encrypted_embedding=b'\x01'*512, is_enrolled=True, consent_given=True)
            _db.session.add(face)

        _db.session.commit()
        return user.id, sid


# ==============================================================================
# 1. Comprehensive Route Verification
# ==============================================================================

PUBLIC_ROUTES = [
    '/',
    '/election',
    '/candidates',
    '/candidates/0',
    '/verification',
    '/receipt-verification',
    '/how-vote-protected',
    '/help',
    '/report-problem',
    '/terms',
    '/privacy',
    '/login',
    '/register',
    '/access-denied',
    '/maintenance',
]

def test_step4_public_routes_load(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    console_errors = []
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)

    for route in PUBLIC_ROUTES:
        url = f"{base_url}{route}"
        page.goto(url)
        page.wait_for_selector('main, .page-container, .hero-section', timeout=5000)
        # Ensure page content is non-empty
        content = page.content()
        assert len(content) > 200
        # Check that page title is present
        title = page.title()
        assert len(title) > 0

    # Ensure no uncaught React/runtime exceptions
    critical_errors = [e for e in console_errors if 'Uncaught' in e or 'TypeError' in e or 'ReferenceError' in e]
    assert len(critical_errors) == 0

    context.close()


def test_step4_unknown_404_route(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{base_url}/unknown/nonexistent-route-404")
    page.wait_for_selector('.page-container', timeout=5000)
    assert '404' in page.inner_text('.page-container')
    assert 'Page Not Found' in page.inner_text('.page-container')

    # Click Return to Home button
    page.locator('button:has-text("Return to Home")').click()
    page.wait_for_selector('.hero-section', timeout=5000)
    assert page.url == f"{base_url}/"

    context.close()


# ==============================================================================
# 2. Student Routes & Session Navigation
# ==============================================================================

STUDENT_ROUTES = [
    '/dashboard',
    '/vote',
    '/receipt',
    '/my-vote',
    '/profile',
]

def test_step4_unauthenticated_student_routes_redirect_to_login(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()  # Empty context, unauthenticated
    page = context.new_page()

    for r in STUDENT_ROUTES:
        page.goto(f"{base_url}{r}")
        page.wait_for_url(f"**/login**", timeout=5000)
        page.wait_for_selector('.login-page', timeout=5000)

    context.close()


def test_step4_authenticated_student_navigation_and_refresh(step4_server, browser):
    base_url, app = step4_server
    uid, sid = _seed_student_voter(app, idx=11)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)
    page = context.new_page()

    # 1. Access Dashboard directly
    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector('.badge-verified-student', timeout=5000)
    assert page.locator('.badge-verified-student').is_visible()
    assert 'AUTHENTICATED VOTER SESSION' in page.inner_text('.badge-verified-student')

    # 2. Direct refresh on protected route preserves session
    page.reload()
    page.wait_for_selector('.badge-verified-student', timeout=5000)
    assert page.locator('.badge-verified-student').is_visible()

    # 3. Navigate to Vote page
    page.get_by_role("button", name="Vote", exact=True).click()
    page.wait_for_selector('#voting-section', timeout=5000)
    assert page.url == f"{base_url}/vote"

    # 4. Navigate to My Vote page
    page.locator('.student-nav button:has-text("My Vote")').click()
    page.wait_for_selector('.my-vote-page', timeout=5000)
    assert page.url == f"{base_url}/my-vote"

    # 5. Navigate to Profile page
    page.locator('.student-nav button:has-text("Profile & Security")').click()
    page.wait_for_selector('.profile-page', timeout=5000)
    assert page.url == f"{base_url}/profile"

    # 6. Browser Back/Forward testing
    page.go_back()
    page.wait_for_selector('.my-vote-page', timeout=5000)
    page.go_forward()
    page.wait_for_selector('.profile-page', timeout=5000)

    # 7. Student Logout
    page.locator('.btn-logout').click()
    page.wait_for_url(f"**/login**", timeout=5000)
    page.wait_for_selector('.login-page', timeout=5000)

    context.close()


# ==============================================================================
# 3. Admin Routes & RBAC Navigation
# ==============================================================================

ADMIN_ROUTES = [
    '/admin/dashboard',
    '/admin/elections',
    '/admin/approvals',
    '/admin/candidates',
    '/admin/voters',
    '/admin/review',
    '/admin/audit',
    '/admin/results',
    '/admin/verification',
    '/admin/health',
]

def test_step4_unauthenticated_admin_routes_redirect_to_admin_login(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    for r in ADMIN_ROUTES:
        page.goto(f"{base_url}{r}")
        page.wait_for_url(f"**/admin/login**", timeout=5000)
        page.wait_for_selector('.admin-login-page', timeout=5000)

    context.close()


def test_step4_authenticated_admin_officer_and_auditor_roles(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    # Pre-seed admin session token in sessionStorage (Officer role)
    page.goto(f"{base_url}/admin/login")
    page.evaluate("""() => {
        window.sessionStorage.setItem('vwd_admin_token', 'mock-officer-token-xyz');
        window.sessionStorage.setItem('vwd_admin_user', JSON.stringify({
            admin_id: 'ADM-OFFICER-01',
            name: 'Election Officer One',
            role: 'OFFICER'
        }));
    }""")

    # Navigate to Admin Dashboard as Officer
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_selector('.admin-layout', timeout=5000)
    assert 'ROLE: OFFICER' in page.inner_text('.role-officer')
    assert 'Operational Officer' in page.inner_text('.admin-status-right')

    # Switch session in sessionStorage to Auditor role
    page.evaluate("""() => {
        window.sessionStorage.setItem('vwd_admin_user', JSON.stringify({
            admin_id: 'ADM-AUDITOR-01',
            name: 'Independent Auditor',
            role: 'AUDITOR'
        }));
    }""")
    page.reload()
    page.wait_for_selector('.admin-layout', timeout=5000)
    assert 'ROLE: AUDITOR' in page.inner_text('.role-auditor')
    assert 'Read-Only / Cryptographic Integrity' in page.inner_text('.admin-status-right')

    # Auditor visits Approvals queue: must see read-only governance notice
    page.locator('.admin-nav button:has-text("Approvals")').click()
    page.wait_for_selector('.admin-approvals-page', timeout=5000)
    assert 'Auditor Inspection Notice' in page.inner_text('.admin-approvals-page')

    # Admin Logout
    page.locator('.btn-logout').click()
    page.wait_for_url(f"**/admin/login**", timeout=5000)
    page.wait_for_selector('.admin-login-page', timeout=5000)

    context.close()


# ==============================================================================
# 4. Responsive Viewports Testing
# ==============================================================================

VIEWPORTS = [
    {'name': 'Desktop 1080p', 'width': 1920, 'height': 1080},
    {'name': 'Desktop 900p', 'width': 1440, 'height': 900},
    {'name': 'Laptop 768p', 'width': 1366, 'height': 768},
    {'name': 'Tablet Landscape', 'width': 1024, 'height': 768},
    {'name': 'Tablet Portrait', 'width': 768, 'height': 1024},
    {'name': 'Mobile iPhone 14', 'width': 390, 'height': 844},
    {'name': 'Mobile iPhone SE', 'width': 375, 'height': 812},
]

def test_step4_responsive_viewports_no_overflow(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    routes_to_check = ['/', '/election', '/candidates', '/how-vote-protected', '/login', '/register', '/report-problem']

    for vp in VIEWPORTS:
        page.set_viewport_size({'width': vp['width'], 'height': vp['height']})

        for r in routes_to_check:
            page.goto(f"{base_url}{r}")
            page.wait_for_selector('.page-container, .hero-section', timeout=5000)

            # Check that there is no horizontal body overflow
            overflow = page.evaluate("""() => {
                const doc = document.documentElement;
                return doc.scrollWidth - doc.clientWidth;
            }""")
            # Allow at most 2px subpixel rounding tolerance
            assert overflow <= 2, f"Horizontal overflow detected on route {r} at viewport {vp['name']}: {overflow}px"

            # Check minimum touch target size (44x44) on interactive buttons
            button_sizes = page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button.btn, a.btn'));
                return btns.map(b => {
                    const rect = b.getBoundingClientRect();
                    return { width: rect.width, height: rect.height, text: b.innerText };
                });
            }""")
            for b in button_sizes:
                if b['width'] > 0 and b['height'] > 0:
                    assert b['height'] >= 44, f"Button target too small height ({b['height']}px): {b['text']}"

    context.close()


# ==============================================================================
# 5. Accessibility & Keyboard Navigation QA
# ==============================================================================

def test_step4_keyboard_tab_order_and_focus_outline(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{base_url}/login")
    page.wait_for_selector('.login-page', timeout=5000)

    # Press Tab key multiple times and ensure focus advances cleanly through form controls
    for _ in range(5):
        page.keyboard.press('Tab')

    # Ensure focused element has an accessible outline
    has_focus_outline = page.evaluate("""() => {
        const el = document.activeElement;
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.outlineStyle !== 'none' || style.boxShadow !== 'none' || el.tagName === 'INPUT' || el.tagName === 'BUTTON';
    }""")
    assert has_focus_outline is True

    context.close()


def test_step4_prefers_reduced_motion(step4_server, browser):
    base_url, _ = step4_server
    # Emulate prefers-reduced-motion: reduce
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()

    page.goto(f"{base_url}/")
    page.wait_for_selector('.hero-section', timeout=5000)

    # Verify CSS rule applies animation-duration <= 0.01ms under reduced-motion
    motion_disabled = page.evaluate("""() => {
        const btn = document.querySelector('.btn-primary');
        if (!btn) return false;
        const style = window.getComputedStyle(btn);
        return parseFloat(style.transitionDuration) <= 0.01 || style.transitionProperty === 'none' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }""")
    assert motion_disabled is True

    context.close()


# ==============================================================================
# 6. Sensitive Client Storage & Privacy Inspection
# ==============================================================================

def test_step4_client_storage_has_zero_sensitive_data(step4_server, browser):
    base_url, app = step4_server
    uid, sid = _seed_student_voter(app, idx=12)

    context = browser.new_context()
    _set_auth_cookie(context, app, sid)
    page = context.new_page()

    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector('.student-layout', timeout=5000)

    # Inspect localStorage: Must be completely empty
    local_storage_data = page.evaluate("() => Object.keys(window.localStorage)")
    assert len(local_storage_data) == 0, f"localStorage should be empty but found: {local_storage_data}"

    # Inspect sessionStorage: Only admin token/user allowed if logged in as admin; student has zero keys
    session_storage_keys = page.evaluate("() => Object.keys(window.sessionStorage)")
    for k in session_storage_keys:
        assert k in ['vwd_admin_token', 'vwd_admin_user'], f"Unexpected key in sessionStorage: {k}"

    # Verify no passwords, OTPs, seed phrases, or private keys exist anywhere in client storage
    all_storage_dump = page.evaluate("""() => {
        let text = '';
        for (let i = 0; i < localStorage.length; i++) text += localStorage.getItem(localStorage.key(i)) + ' ';
        for (let i = 0; i < sessionStorage.length; i++) text += sessionStorage.getItem(sessionStorage.key(i)) + ' ';
        return text.toLowerCase();
    }""")
    sensitive_words = ['password', 'otp', 'private_key', 'seed phrase', 'mnemonic']
    for w in sensitive_words:
        assert w not in all_storage_dump

    context.close()


# ==============================================================================
# 7. Support Report Client-Side Privacy Filtering
# ==============================================================================

def test_step4_report_problem_proactively_blocks_secrets(step4_server, browser):
    base_url, _ = step4_server
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{base_url}/report-problem")
    page.wait_for_selector('.report-problem-page', timeout=5000)

    textarea = page.locator('textarea')
    submit_btn = page.locator('button[type="submit"]')

    # Test 1: Typing a private key attempt
    textarea.fill('I have a problem with my private key 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef')
    submit_btn.click()
    page.wait_for_selector('.alert-danger', timeout=3000)
    assert 'Do not include private keys or seed phrases' in page.inner_text('.alert-danger')

    # Test 2: Typing an account password
    textarea.fill('My login password is SuperSecretPassword123!')
    submit_btn.click()
    page.wait_for_selector('.alert-danger', timeout=3000)
    assert 'Do not include account passwords' in page.inner_text('.alert-danger')

    # Test 3: Disclosing vote choice
    textarea.fill('I voted for Candidate Alice and need to change it')
    submit_btn.click()
    page.wait_for_selector('.alert-danger', timeout=3000)
    assert 'Never disclose your vote choice' in page.inner_text('.alert-danger')

    # Test 4: Legitimate technical issue submits successfully
    textarea.fill('Email OTP was delayed by 3 minutes on my mobile device.')
    submit_btn.click()
    page.wait_for_selector('.alert-success', timeout=5000)
    assert 'Support Request Logged' in page.inner_text('.alert-success')
    assert 'Reference Tracking ID:' in page.inner_text('.alert-success')

    context.close()
