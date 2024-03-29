import asyncio
import os

import aiohttp

CLIENT_SESSSION = None
TRUTH_VALUES = ("yes", "true", "1", "on")


_lock = asyncio.Lock()


async def get_client_session():
    from .asgi import application

    global CLIENT_SESSSION

    async with _lock:
        if not CLIENT_SESSSION:
            CLIENT_SESSSION = aiohttp.ClientSession()
            application.on_shutdown.append(CLIENT_SESSSION.close)

    return CLIENT_SESSSION


def get_bool_config(name, default=False):
    """
    Get bool configuration from environment variables
    """
    try:
        env_var = os.environ[name]
    except KeyError:
        return default
    return env_var.lower() in TRUTH_VALUES
