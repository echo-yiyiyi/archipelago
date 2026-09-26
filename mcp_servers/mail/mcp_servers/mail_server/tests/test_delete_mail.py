import json
from email.message import EmailMessage

import pytest
from models.mail import ForwardMailInput, ReplyMailInput, SearchMailInput
from tools._meta_tools import MailInput, mail
from tools.forward_mail import forward_mail
from tools.list_mails import list_mails
from tools.read_mail import read_mail
from tools.reply_mail import reply_mail
from tools.search_mail import search_mail
from utils import path as path_utils
from utils.mbox_utils import SOFT_DELETED_AT_HEADER, SOFT_DELETED_HEADER, UTF8Mbox


def _create_mailbox(root, mail_id="<delete-me@example.com>"):
    root.mkdir(parents=True, exist_ok=True)
    mbox_path = root / "inbox.mbox"
    mbox = UTF8Mbox(str(mbox_path), create=True)
    message = EmailMessage()
    message["Message-ID"] = mail_id
    message["Date"] = "Tue, 15 Jan 2025 10:30:00 +0000"
    message["From"] = "sender@example.com"
    message["To"] = "user@example.com"
    message["Subject"] = "Delete test message"
    message["X-Body-Format"] = "plain"
    message.set_content("This body must be hidden after deletion.")
    mbox.add(message)
    mbox.flush()
    mbox.close()
    return mbox_path, mail_id


@pytest.mark.asyncio
async def test_soft_delete_hides_mail_and_records_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "MAIL_DATA_ROOT", str(tmp_path))
    mbox_path, mail_id = _create_mailbox(tmp_path)

    result = await mail(MailInput(action="delete", mail_id=mail_id))
    assert result.error is None
    assert result.delete is not None
    assert result.delete.success is True

    assert "Mail not found" in await read_mail(mail_id=mail_id)
    assert "No emails found" == await list_mails()
    assert "No emails found" == await search_mail(
        SearchMailInput(subject="Delete test")
    )
    assert "Original mail not found" in await reply_mail(
        ReplyMailInput(original_mail_id=mail_id, body="Should not send")
    )
    assert "Original mail not found" in await forward_mail(
        ForwardMailInput(
            original_mail_id=mail_id,
            to_email="recipient@example.com",
        )
    )

    mbox = UTF8Mbox(str(mbox_path))
    stored_message = next(iter(mbox))
    mbox.close()
    assert stored_message[SOFT_DELETED_HEADER] == "true"
    assert stored_message[SOFT_DELETED_AT_HEADER]
    assert "This body must be hidden" in stored_message.get_payload()

    audit_lines = (tmp_path / "deletion_audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(audit_lines) == 1
    audit = json.loads(audit_lines[0])
    assert audit["action"] == "soft_delete"
    assert audit["mail_id"] == mail_id
    assert audit["deleted_at"] == stored_message[SOFT_DELETED_AT_HEADER]

    repeated = await mail(MailInput(action="delete", mail_id=mail_id))
    assert repeated.delete is None
    assert repeated.error == f"Mail already deleted with ID: {mail_id}"
    assert len(
        (tmp_path / "deletion_audit.jsonl").read_text(encoding="utf-8").splitlines()
    ) == 1


@pytest.mark.asyncio
async def test_soft_delete_rejects_missing_mail(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "MAIL_DATA_ROOT", str(tmp_path))
    _create_mailbox(tmp_path)

    result = await mail(
        MailInput(action="delete", mail_id="<missing@example.com>")
    )
    assert result.delete is None
    assert result.error == "Mail not found with ID: <missing@example.com>"
    assert not (tmp_path / "deletion_audit.jsonl").exists()
