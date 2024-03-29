import asyncio

from apps.common.tracing.har_uploader import upload_traced_session
from apps.common.tracing.traced_session import TracedSession


async def fetch(url):
    async with TracedSession() as client:
        async with client.get(url) as response:
            await response.read()
    upload_traced_session(client, "test")


def main():
    asyncio.run(fetch("https://spotify.com"))


if __name__ == "__main__":
    main()
