"""A software authenticator for WebAuthn ceremonies, and the API calls tests make with it.

See specs/contracts/test-harness.md ("Passkeys"), AUTH-010 and ADR-0094. The
authenticator makes ES256 (ECDSA over P-256 with SHA-256) keys, answers
registrations with attestation `none` and assertions with a signature
counter, encoded as WebAuthn Level 3's JSON forms. It is written with the
standard library only, so that tests depend on no WebAuthn library of the
server's.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
import uuid
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from tests.support.accounts import Account, body
from tests.support.database import Database, uuid7
from tests.support.server import Server

# NIST P-256 (FIPS 186-4, D.1.2.3).
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (
    0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
    0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5,
)

Point = tuple[int, int] | None

# Flags of authenticator data (WebAuthn Level 3, 6.1).
USER_PRESENT, USER_VERIFIED, ATTESTED_CREDENTIAL = 0x01, 0x04, 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _add(one: Point, two: Point) -> Point:
    if one is None:
        return two
    if two is None:
        return one
    (x1, y1), (x2, y2) = one, two
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    tangent = one == two
    numerator, denominator = (3 * x1 * x1 + _A, 2 * y1) if tangent else (y2 - y1, x2 - x1)
    slope = numerator * pow(denominator, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def _multiply(scalar: int, point: Point) -> Point:
    result: Point = None
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _der_integer(value: int) -> bytes:
    encoded = value.to_bytes((value.bit_length() + 8) // 8, "big")
    return b"\x02" + bytes([len(encoded)]) + encoded


def _sign(private_key: int, message: bytes) -> bytes:
    """An ECDSA signature of `message` with SHA-256, DER-encoded as WebAuthn's ES256 is."""
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        k = secrets.randbelow(_N - 1) + 1
        point = _multiply(k, _G)
        assert point is not None
        r = point[0] % _N
        s = pow(k, -1, _N) * (digest + r * private_key) % _N
        if r and s:
            sequence = _der_integer(r) + _der_integer(s)
            return b"\x30" + bytes([len(sequence)]) + sequence


def _cbor_head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([major << 5 | value])
    for extra, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if value < 1 << (8 * size):
            return bytes([major << 5 | extra]) + value.to_bytes(size, "big")
    raise ValueError(value)


def cbor(value: object) -> bytes:
    """CBOR (RFC 8949) of the values WebAuthn needs: integers, bytes, text, lists and maps."""
    match value:
        case bool():
            return b"\xf5" if value else b"\xf4"
        case int() if value >= 0:
            return _cbor_head(0, value)
        case int():
            return _cbor_head(1, -1 - value)
        case bytes():
            return _cbor_head(2, len(value)) + value
        case str():
            encoded = value.encode()
            return _cbor_head(3, len(encoded)) + encoded
        case list():
            items = cast("list[object]", value)
            return _cbor_head(4, len(items)) + b"".join(cbor(item) for item in items)
        case dict():
            entries = cast("dict[object, object]", value)
            return _cbor_head(5, len(entries)) + b"".join(cbor(key) + cbor(item) for key, item in entries.items())
        case _:
            raise TypeError(type(value))


@dataclass
class Credential:
    """A passkey the authenticator holds."""

    id: bytes
    private_key: int
    rp_id: str
    user_handle: bytes
    counter: int = 0

    def cose_key(self) -> bytes:
        point = _multiply(self.private_key, _G)
        assert point is not None
        x, y = point
        # kty EC2, alg ES256, crv P-256 (RFC 9053).
        return cbor({1: 2, 3: -7, -1: 1, -2: x.to_bytes(32, "big"), -3: y.to_bytes(32, "big")})


def _client_data(kind: str, challenge: str, origin: str) -> bytes:
    return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()


@dataclass
class Authenticator:
    """A platform authenticator answering for `origin`, whose host is the relying party ID by default.

    Its signature counter goes up by `counter_step` on each assertion; many
    passkeys that sync keep it at zero.
    """

    origin: str
    counter_step: int = 1
    credentials: dict[bytes, Credential] = field(default_factory=dict[bytes, Credential])

    @property
    def rp_id(self) -> str:
        host = urlsplit(self.origin).hostname
        assert host is not None
        return host

    def create(self, options: dict[str, Any], *, origin: str | None = None, rp_id: str | None = None) -> dict[str, Any]:
        """Answer `navigator.credentials.create` with `PublicKeyCredentialCreationOptionsJSON` `options`."""
        relying_party = rp_id or options["rp"].get("id") or self.rp_id
        credential = Credential(
            id=secrets.token_bytes(32),
            private_key=secrets.randbelow(_N - 1) + 1,
            rp_id=relying_party,
            user_handle=from_b64url(options["user"]["id"]),
        )
        self.credentials[credential.id] = credential
        attested = bytes(16) + struct.pack(">H", len(credential.id)) + credential.id + credential.cose_key()
        authenticator_data = (
            hashlib.sha256(relying_party.encode()).digest()
            + bytes([USER_PRESENT | USER_VERIFIED | ATTESTED_CREDENTIAL])
            + struct.pack(">I", credential.counter)
            + attested
        )
        attestation = cbor({"fmt": "none", "attStmt": {}, "authData": authenticator_data})
        client_data = _client_data("webauthn.create", options["challenge"], origin or self.origin)
        return {
            "id": b64url(credential.id),
            "rawId": b64url(credential.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal"],
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        counter: int | None = None,
        credential: Credential | None = None,
    ) -> dict[str, Any]:
        """Answer `navigator.credentials.get` with `PublicKeyCredentialRequestOptionsJSON` `options`.

        Uses the first allowed passkey the authenticator holds, or `credential`;
        `counter` sends that counter instead of the next one.
        """
        if credential is None:
            allowed = [from_b64url(entry["id"]) for entry in options.get("allowCredentials", [])]
            held = [self.credentials[key] for key in allowed if key in self.credentials]
            assert held, "the authenticator holds none of the allowed passkeys"
            credential = held[0]
        credential.counter = credential.counter + self.counter_step if counter is None else counter
        authenticator_data = (
            hashlib.sha256(credential.rp_id.encode()).digest()
            + bytes([USER_PRESENT | USER_VERIFIED])
            + struct.pack(">I", credential.counter)
        )
        client_data = _client_data("webauthn.get", options["challenge"], origin or self.origin)
        signature = _sign(credential.private_key, authenticator_data + hashlib.sha256(client_data).digest())
        return {
            "id": b64url(credential.id),
            "rawId": b64url(credential.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(authenticator_data),
                "signature": b64url(signature),
                "userHandle": b64url(credential.user_handle),
            },
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
        }


def authenticator(server: Server) -> Authenticator:
    """An authenticator for the origin the API is given (test-harness.md)."""
    assert server.public_origin is not None
    return Authenticator(server.public_origin)


def start_registration(server: Server, token: str, password: str) -> httpx.Response:
    with server.client(token) as api:
        return api.post("/me/passkeys/registrations", json={"password": password})


def register_passkey(
    server: Server, token: str, account: Account, device: Authenticator, name: str = "Phone"
) -> dict[str, Any]:
    """Register a passkey of `device` for the signed-in `account`, through the API."""
    started = start_registration(server, token, account.password)
    assert started.status_code == 201, started.text
    registration = body(started)
    with server.client(token) as api:
        response = api.post(
            "/me/passkeys",
            json={
                "registration_id": registration["registration_id"],
                "name": name,
                "credential": device.create(registration["options"]),
            },
        )
    assert response.status_code == 201, response.text
    return body(response)


def start_sign_in(server: Server, account: Account, source: str | None = None) -> dict[str, Any]:
    """The password step of a sign-in for a user who has passkeys: the sign-in token and options."""
    with server.client(source=source) as api:
        response = api.post(
            "/auth/login",
            json={"username": account.username, "password": account.password, "device_name": "Phone"},
        )
    assert response.status_code == 200, response.text
    return body(response)


def finish_sign_in(
    server: Server,
    started: dict[str, Any],
    credential: dict[str, Any],
    source: str | None = None,
    **extra: str,
) -> httpx.Response:
    with server.client(source=source) as api:
        return api.post(
            "/auth/login/passkey",
            json={"sign_in_token": started["sign_in_token"], "credential": credential, "device_name": "Phone", **extra},
        )


def sign_in_with_passkey(server: Server, account: Account, device: Authenticator) -> str:
    """Sign in with the password and a passkey of `device`; the session token."""
    started = start_sign_in(server, account)
    response = finish_sign_in(server, started, device.get(started["options"]))
    assert response.status_code == 201, response.text
    token = body(response)["token"]
    assert isinstance(token, str)
    return token


def arrange_passkey(database: Database, account: Account | Any, name: str = "Arranged") -> uuid.UUID:
    """A passkey of `account` in the database, arranged as superuser; no device holds its key."""
    passkey_id = uuid7()
    with database.superuser() as conn:
        conn.execute(
            "INSERT INTO passkeys (id, tenant_id, user_id, credential_id, public_key, sign_count, name, created_at)"
            " VALUES (%s, %s, %s, %s, %s, 0, %s, now())",
            (passkey_id, account.tenant_id, account.id, secrets.token_bytes(32), b"not a key", name),
        )
    return passkey_id
