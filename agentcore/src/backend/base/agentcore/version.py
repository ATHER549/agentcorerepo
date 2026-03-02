
import contextlib
from importlib import metadata


def get_version() -> str:
    """Retrieves the version of the from a possible list of names.
    """
    names = [
        "agentcore",
    ]
    version = None
    for pkg_name in names:
        with contextlib.suppress(ImportError, metadata.PackageNotFoundError):
            version = metadata.version(pkg_name)

    if version is None:
        msg = f"Package not found from options {names}"
        raise ValueError(msg)

    return version


def is_pre_release(v: str) -> bool:
    """Returns a boolean indicating whether the version is a pre-release version.

    Returns a boolean indicating whether the version is a pre-release version,
    as per the definition of a pre-release segment from PEP 440.
    """
    return any(label in v for label in ["a", "b", "rc"])
