"""
Email Service - Vote Without Doubt
Handles email delivery via SMTP (Mailpit for development) with responsive branded HTML templates
and plain-text alternatives.
"""

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
        """Send a branded OTP verification email with both HTML and plain-text alternatives."""
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.default_sender
            msg['To'] = recipient_email

            purpose_clean = purpose.replace('_', ' ').strip()
            purpose_title = purpose_clean.title()
            msg['Subject'] = f'Vote Without Doubt — Verification Code for {purpose_title}'

            # Sanitize inputs for template insertion
            safe_otp = html.escape(str(otp).strip())
            safe_purpose = html.escape(purpose_clean.upper())

            # 1. Plain-text version (RFC fallback for text-only clients and screen readers)
            text_body = f"""VOTE WITHOUT DOUBT
Official Collegiate E-Voting Platform
--------------------------------------------------

YOUR VERIFICATION CODE FOR {safe_purpose}:

    {safe_otp}

This code will expire in 5 minutes.

SECURITY REMINDER:
Do not share this code with anyone. Election officers, college administrators,
and technical support will never ask for your verification code or password.

If you did not request this verification code, please ignore this message
or contact your campus election administrator immediately.
--------------------------------------------------
Vote Without Doubt — Secure, Transparent, Cryptographically Verifiable E-Voting
"""
            msg.attach(MIMEText(text_body, 'plain', 'utf-8'))

            # 2. Branded HTML version (responsive, table-based for universal email client compatibility)
            html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vote Without Doubt Verification Code</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F1F5F9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1E293B;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #F1F5F9; padding: 32px 16px;">
    <tr>
      <td align="center">
        <!-- Main Container Card -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 560px; background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">

          <!-- Header Bar -->
          <tr>
            <td style="background-color: #0F172A; padding: 28px 32px; text-align: center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td align="center">
                    <span style="display: inline-block; background-color: #F59E0B; color: #000000; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 4px 10px; border-radius: 4px; text-transform: uppercase; margin-bottom: 8px;">
                      Official Verification
                    </span>
                    <h1 style="margin: 8px 0 4px 0; color: #FFFFFF; font-size: 22px; font-weight: 900; letter-spacing: 0.5px;">
                      VOTE WITHOUT DOUBT
                    </h1>
                    <p style="margin: 0; color: #94A3B8; font-size: 13px; font-weight: 500;">
                      Collegiate Electronic Voting Platform
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body Content -->
          <tr>
            <td style="padding: 32px 32px 24px 32px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td>
                    <h2 style="margin: 0 0 12px 0; color: #0F172A; font-size: 18px; font-weight: 800;">
                      One-Time Verification Code
                    </h2>
                    <p style="margin: 0 0 20px 0; color: #475569; font-size: 14px; line-height: 1.6;">
                      You requested a verification code to complete your <strong style="color: #0F172A;">{safe_purpose}</strong> request. Please enter the six-digit code below into the application:
                    </p>
                  </td>
                </tr>

                <!-- Prominent OTP Display Box -->
                <tr>
                  <td align="center" style="padding: 12px 0 24px 0;">
                    <div style="background-color: #F8FAFC; border: 2px dashed #CBD5E1; border-radius: 8px; padding: 20px 28px; display: inline-block;">
                      <span style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; font-size: 34px; font-weight: 900; letter-spacing: 10px; color: #0F172A; margin-left: 10px;">
                        {safe_otp}
                      </span>
                    </div>
                  </td>
                </tr>

                <!-- Expiry Notice -->
                <tr>
                  <td align="center" style="padding-bottom: 24px;">
                    <span style="display: inline-block; background-color: #EFF6FF; color: #1D4ED8; font-size: 12px; font-weight: 700; padding: 6px 14px; border-radius: 20px; border: 1px solid #BFDBFE;">
                      ⏱️ Valid for 5 minutes only
                    </span>
                  </td>
                </tr>

                <!-- Security Warning Box -->
                <tr>
                  <td>
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #FFFBEB; border: 1px solid #FCD34D; border-radius: 8px; padding: 14px 16px;">
                      <tr>
                        <td style="font-size: 13px; line-height: 1.5; color: #92400E;">
                          <strong style="color: #78350F;">🛡️ Security Warning:</strong> Do not share this code with anyone. Election officers, campus administrators, and IT personnel will <em>never</em> ask you for your verification code.
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- Context Note -->
                <tr>
                  <td style="padding-top: 24px;">
                    <p style="margin: 0; color: #64748B; font-size: 12px; line-height: 1.5;">
                      If you did not initiate this authentication request, please disregard this email. Your account remains secure unless someone has access to this inbox.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer Bar -->
          <tr>
            <td style="background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 20px 32px; text-align: center;">
              <p style="margin: 0 0 6px 0; color: #64748B; font-size: 12px; font-weight: 600;">
                Vote Without Doubt &bull; Secure &bull; Transparent &bull; Cryptographically Verifiable
              </p>
              <p style="margin: 0; color: #94A3B8; font-size: 11px;">
                This is an automated system security notification. Replies to this email address are not monitored.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            if self.use_ssl:
                with smtplib.SMTP_SSL(self.server, self.port) as server:
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            else:
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
