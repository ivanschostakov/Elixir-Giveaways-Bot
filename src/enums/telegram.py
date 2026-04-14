from typing import Literal
from aiogram.enums import ChatType, ChatMemberStatus

type Joinable = Literal[ChatType.GROUP, ChatType.CHANNEL, ChatType.SUPERGROUP]
VALID_MEMBER_STATUSES = [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]
