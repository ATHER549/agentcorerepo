from collections.abc import Callable
from datetime import datetime


def encode_callable(obj: Callable):
    return obj.__name__ if hasattr(obj, "__name__") else str(obj)


def encode_datetime(obj: datetime):
    # Include fractional seconds for proper message ordering
    return obj.strftime("%Y-%m-%d %H:%M:%S.%f %Z")


CUSTOM_ENCODERS = {Callable: encode_callable, datetime: encode_datetime}
