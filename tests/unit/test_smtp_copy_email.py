from unittest.mock import MagicMock

from ssas.auth.infrastructure.email import smtp_sender


def test_smtp_sender_only_sends_to_central_address(monkeypatch):
    monkeypatch.setattr(smtp_sender.settings, "smtp_only_email", "central@example.test")
    monkeypatch.setattr(smtp_sender.settings, "smtp_host", "smtp.resend.com")
    monkeypatch.setattr(smtp_sender.settings, "smtp_from_email", "avisos@example.test")
    monkeypatch.setattr(smtp_sender.settings, "smtp_username", "resend")
    monkeypatch.setattr(smtp_sender.settings, "smtp_password", "key")
    server = MagicMock()
    server.__enter__.return_value = server
    monkeypatch.setattr(smtp_sender.smtplib, "SMTP", lambda *_args, **_kwargs: server)
    smtp_sender.SMTPEmailSender._send_sync("user@example.test", "Asunto", "Texto", "<p>Texto</p>")
    message = server.send_message.call_args.args[0]
    assert message["To"] == "central@example.test"
    assert message["Bcc"] is None

    smtp_sender.SMTPEmailSender._send_sync("central@example.test", "Asunto", "Texto", "<p>Texto</p>")
    message = server.send_message.call_args.args[0]
    assert message["To"] == "central@example.test"
