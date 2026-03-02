import asyncio
from groq import AsyncGroq
from config import settings


async def main():
    client = AsyncGroq(api_key=settings.groq_key.get_secret_value())
    models = await client.models.list()
    for m in models.data:
        print(f"- {m.id}")


asyncio.run(main())
