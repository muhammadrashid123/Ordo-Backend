from functools import wraps
from inspect import isfunction
from random import random
from time import sleep
from typing import Any, Callable, Sequence, Type, Union, no_type_check


def retry(
    exc: Union[Type[Exception], Sequence[Type[Exception]]] = Exception,
    max_attempts: int = 1,
    wait: float = 0,
    stall: float = 0,
) -> Callable[[Any], Any]:
    """
    Retry decorator.

    :param exc: List of exceptions that will cause the call to be retried if raised.
    :param max_attempts: Maximum number of attempts to try.
    :param wait: Amount of time to wait before retrying after an exception.
    :param stall: Amount of time to wait before the first attempt.
    :param verbose: If True, prints a message to STDOUT when retries occur.
    :return: Returns the value returned by decorated function.
    """

    @no_type_check
    def _retry(func):
        @wraps(func)
        def retry_decorator(*args, **kwargs):
            if stall:
                sleep(stall)
            attempts = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exc as e:
                    attempts += 1
                    if max_attempts is None or attempts < max_attempts:
                        sleep(wait * (1 + 0.1 * (random() - 0.5)))
                    else:
                        # Max retries exceeded.
                        raise e

        return retry_decorator

    if isfunction(exc):
        # Remember the given function.
        _func = exc
        # Set 'exc' to a sensible exception class for _retry().
        exc = Exception
        # Wrap and return.
        return _retry(func=_func)
    else:
        # Check decorator args, and return _retry,
        # to be called with the decorated function.
        if isinstance(exc, (list, tuple)):
            for _exc in exc:
                if not (isinstance(_exc, type) and issubclass(_exc, Exception)):
                    raise TypeError("not an exception class: {}".format(_exc))
        else:
            if not (isinstance(exc, type) and issubclass(exc, Exception)):
                raise TypeError("not an exception class: {}".format(exc))
        if not isinstance(max_attempts, int):
            raise TypeError("'max_attempts' must be an int: {}".format(max_attempts))
        if not isinstance(wait, (float, int)):
            raise TypeError("'wait' must be a float: {}".format(max_attempts))
        if not isinstance(stall, (float, int)):
            raise TypeError("'stall' must be a float: {}".format(max_attempts))
        return _retry
