import logging
import time
import urllib.parse
import uuid
from datetime import datetime
from http.cookies import Morsel, SimpleCookie

import aiohttp
from aiohttp import ClientResponse
from multidict import CIMultiDict
from pytz import utc

logger = logging.getLogger(__name__)


class HarEntry:
    def __init__(self, url: str, headers: CIMultiDict, method: str, start: float):
        self.headers = headers
        self.url: str = url
        self.method: str = method
        self.start: float = start
        self.end: float or None = None
        self.last_chunk_send: float or None = None
        self.first_chunk_receive: float or None = None
        self.last_chunk_receive: float or None = None
        self.request_chunks: list[bytes] = []
        self.response_chunks: list[bytes] = []
        self.response = None

    def add_request_chunk(self, chunk: bytes):
        self.request_chunks.append(chunk)
        self.last_chunk_send = time.time()

    def add_response_chunk(self, chunk: bytes):
        self.response_chunks.append(chunk)
        if not self.first_chunk_receive:
            self.first_chunk_receive = time.time()
        self.last_chunk_receive = time.time()

    def set_response(self, response: ClientResponse):
        self.response = response

    def query_string(self):
        parsed_url = urllib.parse.urlparse(self.url)
        return [{"name": name, "value": value} for name, value in urllib.parse.parse_qsl(parsed_url.query)]

    def request_headers(self):
        result = [
            {
                "name": name,
                "value": value,
            }
            for name, value in self.response.request_info.headers.items()
        ]
        return result

    def response_headers(self):
        result = [
            {
                "name": name,
                "value": value,
            }
            for name, value in self.response.headers.items()
        ]
        return result

    def post_data(self):
        text = b"".join(self.request_chunks).decode()
        content_type = self.response.request_info.headers.get("content-type")
        params = []
        return {
            "mimeType": content_type,
            "params": params,
            "text": text,
        }

    def request_cookies(self):
        result = []
        cookie_header = self.response.request_info.headers.get("cookie")
        if not cookie_header:
            return result
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        for key, morsel in cookie.items():
            result.append({"name": key, "value": morsel.value})
        return result

    def response_cookies(self):
        result = []
        for cookie_name in self.response.cookies:
            m: Morsel = self.response.cookies.get(cookie_name)
            v = {
                "name": m.key,
                "value": m.value,
            }
            if "path" in m:
                v["path"] = m["path"]
            if "domain" in m:
                v["domain"] = m["domain"]
            if "expires" in m:
                try:
                    expires = (
                        datetime.strptime(m["expires"], "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=utc).isoformat()
                    )
                except ValueError:
                    expires = ""
                v["expires"] = expires
            if "httponly" in m:
                v["httpOnly"] = m["httponly"]
            if "secure" in m:
                v["secure"] = m["secure"]
            result.append(v)

        return result

    def response_har(self):
        body = b"".join(self.response_chunks)
        content = {
            "size": len(body),
            "mimeType": self.response.headers.get("content-type", ""),
            "text": body.decode("utf-8"),
            # "encoding": "base64",
        }
        result = {
            "status": self.response.status,
            "statusText": "OK",
            "httpVersion": "HTTP/1.1",
            "cookies": self.response_cookies(),
            "headers": self.response_headers(),
            "content": content,
            "redirectURL": self.response.headers.get("location", ""),
            "headersSize": -1,
            "bodySize": len(body),
        }
        return result

    def request_har(self):
        result = {
            "method": self.method,
            "url": self.url,
            "httpVersion": "HTTP/1.1",
            "cookies": self.request_cookies(),
            "headers": self.request_headers(),
            "queryString": self.query_string(),
            "postData": self.post_data(),  # TODO: figure out
            "headersSize": -1,
            "bodySize": sum(map(len, self.response_chunks)),
        }
        return result

    def har(self):
        if self.first_chunk_receive and self.last_chunk_receive:
            wait = 1000 * (self.first_chunk_receive - self.last_chunk_send)
        else:
            wait = 0
        if self.last_chunk_receive and self.first_chunk_receive:
            receive = 1000 * (self.last_chunk_receive - self.first_chunk_receive)
        else:
            receive = 0
        if self.last_chunk_send and self.start:
            send = int((self.last_chunk_send - self.start) * 1000)
        else:
            send = 0
        if self.end and self.start:
            t = (self.last_chunk_send - self.start) * 1000
        else:
            t = 0
        return {
            "startedDateTime": datetime.fromtimestamp(self.start).isoformat(),
            "time": t,
            "request": self.request_har(),
            "response": self.response_har(),
            "cache": {},
            "timings": {
                "blocked": -1,
                "dns": -1,
                "connect": -1,
                "send": send,
                "wait": wait,
                "receive": receive,
                "ssl": -1,
            },
        }


class HarCollector:
    def __init__(self):
        self.entries: dict[uuid.UUID, HarEntry] = {}

    def generate_har(self):
        entries = []
        for entry in self.entries.values():
            try:
                har = entry.har()
            except Exception:
                logger.exception("Could not generate HAR for entry")
            else:
                entries.append(har)
        return {
            "log": {
                "version": "1.2",
                "creator": {},
                "browser": {},
                "pages": [],
                "entries": entries,
                "comment": "",
            }
        }


def request_tracer(collector: HarCollector):
    async def on_request_start(session, context, params: aiohttp.TraceRequestStartParams):
        request_id = uuid.uuid4()
        context.request_id = request_id
        entry = HarEntry(
            url=str(params.url),
            headers=params.headers,
            method=params.method,
            start=time.time(),
        )
        collector.entries[request_id] = entry

    async def on_request_redirect(session, context, params: aiohttp.TraceRequestRedirectParams):
        entry = collector.entries[context.request_id]
        entry.set_response(params.response)
        entry.end = time.time()

        request_id = uuid.uuid4()
        context.request_id = request_id
        next_entry = HarEntry(
            url=str(params.response.headers["Location"]),
            headers=entry.headers,
            method=entry.method,
            start=time.time(),
        )

        collector.entries[request_id] = next_entry

    async def on_request_chunk_sent(session, context, params):
        entry = collector.entries[context.request_id]
        entry.add_request_chunk(params.chunk)

    async def on_response_chunk_received(session, context, params: aiohttp.TraceResponseChunkReceivedParams):
        entry = collector.entries[context.request_id]
        entry.add_response_chunk(params.chunk)

    async def on_request_end(session, context, params):
        entry = collector.entries[context.request_id]
        entry.set_response(params.response)
        entry.end = time.time()

    async def on_request_exception(session, context, params: aiohttp.TraceRequestExceptionParams):
        # discard entry completely
        collector.entries.pop(context.request_id, None)

    trace_config = aiohttp.TraceConfig()

    trace_config.on_request_start.append(on_request_start)
    trace_config.on_request_redirect.append(on_request_redirect)
    trace_config.on_request_end.append(on_request_end)
    trace_config.on_request_chunk_sent.append(on_request_chunk_sent)
    trace_config.on_response_chunk_received.append(on_response_chunk_received)
    trace_config.on_request_exception.append(on_request_exception)

    return trace_config


class TracedSession(aiohttp.ClientSession):
    def __init__(self, *args, **kwargs):
        self.trace: HarCollector = HarCollector()
        trace_configs = kwargs.get("trace_configs", [])
        trace_configs.append(request_tracer(self.trace))
        kwargs["trace_configs"] = trace_configs
        super().__init__(*args, **kwargs)
