"""
Email service — sends verification codes via Gmail SMTP
Uses Python's built-in smtplib (run in thread to avoid blocking async loop)
"""
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..core.config import get_settings


def _build_verification_email(to_email: str, code: str) -> MIMEMultipart:
    settings = get_settings()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your VideoAI Verification Code: {code}"
    msg["From"] = f"VideoAI <{settings.MAIL_USERNAME}>"
    msg["To"] = to_email

    plain = f"Your verification code is: {code}\n\nThis code expires in 10 minutes. If you didn't request this, ignore this email."

    html = f"""\
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 480px; margin: 0 auto; background: #0a0a1a; border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08);">
      <div style="padding: 32px 28px; text-align: center;">
        <div style="display: inline-block; width: 48px; height: 48px; background: linear-gradient(135deg, #478BE0, #2F61A0); border-radius: 12px; line-height: 48px; margin-bottom: 20px;">
          <span style="color: #fff; font-size: 22px; font-weight: 700;">V</span>
        </div>
        <h1 style="color: #fff; font-size: 22px; font-weight: 700; margin: 0 0 8px; letter-spacing: -0.02em;">Verification Code</h1>
        <p style="color: rgba(255,255,255,0.5); font-size: 14px; margin: 0 0 28px;">Use the code below to verify your identity</p>
        <div style="background: rgba(71,139,224,0.08); border: 1px solid rgba(71,139,224,0.2); border-radius: 12px; padding: 20px; margin-bottom: 28px;">
          <span style="font-size: 36px; font-weight: 700; letter-spacing: 12px; color: #478BE0; font-family: monospace;">{code}</span>
        </div>
        <p style="color: rgba(255,255,255,0.35); font-size: 13px; margin: 0;">This code expires in <strong style="color: rgba(255,255,255,0.6);">10 minutes</strong>. If you didn't request this, you can safely ignore this email.</p>
      </div>
      <div style="background: rgba(255,255,255,0.02); padding: 16px 28px; text-align: center; border-top: 1px solid rgba(255,255,255,0.04);">
        <p style="color: rgba(255,255,255,0.25); font-size: 12px; margin: 0;">VideoAI — AI Video Summarizer</p>
      </div>
    </div>"""

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_smtp(to_email: str, code: str) -> None:
    """Blocking SMTP send — run via asyncio.to_thread()"""
    settings = get_settings()
    msg = _build_verification_email(to_email, code)

    with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=15) as server:
        server.starttls()
        server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
        server.send_message(msg)


async def send_verification_email(to_email: str, code: str) -> bool:
    """Send verification code email (async-safe)"""
    try:
        await asyncio.to_thread(_send_smtp, to_email, code)
        print(f"[OK] Verification email sent to {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email to {to_email}: {e}")
        return False
