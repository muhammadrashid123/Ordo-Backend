import asyncio
from argparse import Namespace

from aiohttp import ClientConnectorError

from apps.scrapers.errors import NetworkConnectionException
from apps.scrapers.utils import catch_network, transform_exceptions


@transform_exceptions({ZeroDivisionError: KeyError})
async def zd_to_ke():
    raise ZeroDivisionError


@transform_exceptions({ZeroDivisionError: KeyError})
async def good():
    return


class CustomError(Exception):
    pass


@transform_exceptions({ZeroDivisionError: KeyError}, default=ValueError)
async def zd_to_ke_default_value_error():
    raise CustomError()


@catch_network
async def bad_network():
    raise ClientConnectorError(1, Namespace(errno=1, strerror="asdf"))


def test_zd_to_ke():
    try:
        asyncio.run(zd_to_ke())
    except KeyError:
        assert True
    else:
        assert False


def test_zd_to_ke_default_value_error():
    try:
        asyncio.run(zd_to_ke_default_value_error())
    except ValueError:
        assert True
    else:
        assert False


def test_good():
    try:
        asyncio.run(good())
    except Exception:
        assert False
    else:
        assert True


def test_catch_network():
    try:
        asyncio.run(bad_network())
    except NetworkConnectionException:
        assert True
    else:
        assert False
