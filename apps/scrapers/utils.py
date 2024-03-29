import logging
import re
import traceback
from decimal import Decimal
from functools import wraps
from typing import Dict, List, Optional, Type

from aiohttp.client_exceptions import ClientConnectorError
from unicaps import CaptchaSolver, CaptchaSolvingService

from apps.scrapers.errors import NetworkConnectionException
from services.utils.secrets import get_secret_value

TransformValue = Type[Exception]
TranformExceptionMapping = Dict[Type[Exception], TransformValue]


logger = logging.getLogger(__name__)


def transform_exceptions(exception_mapping: TranformExceptionMapping, default: Optional[TransformValue] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                tb = "\n".join(traceback.format_exception(None, e, e.__traceback__))
                logger.exception("Got original exception: %s", tb)
                for exception_class, substitute in exception_mapping.items():
                    if not isinstance(e, exception_class):
                        continue
                    logger.info(f"Got match, replacing with {substitute}")
                    raise substitute() from e
                else:
                    if default is None:
                        logger.info("No default, re-raising exception")
                        raise
                    logger.info(f"Raising default {default}")
                    raise default() from e
            else:
                return result

        return wrapper

    return decorator


catch_network = transform_exceptions({ClientConnectorError: NetworkConnectionException})


def semaphore_coroutine(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with args[1]:
            ret = await func(*args, **kwargs)
            return ret

    return wrapper


def extract_numeric_values(text: str) -> List[str]:
    return re.findall(r"(\d[\d.,]*)\b", text)


def convert_string_to_price(text: str) -> Decimal:
    try:
        price = extract_numeric_values(text)[0]
        price = price.replace(",", "")
        return Decimal(price)
    except (KeyError, ValueError, TypeError, IndexError):
        return Decimal("0")


def solve_captcha(site_key: str, url: str, score: float, is_enterprise: bool, api_domain: str):
    solver = CaptchaSolver(CaptchaSolvingService.ANTI_CAPTCHA, get_secret_value("ANTI_CAPTCHA_API_KEY"))
    solved = solver.solve_recaptcha_v3(
        site_key=site_key, page_url=url, is_enterprise=is_enterprise, min_score=score, api_domain=api_domain
    )

    return solved
