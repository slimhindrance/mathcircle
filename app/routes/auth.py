"""Auth + request-access + admin queue routes."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..auth import (
    clear_session,
    consume_token,
    create_login_token,
    current_family,
    require_admin,
    send_magic_link,
    set_session,
)
from ..config import FAMILY_CAP, KIDS_PER_FAMILY
from ..database import get_db
from ..models import AccessRequest, Child, Family

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _active_family_count(db: Session) -> int:
    return db.execute(
        select(func.count(Family.id)).where(Family.is_active.is_(True))
    ).scalar_one()


def _waitlist_count(db: Session) -> int:
    return db.execute(
        select(func.count(AccessRequest.id)).where(
            AccessRequest.status.in_(["pending", "waitlisted"])
        )
    ).scalar_one()


# ---------- public landing page ----------
@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    fam = current_family(request, db)
    if fam is not None:
        return RedirectResponse("/home", status_code=303)
    active = _active_family_count(db)
    waitlist = _waitlist_count(db)
    return _templates(request).TemplateResponse(
        request,
        "landing.html",
        {
            "active_count": active,
            "cap": FAMILY_CAP,
            "kids_per_family": KIDS_PER_FAMILY,
            "waitlist_count": waitlist,
            "is_full": active >= FAMILY_CAP,
        },
    )


# ---------- request access (public) ----------
@router.get("/request-access", response_class=HTMLResponse)
def request_access_form(request: Request, db: Session = Depends(get_db)):
    fam = current_family(request, db)
    if fam is not None:
        return RedirectResponse("/home", status_code=303)
    active = _active_family_count(db)
    waitlist = _waitlist_count(db)
    return _templates(request).TemplateResponse(
        request,
        "request_access.html",
        {
            "active_count": active,
            "cap": FAMILY_CAP,
            "kids_per_family": KIDS_PER_FAMILY,
            "waitlist_count": waitlist,
            "is_full": active >= FAMILY_CAP,
            "submitted": False,
        },
    )


@router.post("/request-access")
async def request_access_submit(
    request: Request,
    family_name: str = Form(...),
    parent_email: str = Form(...),
    kids_summary: str = Form(""),
    referral: str = Form(""),
    db: Session = Depends(get_db),
):
    parent_email = parent_email.strip().lower()
    family_name = family_name.strip()
    # de-dupe — if same email already pending, just show the same confirmation
    existing = db.execute(
        select(AccessRequest)
        .where(AccessRequest.parent_email == parent_email)
        .where(AccessRequest.status.in_(["pending", "waitlisted"]))
    ).scalar_one_or_none()
    if existing is None:
        active = _active_family_count(db)
        status = "pending" if active < FAMILY_CAP else "waitlisted"
        ip_address = (request.client.host if request.client else "")[:64]
        db.add(
            AccessRequest(
                family_name=family_name[:160],
                parent_email=parent_email[:160],
                kids_summary=(kids_summary or "")[:500],
                referral=(referral or "")[:1000],
                status=status,
                ip_address=ip_address,
            )
        )
        db.commit()
    active = _active_family_count(db)
    waitlist = _waitlist_count(db)
    return _templates(request).TemplateResponse(
        request,
        "request_access.html",
        {
            "active_count": active,
            "cap": FAMILY_CAP,
            "kids_per_family": KIDS_PER_FAMILY,
            "waitlist_count": waitlist,
            "is_full": active >= FAMILY_CAP,
            "submitted": True,
            "submitted_email": parent_email,
        },
    )


# ---------- magic-link login ----------
@router.get("/auth/login/{token}", response_class=HTMLResponse)
def auth_consume(token: str, request: Request, db: Session = Depends(get_db)):
    fam = consume_token(db, token)
    if fam is None:
        return _templates(request).TemplateResponse(
            request,
            "login_failed.html",
            {"reason": "Link expired or already used."},
        )
    db.commit()
    resp = RedirectResponse("/home", status_code=303)
    set_session(resp, fam.id)
    return resp


@router.get("/auth/logout")
def auth_logout(_request: Request):
    resp = RedirectResponse("/", status_code=303)
    clear_session(resp)
    return resp


# Optional convenience: existing family can request a new login link by email
@router.get("/auth/sign-in", response_class=HTMLResponse)
def signin_form(request: Request):
    return _templates(request).TemplateResponse(
        request, "signin.html", {"sent": False}
    )


@router.post("/auth/sign-in")
async def signin_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    fam = db.execute(
        select(Family).where(Family.email == email)
    ).scalar_one_or_none()
    # Always show the same response — we don't reveal which emails exist.
    if fam is not None and fam.is_active:
        token = create_login_token(db, fam, purpose="login")
        db.commit()
        send_magic_link(fam, token, kind="login")
    return _templates(request).TemplateResponse(
        request, "signin.html", {"sent": True, "email": email}
    )


# ---------- admin queue ----------
@router.get("/admin/requests", response_class=HTMLResponse)
def admin_requests(
    request: Request,
    db: Session = Depends(get_db),
    _admin: Family = Depends(require_admin),
):
    pending = db.execute(
        select(AccessRequest)
        .where(AccessRequest.status.in_(["pending", "waitlisted"]))
        .order_by(AccessRequest.created_at)
    ).scalars().all()
    decided = db.execute(
        select(AccessRequest)
        .where(AccessRequest.status.in_(["approved", "declined"]))
        .order_by(desc(AccessRequest.created_at))
        .limit(30)
    ).scalars().all()
    families = db.execute(
        select(Family).order_by(desc(Family.created_at))
    ).scalars().all()
    active = _active_family_count(db)
    return _templates(request).TemplateResponse(
        request,
        "admin_requests.html",
        {
            "pending": pending,
            "decided": decided,
            "families": families,
            "active_count": active,
            "cap": FAMILY_CAP,
        },
    )


@router.post("/admin/requests/{req_id}/approve")
def admin_approve(
    req_id: int,
    db: Session = Depends(get_db),
    _admin: Family = Depends(require_admin),
):
    ar = db.get(AccessRequest, req_id)
    if ar is None:
        raise HTTPException(404)
    if ar.status not in ("pending", "waitlisted"):
        raise HTTPException(400, "Already decided")
    if _active_family_count(db) >= FAMILY_CAP:
        raise HTTPException(409, "Family cap reached")

    # Create or look up the Family record by email
    fam = db.execute(
        select(Family).where(Family.email == ar.parent_email)
    ).scalar_one_or_none()
    if fam is None:
        fam = Family(
            email=ar.parent_email,
            display_name=ar.family_name,
            is_active=True,
        )
        db.add(fam)
        db.flush()

    ar.status = "approved"
    ar.decided_at = datetime.utcnow()
    ar.family_id = fam.id

    # Mint and send the magic link
    token = create_login_token(db, fam, purpose="invite")
    db.commit()
    send_magic_link(fam, token, kind="invite")
    return RedirectResponse("/admin/requests", status_code=303)


@router.post("/admin/requests/{req_id}/decline")
async def admin_decline(
    req_id: int,
    note: str = Form(""),
    db: Session = Depends(get_db),
    _admin: Family = Depends(require_admin),
):
    ar = db.get(AccessRequest, req_id)
    if ar is None:
        raise HTTPException(404)
    ar.status = "declined"
    ar.decided_at = datetime.utcnow()
    ar.admin_note = (note or "")[:1000]
    db.commit()
    return RedirectResponse("/admin/requests", status_code=303)


@router.post("/admin/requests/{req_id}/resend")
def admin_resend(
    req_id: int,
    db: Session = Depends(get_db),
    _admin: Family = Depends(require_admin),
):
    """Re-send the magic link for an already-approved request (in case email was lost)."""
    ar = db.get(AccessRequest, req_id)
    if ar is None or ar.status != "approved" or ar.family_id is None:
        raise HTTPException(404)
    fam = db.get(Family, ar.family_id)
    if fam is None:
        raise HTTPException(404)
    token = create_login_token(db, fam, purpose="login")
    db.commit()
    send_magic_link(fam, token, kind="login")
    return RedirectResponse("/admin/requests", status_code=303)
