import json
import os
from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field
from utils.decorators import make_async_background
from utils.mbox_utils import (
    SOFT_DELETED_AT_HEADER,
    SOFT_DELETED_HEADER,
    UTF8Mbox,
    is_message_deleted,
)
from utils.path import get_mbox_path, resolve_mail_path


def _append_deletion_audit(mail_id: str, deleted_at: str) -> None:
    """Append a durable audit record without storing message content."""
    audit_path = resolve_mail_path("deletion_audit.jsonl")
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as audit_file:
        audit_file.write(
            json.dumps(
                {
                    "action": "soft_delete",
                    "mail_id": mail_id,
                    "deleted_at": deleted_at,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


@make_async_background
def delete_mail(
    mail_id: Annotated[
        str,
        Field(
            description="The Message-ID of the email to soft-delete. Obtain it from list_mails or search_mail."
        ),
    ],
) -> str:
    """Soft-delete an email while retaining its data and an audit record."""
    if not mail_id or not mail_id.strip():
        return "Error: Invalid mail_id - cannot be empty"

    mbox_path = get_mbox_path()
    if not os.path.exists(mbox_path):
        return f"Mail not found with ID: {mail_id}"

    try:
        mbox = UTF8Mbox(mbox_path)
        try:
            mbox.lock()
        except (BlockingIOError, OSError):
            return "Mailbox is currently busy. Please try again in a moment."

        try:
            for key, message in mbox.items():
                if message.get("Message-ID") != mail_id:
                    continue
                if is_message_deleted(message):
                    return f"Mail already deleted with ID: {mail_id}"

                deleted_at = datetime.now(UTC).isoformat()
                message[SOFT_DELETED_HEADER] = "true"
                message[SOFT_DELETED_AT_HEADER] = deleted_at
                mbox[key] = message
                mbox.flush()
                _append_deletion_audit(mail_id, deleted_at)
                return f"Mail deleted successfully with ID: {mail_id}"
        finally:
            mbox.unlock()
            mbox.close()

        return f"Mail not found with ID: {mail_id}"
    except Exception as exc:
        return f"Failed to delete mail: {repr(exc)}"
