"""The push service the tests serve, and subscriptions made as a browser makes them.

See specs/contracts/test-harness.md ("Push services") and ADR-0101. The
service listens on `127.0.0.1` over HTTPS, with a certificate for the hosts
of ADR-0101 issued by a certificate authority made for the session; the
worker trusts it through `SSL_CERT_FILE` and reaches it through
`TEST_PUSH_ADDRESS` (tests/support/outbound/sitecustomize.py). It answers
`201`, or `410` for a subscription a test says is gone, and records every
request.

A `BrowserSubscription` holds what a browser keeps: the P-256 key pair and the
authentication secret. It decrypts what the instance sends (RFC 8291) and
checks its VAPID signature (RFC 8292).
"""

from __future__ import annotations

import base64
import datetime
import json
import secrets
import ssl
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509.oid import NameOID

# The push services of ADR-0101, as browsers name their endpoints.
FCM = "fcm.googleapis.com"
MOZILLA = "updates.push.services.mozilla.com"
APPLE = "web.push.apple.com"
WINDOWS = "wns2-par02p.notify.windows.com"
PUSH_HOSTS = (FCM, MOZILLA, APPLE, WINDOWS)

_PATHS = {
    FCM: "/fcm/send/{token}",
    MOZILLA: "/wpush/v2/{token}",
    APPLE: "/{token}",
    WINDOWS: "/w/?token={token}",
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def from_b64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


@dataclass(frozen=True)
class Push:
    """One request that reached the push service."""

    host: str
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def endpoint(self) -> str:
        return f"https://{self.host}{self.path}"


class BrowserSubscription:
    """A push subscription as a browser makes it, on one of the hosts of ADR-0101."""

    def __init__(self, host: str = FCM) -> None:
        self.host = host
        self.endpoint = f"https://{host}" + _PATHS.get(host, "/{token}").format(token=secrets.token_urlsafe(24))
        self._key = ec.generate_private_key(ec.SECP256R1())
        self.auth = secrets.token_bytes(16)

    @property
    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )

    def to_json(self) -> dict[str, Any]:
        """As `PushSubscription.toJSON()` gives it."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64url(self.public_key), "auth": b64url(self.auth)}}

    def decrypt(self, push: Push) -> dict[str, Any]:
        """The JSON payload of `push`, encrypted with `aes128gcm` for this subscription (RFC 8291, RFC 8188)."""
        assert push.headers.get("content-encoding") == "aes128gcm", push.headers
        body = push.body
        salt, record_size, key_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        sender = body[21 : 21 + key_length]
        ciphertext = body[21 + key_length :]
        assert len(ciphertext) <= record_size, "a push payload is one record"
        sender_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender)
        shared = self._key.exchange(ec.ECDH(), sender_key)
        ikm = _hkdf(self.auth, shared, b"WebPush: info\x00" + self.public_key + sender, 32)
        key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        padded = AESGCM(key).decrypt(nonce, ciphertext, None)
        end = len(padded.rstrip(b"\x00")) - 1
        assert end >= 0, "the record holds its delimiter"
        assert padded[end] == 2, "the last record ends with the delimiter 0x02"
        return json.loads(padded[:end])


def vapid_claims(push: Push, public_key: str) -> dict[str, Any]:
    """The claims of `push`'s VAPID token, once its signature is checked against `public_key` (RFC 8292)."""
    scheme, _, credentials = push.headers.get("authorization", "").partition(" ")
    assert scheme.lower() == "vapid", push.headers.get("authorization")
    parameters = dict(part.strip().split("=", 1) for part in credentials.split(","))
    assert parameters["k"] == public_key, "the token names the instance's public key"
    header, payload, signature = parameters["t"].split(".")
    assert json.loads(from_b64url(header))["alg"] == "ES256"
    raw = from_b64url(signature)
    assert len(raw) == 64
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), from_b64url(public_key))
    key.verify(
        encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        f"{header}.{payload}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )
    return json.loads(from_b64url(payload))


@dataclass
class PushService:
    """The push service the tests serve: every request it received, and the subscriptions that are gone."""

    address: str = ""
    certificate_authority: Path = field(default_factory=Path)
    _pushes: list[Push] = field(default_factory=list[Push])
    _gone: set[str] = field(default_factory=set[str])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, push: Push) -> int:
        with self._lock:
            self._pushes.append(push)
            return 410 if push.endpoint in self._gone else 201

    def gone(self, subscription: BrowserSubscription) -> None:
        """Answer `410 Gone` for `subscription` from now on, as a push service does once it expires."""
        with self._lock:
            self._gone.add(subscription.endpoint)

    def pushes(self, subscription: BrowserSubscription | None = None) -> list[Push]:
        """What reached the service, for `subscription` or for all."""
        with self._lock:
            pushes = list(self._pushes)
        return pushes if subscription is None else [push for push in pushes if push.endpoint == subscription.endpoint]


def _certificates(directory: Path) -> tuple[Path, Path, Path]:
    """A certificate authority, and a certificate it issues for the push hosts: the CA's file, the cert, the key."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sibillo tests push CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, FCM)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in PUSH_HOSTS]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_file, cert_file, key_file = directory / "ca.pem", directory / "cert.pem", directory / "key.pem"
    ca_file.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return ca_file, cert_file, key_file


def _handler(service: PushService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            host = (self.headers.get("Host") or "").partition(":")[0]
            headers = {name.lower(): value for name, value in self.headers.items()}
            status = service.record(Push(host, self.path, headers, body))
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def start_push_service() -> tuple[PushService, ThreadingHTTPServer]:
    """Serve the push service on a free port of `127.0.0.1`; the caller shuts the server down."""
    directory = Path(tempfile.mkdtemp(prefix="sibillo-push-"))
    ca_file, cert_file, key_file = _certificates(directory)
    service = PushService(certificate_authority=ca_file)
    http = ThreadingHTTPServer(("127.0.0.1", 0), _handler(service))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    http.socket = context.wrap_socket(http.socket, server_side=True)
    service.address = f"127.0.0.1:{http.server_address[1]}"
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return service, http
