"""Suite-wide guarantee that no test reaches the network.

The socket layer is closed for the duration of every test and a real
connection attempt raises `NetworkAccessDuringTestError` instead, so "no
test calls the network" is enforced rather than trusted. Loopback stays
open since nothing about Google Trends is reachable at 127.0.0.1.
"""

import socket

import pytest

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


class NetworkAccessDuringTestError(RuntimeError):
    """Raised when a test attempts a connection to a non-loopback address."""


def _is_loopback(address) -> bool:
    """True for an address this guard lets through. Non-inet families (AF_UNIX etc.) are always allowed."""
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
