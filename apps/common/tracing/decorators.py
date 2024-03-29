from aiohttp import ClientSession
from django.conf import settings

from apps.common.tracing.traced_session import TracedSession


def inject_session(handler=None):
    def wrapper(coro):
        async def wrapped(*args, handler_context=None, **kwargs):
            session_class = TracedSession if settings.TRACE_SESSIONS else ClientSession
            async with session_class() as session:
                try:
                    await coro(*args, **kwargs, session=session)
                finally:
                    if callable(handler):
                        handler(session, handler_context)

        return wrapped

    return wrapper
