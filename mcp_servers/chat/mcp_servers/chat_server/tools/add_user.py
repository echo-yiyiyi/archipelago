from loguru import logger
from models.chat import GroupInfo, GroupMember, MembershipInfo, UserInfo, UserProfile
from models.requests import AddUserRequest
from models.responses import AddUserResponse
from utils.decorators import make_async_background
from utils.storage import generate_user_id, list_directories, load_json, save_json


@make_async_background
def add_user(request: AddUserRequest) -> AddUserResponse:
    """Add a user to the workspace and optionally add them to a channel."""
    try:
        name = request.name.strip()
        email = request.email.strip().lower()
        if not name:
            raise ValueError("User name must not be blank")
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")

        for user_dir in list_directories("Users"):
            user_data = load_json(f"Users/{user_dir}", "user_info.json")
            if not user_data:
                continue
            existing_user = UserInfo.model_validate(user_data)
            if existing_user.user.email.strip().lower() == email:
                raise ValueError(f"User with email {email} already exists")

        group = None
        if request.channel_id:
            group_data = load_json(f"Groups/{request.channel_id}", "group_info.json")
            if not group_data:
                raise ValueError(f"Channel {request.channel_id} not found")
            group = GroupInfo.model_validate(group_data)
            if any(member.email.strip().lower() == email for member in group.members):
                raise ValueError(
                    f"User with email {email} is already a member of channel "
                    f"{request.channel_id}"
                )

        user_id = generate_user_id()
        memberships = []
        if group and request.channel_id:
            memberships.append(
                MembershipInfo(
                    group_name=group.name,
                    group_id=request.channel_id,
                    membership_state="MEMBER_JOINED",
                )
            )

        new_user = UserInfo(
            user=UserProfile(name=name, email=email, user_type=request.user_type),
            membership_info=memberships,
        )
        save_json(
            f"Users/{user_id}",
            "user_info.json",
            new_user.model_dump(),
        )

        if group and request.channel_id:
            group.members.append(
                GroupMember(name=name, email=email, user_type=request.user_type)
            )
            save_json(
                f"Groups/{request.channel_id}",
                "group_info.json",
                group.model_dump(),
            )

        return AddUserResponse(
            user_id=user_id,
            name=name,
            email=email,
            user_type=request.user_type,
            channel_id=request.channel_id,
        )
    except Exception as exc:
        logger.error(f"Error adding user: {exc}")
        raise ValueError(f"Error adding user: {exc}") from exc
