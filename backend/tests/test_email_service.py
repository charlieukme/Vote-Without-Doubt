"""
Email Service Unit Tests
Vote Without Doubt - Backend
"""

from unittest.mock import MagicMock, patch
import pytest

from app.email.service import EmailService


def test_send_otp_builds_multipart_alternative_with_html_and_text(app):
    """Verify that send_otp attaches both plain-text and branded HTML parts."""
    with app.app_context():
        service = EmailService()
        sent_messages = []

        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        def record_send(msg):
            sent_messages.append(msg)
            return {}
        mock_smtp.send_message.side_effect = record_send

        with patch('smtplib.SMTP', return_value=mock_smtp):
            success = service.send_otp(
                recipient_email='student@college.edu',
                otp='849201',
                purpose='student_login',
            )

        assert success is True
        assert len(sent_messages) == 1
        msg = sent_messages[0]

        assert msg['To'] == 'student@college.edu'
        assert 'Vote Without Doubt' in msg['Subject']
        assert 'Student Login' in msg['Subject']
        assert msg.is_multipart() is True

        payloads = msg.get_payload()
        assert len(payloads) == 2

        # 1. Plain text alternative
        text_part = payloads[0]
        assert text_part.get_content_type() == 'text/plain'
        text_content = text_part.get_payload(decode=True).decode('utf-8')
        assert '849201' in text_content
        assert '5 minutes' in text_content
        assert 'SECURITY REMINDER' in text_content

        # 2. Branded HTML alternative
        html_part = payloads[1]
        assert html_part.get_content_type() == 'text/html'
        html_content = html_part.get_payload(decode=True).decode('utf-8')
        assert '849201' in html_content
        assert 'VOTE WITHOUT DOUBT' in html_content
        assert 'Valid for 5 minutes only' in html_content
        assert 'Security Warning' in html_content
        assert 'STUDENT LOGIN' in html_content


def test_send_otp_handles_smtp_exception_gracefully(app):
    """Verify that SMTP communication failures return False without crashing."""
    with app.app_context():
        service = EmailService()
        with patch('smtplib.SMTP', side_effect=Exception('SMTP connection refused')):
            success = service.send_otp(
                recipient_email='student@college.edu',
                otp='123456',
                purpose='login',
            )
            assert success is False
