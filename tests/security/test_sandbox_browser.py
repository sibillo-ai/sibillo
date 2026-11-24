"""The browser of a sandbox, seen from inside it (SBX-026, ADR-0138).

A sandbox starts no browser until a browser tool is called in it, runs at most
one, which listens on its loopback address only, sends no telemetry, holds no
key, and leaves nothing in the workspace.
"""

from __future__ import annotations

import re
import textwrap

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.approvals import approving
from tests.support.browser import LIBRARY, LOAD, PROCESS, call, chain, command, serve_pages
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, get_run
from tests.support.sandbox import Driver
from tests.support.server import Server

# Every listening TCP socket of the sandbox, by local address, from the kernel's tables.
LISTENING = textwrap.dedent(
    """\
    python3 - <<'EOF'
    import ipaddress
    for name, size in (("/proc/net/tcp", 4), ("/proc/net/tcp6", 16)):
        try:
            lines = open(name).read().splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            fields = line.split()
            if fields[3] != "0A":
                continue
            address, port = fields[1].split(":")
            raw = bytes.fromhex(address)
            raw = b"".join(raw[index : index + 4][::-1] for index in range(0, len(raw), 4))
            print(f"listening {ipaddress.ip_address(raw)} {int(port, 16)}")
    EOF"""
)
# The browser's environment, one variable per line.
ENVIRONMENT = f"tr '\\0' '\\n' < /proc/$(pgrep -x {PROCESS} | head -1)/environ"
# A digest of the workspace's names and sizes.
WORKSPACE = "find /workspace -mindepth 1 -printf '%P %s\\n' | sort | sha256sum | cut -c1-16"


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _browsed(
    server: Server, sandboxes: Driver, account: Account, token: str, model: HarnessModel, *after: str
) -> list[str]:
    """Load the browser, open a page and use it, then run `after`: what the model was told of each call."""
    conversation_id = create_conversation(server, token)["id"]
    base = serve_pages(sandboxes, account, conversation_id, {"library.html": LIBRARY.replace("{opening}", "9:00")})
    text = chain(
        LOAD,
        call("browser_goto", url=f"{base}library.html"),
        call("browser_fill", selector="#q", value="Riverside"),
        call("browser_click", selector="button"),
        *after,
    )
    _, _, last = approving(server, token, conversation_id, text)
    assert get_run(server, token, last)["status"] == "completed"
    return [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]


@pytest.mark.spec("SBX-026")
def test_a_sandbox_starts_no_browser_by_itself(sandboxes: Driver) -> None:
    sandbox = str(uuid7()), str(uuid7()), str(uuid7())
    try:
        sandboxes.ensure(*sandbox, internet_access=True)
        result = sandboxes.sh(*sandbox, f"pgrep -x {PROCESS} || echo no-browser")
        assert result.exit_code == 0, result
        assert result.stdout.strip() == "no-browser"
    finally:
        sandboxes.stop(*sandbox)


@pytest.mark.spec("SBX-026")
def test_the_browser_is_in_the_image_and_sends_no_telemetry(sandboxes: Driver) -> None:
    sandbox = str(uuid7()), str(uuid7()), str(uuid7())
    try:
        # Without network: the browser is in the image, not downloaded.
        sandboxes.ensure(*sandbox, internet_access=False)
        version = sandboxes.sh(*sandbox, f"{PROCESS} version")
        assert version.exit_code == 0, version
        assert re.search(r"\d+\.\d+\.\d+", version.stdout), version
        telemetry = sandboxes.sh(*sandbox, "printenv LIGHTPANDA_DISABLE_TELEMETRY")
        assert telemetry.stdout.strip() == "true", telemetry
    finally:
        sandboxes.stop(*sandbox)


@pytest.mark.spec("SBX-026", "AGT-039")
def test_the_browser_listens_on_loopback_only(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    results = _browsed(server, sandboxes, account, token, default_model, command(LISTENING))
    sockets = re.findall(r"listening (\S+) (\d+)", results[-1])
    # The page server, and the browser.
    assert len(sockets) >= 2, results[-1]
    assert {address for address, _ in sockets} <= {"127.0.0.1", "::1"}, sockets


@pytest.mark.spec("SBX-026", "AGT-039")
def test_a_sandbox_runs_one_browser_without_keys(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    results = _browsed(
        server,
        sandboxes,
        account,
        token,
        default_model,
        call("browser_goto", url="http://127.0.0.1:8765/library.html"),
        command(f"echo browsers=$(pgrep -x -c {PROCESS})"),
        command(ENVIRONMENT),
    )
    assert "browsers=1" in results[-2]
    environment = results[-1]
    assert "LIGHTPANDA_DISABLE_TELEMETRY=true" in environment
    # No key of any service, and no credential (SBX-008).
    assert not re.search(r"^[A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=", environment, re.MULTILINE)
    assert not re.search(r"^LP_", environment, re.MULTILINE)


@pytest.mark.spec("SBX-026", "AGT-039")
def test_browsing_keeps_nothing_in_the_workspace(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    base = serve_pages(sandboxes, account, conversation_id, {"library.html": LIBRARY.replace("{opening}", "9:00")})
    text = chain(
        command(WORKSPACE),
        LOAD,
        call("browser_goto", url=f"{base}library.html"),
        call("browser_fill", selector="#q", value="Riverside"),
        call("browser_click", selector="button"),
        command(WORKSPACE),
    )
    _, _, last = approving(server, token, conversation_id, text)
    assert get_run(server, token, last)["status"] == "completed"
    results = [
        str(message.get("content", ""))
        for request in default_model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    before, after = (re.findall(r"\b[0-9a-f]{16}\b", results[index]) for index in (0, -1))
    assert before, results[0]
    assert before == after, (results[0], results[-1])
