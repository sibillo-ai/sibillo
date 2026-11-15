"""Passkeys as a second factor, through the public API.

AUTH-010 and UX-026, as ADR-0065 and ADR-0094 decide; responses as in
specs/contracts/openapi.yaml. Ceremonies are answered by the test suite's
software authenticator (test-harness.md, "Passkeys").
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.passkeys import (
    Authenticator,
    arrange_passkey,
    authenticator,
    b64url,
    finish_sign_in,
    from_b64url,
    register_passkey,
    sign_in_with_passkey,
    start_registration,
    start_sign_in,
)
from tests.support.server import Process, Server, fresh_source


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def device(server: Server) -> Authenticator:
    return authenticator(server)


@pytest.fixture
def enrolled(server: Server, account: Account, device: Authenticator) -> dict[str, Any]:
    """A passkey of `device`, registered by `account`."""
    return register_passkey(server, login(server, account), account, device)


def _passkeys(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as api:
        response = api.get("/me/passkeys")
    assert response.status_code == 200, response.text
    return body(response)


def _add(server: Server, token: str, registration: dict[str, Any], credential: dict[str, Any]) -> Any:
    with server.client(token) as api:
        return api.post(
            "/me/passkeys",
            json={"registration_id": registration["registration_id"], "name": "Laptop", "credential": credential},
        )


def _remove(server: Server, token: str, passkey_id: object, password: str) -> Any:
    with server.client(token) as api:
        return api.post(f"/me/passkeys/{passkey_id}/remove", json={"password": password})


def _password_login(server: Server, account: Account, source: str | None = None) -> Any:
    with server.client(source=source) as api:
        return api.post(
            "/auth/login", json={"username": account.username, "password": account.password, "device_name": "x"}
        )


@pytest.mark.spec("AUTH-010", "UX-026")
def test_a_user_starts_without_passkeys_on_an_instance_that_can_use_them(server: Server, account: Account) -> None:
    assert _passkeys(server, login(server, account)) == {"available": True, "items": []}


@pytest.mark.spec("AUTH-010", "UX-026")
def test_registering_a_passkey_lists_it(server: Server, account: Account, device: Authenticator) -> None:
    token = login(server, account)
    passkey = register_passkey(server, token, account, device, name="Phone")
    assert passkey["name"] == "Phone"
    assert passkey["last_used_at"] is None
    assert _passkeys(server, token) == {"available": True, "items": [passkey]}


@pytest.mark.spec("AUTH-010")
def test_registration_options_bind_the_passkey_to_the_instance_and_never_name_the_username(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    started = start_registration(server, login(server, account), account.password)
    assert started.status_code == 201, started.text
    options = body(started)["options"]
    assert options["rp"]["id"] == "localhost"
    assert from_b64url(options["user"]["id"]) == account.id.bytes
    assert account.username.encode() not in from_b64url(options["user"]["id"])
    assert options["attestation"] == "none"
    assert {entry["alg"] for entry in options["pubKeyCredParams"]} == {-7, -8, -257}
    # The passkeys the user has are excluded, so that a device is not registered twice.
    excluded = [entry["id"] for entry in options["excludeCredentials"]]
    assert excluded == [b64url(next(iter(device.credentials)))]


@pytest.mark.spec("AUTH-010", "UX-026")
def test_any_number_of_passkeys_can_be_registered(server: Server, account: Account) -> None:
    token = login(server, account)
    for name in ("Phone", "Laptop", "Tablet"):
        register_passkey(server, token, account, authenticator(server), name=name)
    assert [item["name"] for item in _passkeys(server, token)["items"]] == ["Phone", "Laptop", "Tablet"]


@pytest.mark.spec("AUTH-010", "UX-026")
def test_registering_needs_the_password_again(server: Server, account: Account) -> None:
    token = login(server, account)
    assert_problem(start_registration(server, token, "not the password"), 403, "auth.invalid_credentials")
    # The session is still valid: a wrong password is not the end of the session.
    assert _passkeys(server, token)["items"] == []


@pytest.mark.spec("AUTH-010")
@pytest.mark.parametrize("problem", ["other-origin", "other-relying-party", "used-twice", "expired", "unknown"])
def test_a_registration_that_does_not_verify_is_rejected(
    database: Database, server: Server, account: Account, device: Authenticator, problem: str
) -> None:
    token = login(server, account)
    started = start_registration(server, token, account.password)
    assert started.status_code == 201, started.text
    registration = body(started)
    match problem:
        case "other-origin":
            credential = device.create(registration["options"], origin="https://phishing.example")
        case "other-relying-party":
            credential = device.create(registration["options"], rp_id="phishing.example")
        case "used-twice":
            credential = device.create(registration["options"])
            assert _add(server, token, registration, credential).status_code == 201
            credential = device.create(registration["options"])
        case "expired":
            with database.superuser() as conn:
                conn.execute(
                    "UPDATE passkey_challenges SET expires_at = now() - interval '1 second' WHERE id = %s",
                    (registration["registration_id"],),
                )
            credential = device.create(registration["options"])
        case _:
            credential = device.create(registration["options"])
            registration = {**registration, "registration_id": str(uuid.uuid4())}
    assert_problem(_add(server, token, registration, credential), 422, "auth.passkey_rejected")
    expected = 1 if problem == "used-twice" else 0
    assert len(_passkeys(server, token)["items"]) == expected


@pytest.mark.spec("AUTH-010")
def test_a_registration_cannot_be_finished_by_another_user(
    database: Database, server: Server, account: Account, device: Authenticator
) -> None:
    registration = body(start_registration(server, login(server, account), account.password))
    other = create_account(database, account.tenant_id)
    other_token = login(server, other)
    response = _add(server, other_token, registration, device.create(registration["options"]))
    assert_problem(response, 422, "auth.passkey_rejected")
    assert _passkeys(server, other_token)["items"] == []


@pytest.mark.spec("AUTH-010")
def test_a_password_alone_no_longer_signs_in_once_the_user_has_a_passkey(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    response = _password_login(server, account)
    assert response.status_code == 200, response.text
    started = body(response)
    assert set(started) == {"sign_in_token", "options"}
    assert len(started["sign_in_token"]) >= 43  # 256 bits, encoded
    assert started["options"]["rpId"] == "localhost"
    # Only the user's own passkeys are allowed.
    assert [entry["id"] for entry in started["options"]["allowCredentials"]] == [b64url(_only(device).id)]
    assert "set-cookie" not in response.headers


@pytest.mark.spec("AUTH-010", "AUTH-004")
def test_the_password_and_a_passkey_create_a_device_session(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    started = start_sign_in(server, account)
    response = finish_sign_in(server, started, device.get(started["options"]))
    assert response.status_code == 201, response.text
    created = body(response)
    assert created["user"]["id"] == str(account.id)
    assert created["session"]["device_name"] == "Phone"
    with server.client(created["token"]) as api:
        assert api.get("/me").status_code == 200
    (passkey,) = _passkeys(server, created["token"])["items"]
    assert passkey["last_used_at"] is not None


@pytest.mark.spec("AUTH-010", "AUTH-005")
def test_the_passkey_step_can_deliver_the_session_as_a_cookie(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    started = start_sign_in(server, account)
    response = finish_sign_in(server, started, device.get(started["options"]), session_delivery="cookie")
    assert response.status_code == 201, response.text
    assert "token" not in body(response)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("sibillo_session=")
    assert "HttpOnly" in cookie


@pytest.mark.spec("AUTH-010")
@pytest.mark.parametrize("problem", ["other-origin", "unknown-passkey", "another-users-passkey", "forged-signature"])
def test_a_passkey_that_does_not_verify_is_refused(
    database: Database,
    server: Server,
    account: Account,
    device: Authenticator,
    enrolled: dict[str, Any],
    problem: str,
) -> None:
    started = start_sign_in(server, account)
    match problem:
        case "other-origin":
            credential = device.get(started["options"], origin="https://phishing.example")
        case "unknown-passkey":
            stranger = authenticator(server)
            stranger.create({"rp": {"id": "localhost"}, "user": {"id": b64url(account.id.bytes)}, "challenge": "x"})
            credential = stranger.get({"challenge": started["options"]["challenge"]}, credential=_only(stranger))
        case "another-users-passkey":
            other = create_account(database, account.tenant_id)
            theirs = authenticator(server)
            register_passkey(server, login(server, other), other, theirs)
            credential = theirs.get({"challenge": started["options"]["challenge"]}, credential=_only(theirs))
        case _:
            credential = device.get(started["options"])
            signature = bytearray(from_b64url(credential["response"]["signature"]))
            signature[-1] ^= 1
            credential["response"]["signature"] = b64url(bytes(signature))
    assert_problem(finish_sign_in(server, started, credential), 401, "auth.invalid_credentials")


def _only(device: Authenticator) -> Any:
    (credential,) = device.credentials.values()
    return credential


@pytest.mark.spec("AUTH-010")
def test_a_sign_in_token_is_used_once_whatever_the_outcome(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    started = start_sign_in(server, account)
    wrong = device.get(started["options"], origin="https://phishing.example")
    assert_problem(finish_sign_in(server, started, wrong), 401, "auth.invalid_credentials")
    # The right passkey after a wrong one needs the password again.
    assert_problem(finish_sign_in(server, started, device.get(started["options"])), 401, "auth.invalid_credentials")

    started = start_sign_in(server, account)
    assert finish_sign_in(server, started, device.get(started["options"])).status_code == 201
    replayed = finish_sign_in(server, started, device.get(started["options"]))
    assert_problem(replayed, 401, "auth.invalid_credentials")


@pytest.mark.spec("AUTH-010")
def test_an_expired_sign_in_token_is_refused(
    database: Database, server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    started = start_sign_in(server, account)
    with database.superuser() as conn:
        conn.execute(
            "UPDATE passkey_challenges SET expires_at = now() - interval '1 second'"
            " WHERE user_id = %s AND purpose = 'sign_in'",
            (account.id,),
        )
    assert_problem(finish_sign_in(server, started, device.get(started["options"])), 401, "auth.invalid_credentials")


@pytest.mark.spec("AUTH-010")
def test_a_signature_counter_that_goes_backwards_is_refused(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    for _ in range(2):
        sign_in_with_passkey(server, account, device)
    started = start_sign_in(server, account)
    assert_problem(
        finish_sign_in(server, started, device.get(started["options"], counter=1)), 401, "auth.invalid_credentials"
    )


@pytest.mark.spec("AUTH-010")
def test_a_signature_counter_that_stays_at_zero_is_accepted(server: Server, account: Account) -> None:
    synced = Authenticator(authenticator(server).origin, counter_step=0)
    register_passkey(server, login(server, account), account, synced)
    for _ in range(2):
        sign_in_with_passkey(server, account, synced)


@pytest.mark.spec("AUTH-010", "AUTH-006")
def test_failed_passkeys_count_as_failed_attempts(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    for _ in range(5):
        started = start_sign_in(server, account)
        wrong = device.get(started["options"], origin="https://phishing.example")
        assert_problem(finish_sign_in(server, started, wrong), 401, "auth.invalid_credentials")
    # The username's limit is reached: refused even with the right password, from a new address.
    response = _password_login(server, account)
    assert_problem(response, 429, "auth.rate_limited")
    assert int(response.headers["retry-after"]) >= 1


@pytest.mark.spec("AUTH-010", "AUTH-006")
def test_the_passkey_step_is_refused_over_the_limits(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    source = fresh_source()
    started = start_sign_in(server, account)
    # Unknown tokens, all from one address, until its limit is reached.
    for _ in range(20):
        unknown = {"sign_in_token": b64url(uuid.uuid4().bytes * 2)}
        response = finish_sign_in(server, unknown, device.get(started["options"]), source=source)
        assert_problem(response, 401, "auth.invalid_credentials")
    response = finish_sign_in(server, started, device.get(started["options"]), source=source)
    assert_problem(response, 429, "auth.rate_limited")
    assert int(response.headers["retry-after"]) >= 1


@pytest.mark.spec("AUTH-010", "AUTH-006")
def test_the_password_that_confirms_a_change_is_rate_limited(server: Server, account: Account) -> None:
    token = login(server, account)
    for _ in range(5):
        assert_problem(start_registration(server, token, "not the password"), 403, "auth.invalid_credentials")
    assert_problem(start_registration(server, token, account.password), 429, "auth.rate_limited")


@pytest.mark.spec("AUTH-010", "UX-026")
def test_removing_ones_own_passkey_needs_the_password(
    server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    token = sign_in_with_passkey(server, account, device)
    assert_problem(_remove(server, token, enrolled["id"], "not the password"), 403, "auth.invalid_credentials")
    assert len(_passkeys(server, token)["items"]) == 1
    assert _remove(server, token, enrolled["id"], account.password).status_code == 204
    assert _passkeys(server, token)["items"] == []
    # Without passkeys, the password alone signs in again.
    assert _password_login(server, account).status_code == 201


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_the_passkeys_of_others_cannot_be_removed(
    database: Database, server: Server, account: Account, enrolled: dict[str, Any]
) -> None:
    for other in (create_account(database, account.tenant_id), create_account(database, create_tenant(database))):
        response = _remove(server, login(server, other), enrolled["id"], other.password)
        assert_problem(response, 404, "resource.not_found")
    assert _password_login(server, account).status_code == 200


@pytest.mark.spec("AUTH-010", "UX-026")
def test_tenant_admins_count_and_remove_the_passkeys_of_a_user(
    database: Database, server: Server, account: Account, device: Authenticator, enrolled: dict[str, Any]
) -> None:
    session = sign_in_with_passkey(server, account, device)
    admin = create_account(database, account.tenant_id, "tenant_admin")
    with server.client(login(server, admin)) as api:
        counted = api.get(f"/tenant/users/{account.id}/passkeys")
        assert counted.status_code == 200, counted.text
        assert body(counted) == {"count": 1}
        assert api.delete(f"/tenant/users/{account.id}/passkeys").status_code == 204
        assert body(api.get(f"/tenant/users/{account.id}/passkeys")) == {"count": 0}
    # The user signs in with their password alone, and their sessions stay open.
    assert _password_login(server, account).status_code == 201
    with server.client(session) as api:
        assert api.get("/me").status_code == 200


@pytest.mark.spec("AUTH-010", "TEN-006")
def test_only_tenant_admins_of_the_users_tenant_reach_their_passkeys(
    database: Database, server: Server, account: Account, enrolled: dict[str, Any]
) -> None:
    member = create_account(database, account.tenant_id)
    with server.client(login(server, member)) as api:
        assert_problem(api.get(f"/tenant/users/{account.id}/passkeys"), 403, "permission.denied")
        assert_problem(api.delete(f"/tenant/users/{account.id}/passkeys"), 403, "permission.denied")
    stranger = create_account(database, create_tenant(database), "tenant_admin")
    with server.client(login(server, stranger)) as api:
        assert_problem(api.get(f"/tenant/users/{account.id}/passkeys"), 404, "resource.not_found")
        assert_problem(api.delete(f"/tenant/users/{account.id}/passkeys"), 404, "resource.not_found")
    assert _password_login(server, account).status_code == 200


@pytest.fixture
def without_origin(server: Server) -> Iterator[Server]:
    """An API of the same instance without `SIBILLO_PUBLIC_ORIGIN` (test-harness.md)."""
    api, origin = server.start_twin_api(without=("SIBILLO_PUBLIC_ORIGIN",))
    try:
        yield _twin(server, api, origin)
    finally:
        api.close()


def _twin(server: Server, api: Process, origin: str) -> Server:
    return Server(base_url=f"{origin}/v1", api=api, worker=server.worker, api_environment=server.api_environment)


@pytest.mark.spec("AUTH-010", "UX-026")
def test_without_an_origin_passkeys_are_unavailable(
    database: Database, without_origin: Server, account: Account
) -> None:
    token = login(without_origin, account)
    assert _passkeys(without_origin, token) == {"available": False, "items": []}
    assert_problem(start_registration(without_origin, token, account.password), 503, "auth.passkeys_unavailable")
    # A user who has passkeys cannot sign in until the operator acts, but can still remove one.
    passkey_id = arrange_passkey(database, account)
    assert_problem(_password_login(without_origin, account), 503, "auth.passkeys_unavailable")
    assert _remove(without_origin, token, passkey_id, account.password).status_code == 204
    assert _password_login(without_origin, account).status_code == 201


@pytest.mark.spec("AUTH-010")
@pytest.mark.parametrize(
    "origin",
    ["sibillo.example.org", "https://sibillo.example.org/app", "http://sibillo.example.org", "ftp://localhost"],
    ids=["no-scheme", "with-path", "insecure", "other-scheme"],
)
def test_an_invalid_origin_stops_the_api(server: Server, origin: str) -> None:
    # The twin API closes itself when it exits instead of serving.
    with pytest.raises(RuntimeError, match="SIBILLO_PUBLIC_ORIGIN"):
        server.start_twin_api(SIBILLO_PUBLIC_ORIGIN=origin)
