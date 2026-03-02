import asyncio
from aiogram.types import User, Message, Chat
from handlers.messages import ShouldRespondFilter, set_bot_info

bot_user = User(
    id=8694475764, is_bot=True, first_name="Sonnet", username="SonnetHelper_bot"
)
set_bot_info(bot_user)


async def test():
    chat = Chat(id=-1002949279532, type="supergroup")
    user = User(id=6028603028, is_bot=False, first_name="Vlad")

    msg = Message(
        message_id=1,
        date=1234567890,
        chat=chat,
        from_user=user,
        text="@SonnetHelper_bot привет",
    )

    filter = ShouldRespondFilter()
    result = await filter(msg)
    print(f"Filter result: {result}")


asyncio.run(test())
