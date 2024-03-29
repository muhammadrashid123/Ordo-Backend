from .base import BASE_HEADERS

PRE_LOGIN_HEADERS = {
    **BASE_HEADERS,
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

LOGIN_HEADERS = {
    **BASE_HEADERS,
    "Upgrade-Insecure-Requests": "1",
    "Origin": "https://identity.benco.com",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

POST_LOGIN_HEADERS = {
    "Upgrade-Insecure-Requests": "1",
    "Origin": "https://identity.benco.com",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://identity.benco.com/",
}

GET_PRODUCT_PRICES_HEADERS = {
    **BASE_HEADERS,
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://shop.benco.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://shop.benco.com/",
}

CLEAR_CART_HEADERS = {
    **BASE_HEADERS,
    "Upgrade-Insecure-Requests": "1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://shop.benco.com/Cart",
}

ADD_PRODUCT_TO_CART_HEADERS = {
    **BASE_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Request-Context": "appId=cid-v1:c74c9cb3-54a4-4cfa-b480-a6dc8f0d3cdc",
    "Request-Id": "|fpNl1.MtH9L",
    "Origin": "https://shop.benco.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://shop.benco.com/Cart",
}
GET_PRODUCT_PAGE_HEADERS = {
    **BASE_HEADERS,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Request-Context": "appId=cid-v1:c74c9cb3-54a4-4cfa-b480-a6dc8f0d3cdc",
    "Request-Id": "|fpNl1.MtH9L",
    "Origin": "https://shop.benco.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}
