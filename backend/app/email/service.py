"""
Email Service - Phase 2
Mailpit for development
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


class EmailService:
    def __init__(self):
        self.server = os.getenv('MAIL_SERVER', 'localhost')
        self.port = int(os.getenv('MAIL_PORT', 1025))
        self.use_tls = os.getenv('MAIL_USE_TLS', 'False').lower() == 'true'
        self.use_ssl = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
        self.username = os.getenv('MAIL_USERNAME', '')
        self.password = os.getenv('MAIL_PASSWORD', '')
        self.default_sender = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@votewithoutdoubt.local')
    
    def send_otp(self, recipient_email: str, otp: str, purpose: str = 'login') -> bool:
        """Send OTP email (Mailpit for dev)"""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.default_sender
            msg['To'] = recipient_email
            msg['Subject'] = f'Vote Without Doubt - OTP for {purpose}'
            
            body = f"""
Your One-Time Password (OTP) for {purpose} is:

{otp}

This OTP will expire in 5 minutes.
Do not share this code with anyone.

If you did not request this, please ignore this email.
"""
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(self.server, self.port) as server:
                if self.use_tls:
                    server.starttls()
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            current_app.logger.error(f"Failed to send email: {e}")
            return False
