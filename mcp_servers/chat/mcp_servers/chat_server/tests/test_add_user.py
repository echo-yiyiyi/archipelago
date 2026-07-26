import json

import pytest
from models.requests import AddUserRequest, GetUsersRequest
from tools.add_user import add_user
from tools.get_users import get_users
from utils import path as path_utils


@pytest.mark.asyncio
async def test_add_user_and_join_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "CHAT_DATA_ROOT", str(tmp_path))
    group_dir = tmp_path / "Groups" / "general"
    group_dir.mkdir(parents=True)
    (group_dir / "group_info.json").write_text(
        json.dumps({"name": "General", "members": []}),
        encoding="utf-8",
    )

    result = await add_user(
        AddUserRequest(
            name="Test User",
            email="TEST.USER@example.com",
            user_type="Human",
            channel_id="general",
        )
    )

    assert result.email == "test.user@example.com"
    assert result.channel_id == "general"

    stored_user = json.loads(
        (tmp_path / "Users" / result.user_id / "user_info.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored_user["user"]["name"] == "Test User"
    assert stored_user["membership_info"][0]["group_id"] == "general"

    stored_group = json.loads(
        (group_dir / "group_info.json").read_text(encoding="utf-8")
    )
    assert stored_group["members"] == [
        {
            "name": "Test User",
            "email": "test.user@example.com",
            "user_type": "Human",
        }
    ]

    users = await get_users(GetUsersRequest())
    assert users.total_count == 1
    assert users.users[0].email == "test.user@example.com"

    with pytest.raises(ValueError, match="already exists"):
        await add_user(
            AddUserRequest(name="Duplicate", email="test.user@example.com")
        )


@pytest.mark.asyncio
async def test_add_user_rejects_unknown_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "CHAT_DATA_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="Channel missing not found"):
        await add_user(
            AddUserRequest(
                name="Test Bot",
                email="bot@example.com",
                user_type="Bot",
                channel_id="missing",
            )
        )

    assert not (tmp_path / "Users").exists()
