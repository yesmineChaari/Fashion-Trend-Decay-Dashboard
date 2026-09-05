"""Suite-wide guarantee that no test reaches the network.

Every ingestion test in this suite is written against a mock, a recorded
fixture, or the on-disk cache — but "written against" is not the same as
"provably didn't call out". A test that silently starts hitting Google
Trends would be slow, flaky, subject to rate limiting, and worst of all
would pass or fail depending on what Google returned that day, quietly
turning a deterministic assertion into a sampled one.

So the socket layer is closed for the duration of every test and a real
connection attempt raises `NetworkAccessDuringTestError` instead: the
acceptance criterion "a network call attempted during tests is a test
failure" is enforced here rather than trusted. Loopback stays open, since
blocking it would break unrelated local machinery (a debugger, a
multiprocessing pipe) without protecting anything — nothing about Google
Trends is reachable at 127.0.0.1.
"""

import socket

import pytest

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


class NetworkAccessDuringTestError(RuntimeError):
    """Raised when a test attempts a connection to a non-loopback address."""


def _is_loopback(address) -> bool:
    """True for an address this guard lets through.

    Non-inet families (AF_UNIX and friends) are allowed: they can't reach
    Google Trends, and the address isn't a `(host, port)` tuple to inspect.
    """
    if not isinstance(address, tuple) or not address:
        return True
    host = address[0]
    return isinstance(host, str) and host in LOOPBACK_HOSTS


def _guard(original, name):
    def guarded(*args, **kwargs):
        address = kwargs.get("address", args[-1] if args else None)
        if _is_loopback(address):
            return original(*args, **kwargs)
        raise NetworkAccessDuringTestError(
            f"{name} to {address!r} was attempted during a test. This suite runs "
            "offline: fetch through a mocked client, a recorded fixture "
            "(Settings.fixture_mode), or the on-disk cache instead."
        )

    return guarded


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail any test that opens a connection to somewhere other than loopback."""
    monkeypatch.setattr(socket.socket, "connect", _guard(socket.socket.connect, "socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard(socket.socket.connect_ex, "socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _guard(socket.create_connection, "socket.create_connection"))
