from unittest.mock import AsyncMock, MagicMock

import pytest

from ssas.personal.application import absence_email
from ssas.personal.infrastructure.http.router import absence_approver_emails


@pytest.mark.asyncio
async def test_absence_email_uses_manager_before_admin_fallback():
    session = AsyncMock()
    session.scalars.return_value.all = MagicMock(return_value=["jefe@example.test"])
    recipients = await absence_approver_emails(session, "company", "employee")
    assert recipients == ["jefe@example.test"]
    assert session.scalars.await_count == 1


@pytest.mark.asyncio
async def test_absence_email_falls_back_to_company_admins():
    session = AsyncMock()
    first = MagicMock()
    first.all.return_value = []
    second = MagicMock()
    second.all.return_value = ["rrhh@example.test", "rrhh@example.test"]
    session.scalars.side_effect = [first, second]
    recipients = await absence_approver_emails(session, "company", "employee")
    assert recipients == ["rrhh@example.test"]


@pytest.mark.asyncio
async def test_absence_notice_deduplicates_recipients(monkeypatch):
    monkeypatch.setattr(absence_email.settings, "smtp_host", "smtp.resend.com")
    monkeypatch.setattr(absence_email.settings, "smtp_from_email", "avisos@example.test")
    monkeypatch.setattr(absence_email.settings, "smtp_only_email", "central@example.test")
    send = AsyncMock()
    monkeypatch.setattr(absence_email.SMTPEmailSender, "send", send)
    await absence_email.send_absence_notice(
        ["jefe@example.test", "jefe@example.test"], "Asunto", "Mensaje", "personal/ausencias/bandeja",
    )
    send.assert_awaited_once()
    assert send.await_args.args[0] == "central@example.test"
    assert "personal/ausencias/bandeja" in send.await_args.args[2]
