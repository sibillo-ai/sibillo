"""Request bodies are bounded before any operation runs (API-009, ADR-0119, T-14, T-15).

Anyone who reaches the API can send a body; it is refused once it passes its
limit, declared or counted, before the session that sends it is checked.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.server import Server

MIB = 1024 * 1024


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


def _login_body(size: int) -> bytes:
    """A sign-in whose free-form WebAuthn object makes the body `size` bytes or a little more."""
    document = {"sign_in_token": "x", "device_name": "x", "credential": {"padding": "a" * size}}
    return json.dumps(document).encode()


def _chunks(data: bytes, size: int = 64 * 1024) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.mark.spec("API-009")
def test_a_body_over_1_mib_is_refused_before_signing_in(server: Server) -> None:
    oversized = _login_body(MIB + 1)
    with server.client() as client:
        # Declared: refused by its length.
        declared = client.post("/auth/login/passkey", content=oversized, headers={"Content-Type": "application/json"})
        assert_problem(declared, 413, "request.too_large")
        # Undeclared, sent in chunks: refused as it is counted.
        counted = client.post(
            "/auth/login/passkey", content=_chunks(oversized), headers={"Content-Type": "application/json"}
        )
        assert_problem(counted, 413, "request.too_large")
        # Under the limit, the operation runs and answers for itself.
        within = client.post(
            "/auth/login/passkey", content=_login_body(MIB // 2), headers={"Content-Type": "application/json"}
        )
        assert_problem(within, 401, "auth.invalid_credentials")


@pytest.mark.spec("API-009")
def test_a_skill_file_has_a_larger_limit_of_its_own(server: Server, account: Account) -> None:
    token = login(server, account)
    name = f"big-{secrets.token_hex(3)}"
    skill_md = f"---\nname: {name}\ndescription: Use for big notes.\n---\n\nRead notes.md.\n"
    with server.client(token) as client:
        created = client.post("/me/skills", json={"skill_md": skill_md})
        assert created.status_code == 201, created.text
        path = f"/me/skills/{body(created)['id']}/file"
        # A million quotes, escaped in JSON, make a body of about 2 MB: within the operation's own limit.
        quoted = json.dumps({"text": '"' * 1_000_000, "executable": False}).encode()
        assert len(quoted) > MIB
        written = client.put(
            path, params={"path": "notes.md"}, content=quoted, headers={"Content-Type": "application/json"}
        )
        assert written.status_code == 200, written.text
        # Over it, refused like any other.
        refused = client.put(
            path,
            params={"path": "notes.md"},
            content=b'{"text": "' + b"a" * (8 * MIB) + b'"}',
            headers={"Content-Type": "application/json"},
        )
        assert_problem(refused, 413, "request.too_large")
