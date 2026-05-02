"""Magic-link authentication with Google Workspace SMTP delivery.

Flow
----
1. Family fills /request-access form → AccessRequest row, status=pending.
2. Admin (Chris) reviews queue at /admin/requests → clicks Approve.
3. Approve action: create Family row, create LoginToken (24h), send email via
   Workspace SMTP relay (smtp.gmail.com:587, STARTTLS, app password) with link
   `/auth/login/{token}`.
4. Recipient clicks link → token validated, marked used → session cookie set
   `mc_family={signed_family_id}`. They land on /home.

Sessions
--------
- Cookie name `mc_family`, value = signed `<family_id>:<signature>` using
  itsdangerous-style HMAC-SHA256 with a SECRET_KEY from env.
- Cookie is HttpOnly, Secure, SameSite=Lax, 90-day expiry.
- The `current_family(request, db)` helper returns the Family or None.
- Routes that need auth use `require_family(...)` dependency.
- Admin routes use `require_admin(...)`.

No third-party auth library; this is ~120 lines of standard library + smtplib.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Family, LoginToken

log = logging.getLogger("mathcircle.auth")

SECRET_KEY = os.getenv(
    "MATHCIRCLE_SECRET_KEY",
    # Stable derived default for dev; production sets a real one.
    hashlib.sha256(b"mathcircle-dev-fallback-key").hexdigest(),
)
COOKIE_NAME = "mc_family"
COOKIE_DAYS = 90
TOKEN_TTL_HOURS = 48
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "chris@base2ml.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Math Circle Home")
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "chris@base2ml.com")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://mathcircle.base2ml.com")


# ---------- cookie signing ----------
def _sign(family_id: int) -> str:
    payload = str(family_id).encode()
    sig = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()[:32]
    return f"{family_id}.{sig}"


def _unsign(value: str) -> Optional[int]:
    try:
        fid_str, sig = value.split(".", 1)
        expected = hmac.new(SECRET_KEY.encode(), fid_str.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, sig):
            return None
        return int(fid_str)
    except Exception:
        return None


def set_session(response: Response, family_id: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=_sign(family_id),
        max_age=COOKIE_DAYS * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_family(request: Request, db: Session) -> Optional[Family]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    fid = _unsign(raw)
    if fid is None:
        return None
    return db.get(Family, fid)


def require_family(
    request: Request, db: Session = Depends(get_db)
) -> Family:
    fam = current_family(request, db)
    if fam is None or not fam.is_active:
        raise HTTPException(401, "Login required")
    return fam


def require_admin(
    request: Request, db: Session = Depends(get_db)
) -> Family:
    fam = current_family(request, db)
    if fam is None or not fam.is_active:
        raise HTTPException(401, "Login required")
    if not fam.is_admin:
        raise HTTPException(403, "Admin only")
    return fam


# ---------- magic-link tokens ----------
def create_login_token(db: Session, family: Family, *, purpose: str = "login") -> LoginToken:
    raw = secrets.token_urlsafe(32)
    token = LoginToken(
        family_id=family.id,
        token=raw,
        purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS),
    )
    db.add(token)
    db.flush()
    return token


def consume_token(db: Session, raw: str) -> Optional[Family]:
    """Return the family if the token is valid and unused; mark it used."""
    row = db.execute(
        select(LoginToken).where(LoginToken.token == raw)
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < datetime.utcnow():
        return None
    fam = db.get(Family, row.family_id)
    if fam is None or not fam.is_active:
        return None
    row.used_at = datetime.utcnow()
    fam.last_login_at = datetime.utcnow()
    db.flush()
    return fam


# ---------- SMTP (Google Workspace) ----------
def send_magic_link(family: Family, token: LoginToken, *, kind: str = "login") -> dict:
    """Send the family their magic-link via Workspace SMTP.

    Returns a dict with at least {"ok": bool, "id": str|None, "fallback": bool}.
    Falls back to logging the URL if SMTP_PASSWORD is empty (useful for dev).
    """
    link = f"{PUBLIC_BASE_URL}/auth/login/{token.token}"
    if kind == "invite":
        subject = "You're in — Math Circle Home"
        intro = (
            "Hi! Chris has approved your family for Math Circle Home. "
            "Click the link below to sign in for the first time:"
        )
    else:
        subject = "Your Math Circle Home sign-in link"
        intro = "Click the link below to sign in. It works for 48 hours."

    body_text = (
        f"{intro}\n\n{link}\n\n"
        f"If you didn't request this, you can ignore the email — the link "
        f"won't do anything until used.\n\n"
        f"— Chris\n"
        f"Math Circle Home, Mt Lebanon, PA\n"
        f"Reply to chris@base2ml.com if you have questions."
    )
    body_html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 540px; padding: 16px;">
      <p style="font-size: 16px; color: #2b2b2b;">{intro}</p>
      <p style="margin: 24px 0;">
        <a href="{link}" style="display:inline-block; padding:12px 22px; background:#e76f51;
           color:#fff; border-radius: 999px; text-decoration:none; font-weight:600;">
          Sign in to Math Circle Home
        </a>
      </p>
      <p style="font-size: 13px; color: #666;">Or paste this URL into your browser:<br>
        <a href="{link}" style="color:#264653; word-break:break-all;">{link}</a></p>
      <p style="font-size: 13px; color: #666;">If you didn't request this, you can ignore
        the email — the link won't do anything until used.</p>
      <hr style="border: 0; border-top: 1px solid #eee; margin: 28px 0 16px;">
      <p style="font-size: 12px; color: #888;">— Chris<br>
        Math Circle Home, built by a parent in Mt Lebanon, PA</p>
    </div>
    """

    if not SMTP_PASSWORD:
        log.warning("SMTP_PASSWORD missing — magic link NOT sent. Link: %s", link)
        return {"ok": False, "id": None, "fallback": True, "link": link}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM))
    msg["To"] = family.email
    if SMTP_REPLY_TO:
        msg["Reply-To"] = SMTP_REPLY_TO
    message_id = make_msgid(domain=SMTP_FROM.split("@", 1)[-1] or "base2ml.com")
    msg["Message-ID"] = message_id
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        log.info("magic-link sent to %s (msg-id=%s)", family.email, message_id)
        return {"ok": True, "id": message_id, "fallback": False, "link": link}
    except Exception as e:
        log.exception("smtp send failed: %s", e)
        return {"ok": False, "id": None, "fallback": True, "link": link, "error": str(e)}
