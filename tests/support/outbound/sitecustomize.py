"""Records the outbound connections of the processes the test harness starts (OBS-006, ADR-0072).

The harness puts this directory on `PYTHONPATH` and names a file in
`TEST_OUTBOUND_LOG`; Python imports `sitecustomize` when it starts, and the
audit hook below appends one JSON line per connection and per name lookup.
Unix sockets are local and not recorded.
"""

import json
import os
import sys
from typing import cast

_LOG = os.environ.get("TEST_OUTBOUND_LOG")


def _write(entry: dict[str, object]) -> None:
    line = (json.dumps(entry) + "\n").encode()
    descriptor = os.open(_LOG or os.devnull, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def _hook(event: str, args: tuple[object, ...]) -> None:
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple):
            host, port = cast(tuple[object, ...], address)[:2]
            _write({"connect": str(host), "port": port, "pid": os.getpid()})
    elif event == "socket.getaddrinfo":
        _write({"resolve": str(args[0]), "pid": os.getpid()})


if _LOG:
    sys.addaudithook(_hook)


# The push service the tests serve stands in for the push services of ADR-0101
# (specs/contracts/test-harness.md, "Push services"): lookups of their hosts
# answer its address, and connections to them on port 443 reach its port.
_PUSH = os.environ.get("TEST_PUSH_ADDRESS")
_PUSH_DOMAINS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")


def _is_push_host(host: object) -> bool:
    name = str(host).rstrip(".").lower()
    return name in _PUSH_DOMAINS or name.endswith(".notify.windows.com")


if _PUSH:
    import socket
    from typing import Any

    import anyio

    _push_host, _, _push_port = _PUSH.rpartition(":")
    _getaddrinfo: Any = socket.getaddrinfo
    _connect_tcp: Any = anyio.connect_tcp

    def _push_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_push_host(host):
            host, port = _push_host, (int(_push_port) if str(port) == "443" else port)
        return _getaddrinfo(host, port, *args, **kwargs)

    async def _push_connect_tcp(remote_host: Any, remote_port: int, *args: Any, **kwargs: Any) -> Any:
        if _is_push_host(remote_host) and remote_port == 443:
            remote_host, remote_port = _push_host, int(_push_port)
        return await _connect_tcp(remote_host, remote_port, *args, **kwargs)

    setattr(socket, "getaddrinfo", _push_getaddrinfo)  # noqa: B010 - replaced for the whole process
    setattr(anyio, "connect_tcp", _push_connect_tcp)  # noqa: B010 - replaced for the whole process
