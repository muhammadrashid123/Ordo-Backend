from .base import BASE_HEADERS

LOGIN_HEADERS = {
    **BASE_HEADERS,
    "Cache-Control": "max-age=0",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.net32.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.net32.com/login?origin=%2F",
}

CART_HEADERS = {
    **BASE_HEADERS,
    "Cache-Control": "max-age=0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.net32.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://www.net32.com/shopping-cart",
}

ADD_PRODUCT_TO_CART_HEADERS = CART_HEADERS
ADD_PRODUCTS_TO_CART_HEADERS = ADD_PRODUCT_TO_CART_HEADERS
REMOVE_PRODUCT_FROM_CART_HEADERS = ADD_PRODUCT_TO_CART_HEADERS
GET_CART_HEADERS = CART_HEADERS
REVIEW_ORDER_HEADERS = {
    **BASE_HEADERS,
    "Upgrade-Insecure-Requests": "1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.net32.com/shopping-cart",
}

PLACE_ORDER_HEADERS = {
    **BASE_HEADERS,
    "Content-Length": "0",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Origin": "https://www.net32.com",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Referer": "https://www.net32.com/checkout/review",
}
