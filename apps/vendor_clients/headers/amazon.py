from .base import BASE_HEADERS

SEARCH_HEADERS = {
    **BASE_HEADERS,
    "authority": "www.amazon.com",
    "rtt": "250",
    "downlink": "10",
    "ect": "4g",
    "upgrade-insecure-requests": "1",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
}
