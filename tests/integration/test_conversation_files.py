"""A conversation's workspace through the API: browsing, previews, uploads, attachments and offers.

(UX-019, UX-020, CNV-017, CNV-020, AGT-023, ART-001, ART-002, ART-003, SBX-014, SBX-019, TEN-006, ADR-0079,
ADR-0086, ADR-0110.)

The control plane never decodes an image, so the images of these tests are a
format's first bytes followed by anything; the served model answers `images?`
with the images its request holds, and `look:<path>` by calling `view_image`
first (tests/support/model.py).
"""

from __future__ import annotations

import base64
import io
import json
import secrets
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import saw
from tests.support.runs import create_conversation, messages, run_input, start_run, text_of, wait_for_run
from tests.support.sandbox import WORKSPACE_QUOTA_BYTES
from tests.support.server import Server, fresh_source


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


BINARY = {"Content-Type": "application/octet-stream"}


def _workspace(conversation_id: str) -> str:
    return f"/conversations/{conversation_id}/workspace"


def _put(client: httpx.Client, conversation_id: str, path: str, data: bytes) -> httpx.Response:
    return client.put(f"{_workspace(conversation_id)}/file", params={"path": path}, content=data, headers=BINARY)


def _upload(client: httpx.Client, conversation_id: str, name: str, data: bytes) -> httpx.Response:
    return client.post(f"{_workspace(conversation_id)}/uploads", params={"name": name}, content=data, headers=BINARY)


@pytest.mark.spec("UX-019", "SBX-014")
def test_the_workspace_is_browsed_and_managed_through_the_api(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "notes/todo.md", b"# To do\n").status_code == 201
        assert client.post(f"{_workspace(conversation)}/folders", json={"path": "drafts"}).status_code == 201
        listed = client.get(f"{_workspace(conversation)}/entries", params={"path": ""})
        assert listed.status_code == 200, listed.text
        assert [entry["name"] for entry in listed.json()["entries"]] == ["drafts", "notes"]
        moved = client.post(f"{_workspace(conversation)}/move", json={"from": "notes/todo.md", "to": "drafts/todo.md"})
        assert moved.status_code == 200, moved.text
        summary = client.get(_workspace(conversation)).json()
        assert summary["quota"] == WORKSPACE_QUOTA_BYTES
        assert summary["size"] >= 8
        zipped = client.get(f"{_workspace(conversation)}/archive", params={"path": "drafts"})
        assert zipped.status_code == 200
        assert "attachment" in zipped.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
            assert archive.read("todo.md") == b"# To do\n"
        assert client.delete(f"{_workspace(conversation)}/entries", params={"path": "notes"}).status_code == 204
        assert client.delete(_workspace(conversation)).status_code == 204
        emptied = client.get(f"{_workspace(conversation)}/entries", params={"path": ""}).json()
    assert emptied["entries"] == []


@pytest.mark.spec("UX-019", "TEN-006", "ART-004")
def test_only_the_owner_reaches_a_conversations_workspace(
    database: Database, server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "private.txt", b"mine").status_code == 201
    other = create_account(database, create_tenant(database))
    with server.client(login(server, other)) as client:
        assert client.get(f"{_workspace(conversation)}/entries", params={"path": ""}).status_code == 404
        assert client.get(f"{_workspace(conversation)}/file", params={"path": "private.txt"}).status_code == 404
        assert _put(client, conversation, "planted.txt", b"x").status_code == 404


@pytest.mark.spec("UX-020")
@pytest.mark.parametrize(
    ("name", "data", "preview_type"),
    [
        ("notes.txt", b"plain notes", "text/plain"),
        ("page.html", b"<script>alert(1)</script>", "text/plain"),
        ("readme.md", b"# Title", "text/markdown"),
        ("table.csv", b"a,b\n1,2\n", "text/csv"),
        ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml"),
        ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png"),
        ("program.exe", b"MZ\x90\x00", None),
    ],
    ids=["text", "html", "markdown", "csv", "svg", "png", "binary"],
)
def test_files_are_downloaded_as_attachments_and_previewed_only_as_safe_types(
    server: Server, token: str, name: str, data: bytes, preview_type: str | None
) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, name, data).status_code == 201
        download = client.get(f"{_workspace(conversation)}/file", params={"path": name})
        preview = client.get(f"{_workspace(conversation)}/file", params={"path": name, "preview": "true"})
    assert download.status_code == 200
    assert download.content == data
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["content-type"].startswith("application/octet-stream")
    assert download.headers["x-content-type-options"] == "nosniff"
    if preview_type is None:
        assert preview.status_code == 415
        assert preview.json()["code"] == "file.not_previewable"
    else:
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].split(";")[0] == preview_type
        assert preview.headers["x-content-type-options"] == "nosniff"
        assert "text/html" not in preview.headers["content-type"]
        # Opened by itself, as from a link, it runs nothing in the app's origin (T-22).
        assert "sandbox" in preview.headers["content-security-policy"]


@pytest.mark.spec("UX-020")
def test_a_text_preview_stops_at_one_mebibyte(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "big.log", b"l" * (2 * 1024 * 1024)).status_code == 201
        preview = client.get(f"{_workspace(conversation)}/file", params={"path": "big.log", "preview": "true"})
    assert preview.status_code == 200
    assert len(preview.content) == 1024 * 1024


@pytest.mark.spec("CNV-017")
def test_attachments_never_replace_a_file(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        first = _upload(client, conversation, "budget.csv", b"one")
        second = _upload(client, conversation, "budget.csv", b"two")
        third = _upload(client, conversation, "../budget.csv", b"three")
    assert first.status_code == 201, first.text
    assert first.json()["path"] == "uploads/budget.csv"
    assert second.json()["path"] == "uploads/budget (2).csv"
    # A name is only a name: never a path.
    assert third.status_code in {201, 422}
    if third.status_code == 201:
        assert third.json()["path"].startswith("uploads/")


@pytest.mark.spec("CNV-017")
def test_the_model_reads_the_attachments_of_a_message(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        path = _upload(client, conversation, "receipt.pdf", b"%PDF-1.4 fake").json()["path"]
    text = f"what is in it {secrets.token_hex(4)}"
    payload = run_input(conversation, text) | {"attachments": [path]}
    with server.client(token) as client:
        response = client.post(f"/conversations/{conversation}/runs", json=payload)
        assert response.status_code == 200, response.text
    run_id = str(payload["runId"])
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    request_texts = [
        json.dumps(request.body) for request in default_model.endpoint.requests if text in json.dumps(request.body)
    ]
    assert request_texts, "the model received no request"
    # The answer's request has them; the title's needs only the text.
    assert any("uploads/receipt.pdf" in body for body in request_texts)
    history = messages(server, token, conversation)
    (user,) = [message for message in history["items"] if message["role"] == "user"]
    assert user["attachments"] == [{"path": "uploads/receipt.pdf", "size": 13}]
    assert user["content"] == text


@pytest.mark.spec("CNV-017")
@pytest.mark.parametrize(
    "path", ["notes.txt", "uploads/missing.pdf", "../etc/passwd"], ids=["outside-uploads", "missing", "escape"]
)
def test_only_uploaded_files_can_be_attached(server: Server, token: str, path: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "notes.txt", b"n").status_code == 201
        payload = run_input(conversation, "with a wrong attachment") | {"attachments": [path]}
        response = client.post(f"/conversations/{conversation}/runs", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.spec("CNV-017", "SBX-019")
def test_uploads_are_limited_by_size_and_quota(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        over_quota = _upload(client, conversation, "huge.bin", b"x" * (WORKSPACE_QUOTA_BYTES + 1024))
    assert over_quota.status_code == 413
    assert over_quota.json()["code"] == "workspace.quota_exceeded"
    api, origin = server.start_twin_api(SIBILLO_UPLOAD_MAX_MB="1")
    try:
        too_large = httpx.post(
            f"{origin}/v1{_workspace(conversation)}/uploads",
            params={"name": "two-mib.bin"},
            content=b"x" * (2 * 1024 * 1024),
            headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": fresh_source(), **BINARY},
            timeout=60,
        )
    finally:
        api.close()
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "file.too_large"


def _tool_result(model: HarnessModel, text: str) -> str:
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


@pytest.mark.spec("AGT-023")
def test_the_agent_offers_a_file_of_the_workspace(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "report.pdf", b"%PDF report").status_code == 201
    text = 'tool:offer_download {"path": "report.pdf"}'
    run_id, events = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "report.pdf" in _tool_result(default_model, text)
    calls = [event for event in events if event.type == "TOOL_CALL_START"]
    assert [event.data.get("toolCallName") for event in calls] == ["offer_download"]
    # The offer stays in history, where clients show it as a card.
    history = messages(server, token, conversation)["items"]
    offers: list[Any] = [
        call
        for message in history
        if message["role"] == "assistant"
        for call in message.get("toolCalls", [])
        if call["function"]["name"] == "offer_download"
    ]
    assert offers


@pytest.mark.spec("AGT-023")
@pytest.mark.parametrize("path", ["missing.pdf", "../../etc/passwd"], ids=["missing", "escape"])
def test_an_offer_of_a_file_that_is_not_there_is_told_to_the_model(
    server: Server, token: str, default_model: HarnessModel, path: str
) -> None:
    conversation = create_conversation(server, token)["id"]
    text = f"tool:offer_download {json.dumps({'path': path})}"
    run_id, _ = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    result = _tool_result(default_model, text).lower()
    assert "not" in result
    assert "root:" not in result


@pytest.mark.spec("ART-003")
def test_a_web_page_is_served_to_run_in_an_opaque_origin_without_network(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    page = b"<!doctype html><title>Planner</title><script>document.title = 'ran'</script>"
    with server.client(token) as client:
        assert _put(client, conversation, "site/planner.html", page).status_code == 201
        assert _put(client, conversation, "notes.txt", b"plain").status_code == 201
        file = f"{_workspace(conversation)}/file"
        served = client.get(file, params={"path": "site/planner.html", "page": "true"})
        refused = client.get(file, params={"path": "notes.txt", "page": "true"})
        preview = client.get(file, params={"path": "site/planner.html", "preview": "true"})
    assert served.status_code == 200, served.text
    assert served.content == page
    assert served.headers["content-type"].split(";")[0] == "text/html"
    assert served.headers["x-content-type-options"] == "nosniff"
    policy = {
        name: values
        for directive in served.headers["content-security-policy"].split(";")
        if directive.strip()
        for name, *values in [directive.split()]
    }
    # An opaque origin: scripts run, as a stranger to the app's origin.
    assert policy["sandbox"] == ["allow-scripts"]
    # No network: inline code and styles, data and blobs, nothing from any address.
    assert policy["default-src"] == ["'none'"]
    for directive, values in policy.items():
        for value in values:
            assert value in {"'none'", "'unsafe-inline'", "'unsafe-eval'", "data:", "blob:", "allow-scripts"}, (
                directive,
                value,
            )
    assert refused.status_code == 415
    assert refused.json()["code"] == "file.not_previewable"
    # Without `page`, an HTML file still previews as its source only.
    assert preview.headers["content-type"].split(";")[0] == "text/plain"


@pytest.mark.spec("ART-002")
def test_the_agent_is_told_how_to_make_pages_and_diagrams(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)["id"]
    text = f"instructions {secrets.token_hex(4)}"
    run_id, _ = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(text)[:1]
    system = request.system_text()
    for phrase in ("self-contained", "Mermaid", ".mmd", "offer_download"):
        assert phrase in system, f"the instructions do not mention {phrase}"


# The largest image that reaches the model (ADR-0110).
IMAGE_MAX_BYTES = 5 * 1024 * 1024


def _png(size: int = 64) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + secrets.token_bytes(size - 8)


def _jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + secrets.token_bytes(60)


def _gif() -> bytes:
    return b"GIF89a" + secrets.token_bytes(58)


def _webp() -> bytes:
    return b"RIFF" + (56).to_bytes(4, "little") + b"WEBP" + secrets.token_bytes(52)


@dataclass(frozen=True)
class Household:
    account: Account
    token: str
    model: HouseholdModel


@pytest.fixture
def household(database: Database, server: Server, default_model: HarnessModel) -> Household:
    """A household whose default model is not known to accept images."""
    account = create_account(database, create_tenant(database))
    return Household(account, login(server, account), default_model.connect(account.tenant_id))


@pytest.fixture
def seeing(server: Server, household: Household) -> Household:
    """The household, once its admin said that its default model accepts images (MOD-020)."""
    with server.client(household.model.admin_token) as client:
        response = client.patch(
            f"/tenant/connections/{household.model.connection_id}", json={"image_models": ["test-model"]}
        )
    assert response.status_code == 200, response.text
    return household


def _attach(client: httpx.Client, conversation_id: str, name: str, data: bytes) -> str:
    response = client.post(
        f"/conversations/{conversation_id}/workspace/uploads", params={"name": name}, content=data, headers=BINARY
    )
    assert response.status_code == 201, response.text
    path: str = response.json()["path"]
    return path


def _ask(
    server: Server,
    token: str,
    conversation_id: str,
    text: str,
    attachments: list[str] | None = None,
    parent_run_id: str | None = None,
) -> tuple[str, str]:
    """Send a message with its attachments; the run's ID and the assistant's answer."""
    payload = run_input(conversation_id, text, parent_run_id=parent_run_id) | {"attachments": attachments or []}
    with server.client(token) as client:
        response = client.post(f"/conversations/{conversation_id}/runs", json=payload)
        assert response.status_code == 200, response.text
    run_id = str(payload["runId"])
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    answers = [m for m in messages(server, token, conversation_id)["items"] if m["role"] == "assistant"]
    return run_id, str(answers[-1]["content"])


def _request_of(model: HouseholdModel, text: str) -> str:
    """The body of the request that answered the message holding `text`, as JSON."""
    bodies = [json.dumps(request.body) for request in model.endpoint.requests if request.body.get("tools")]
    (found,) = [body for body in bodies if text in body][-1:]
    return found


@pytest.mark.spec("CNV-020")
def test_an_attached_image_reaches_a_model_that_accepts_images(
    database: Database, server: Server, seeing: Household
) -> None:
    conversation = create_conversation(server, seeing.token)["id"]
    photo = _png()
    with server.client(seeing.token) as client:
        path = _attach(client, conversation, "photo.png", photo)
    text = f"images? {secrets.token_hex(4)}"
    _, answer = _ask(server, seeing.token, conversation, text, [path])
    assert answer == saw([photo])
    # Its path and size are still listed (CNV-017).
    assert "uploads/photo.png" in _request_of(seeing.model, text)
    # The history keeps where the image is, never the image (ADR-0110).
    encoded = base64.b64encode(photo).decode()[:40]
    with database.superuser() as conn:
        stored = conn.execute(
            "SELECT count(*) FROM conversation_messages WHERE conversation_id = %s AND message::text LIKE %s",
            (conversation, f"%{encoded}%"),
        ).fetchone()
        assert stored == (0,)
        checkpoints = conn.execute(
            "SELECT count(*) FROM compaction_checkpoints WHERE conversation_id = %s AND messages::text LIKE %s",
            (conversation, f"%{encoded}%"),
        ).fetchone()
        assert checkpoints == (0,)
    history = messages(server, seeing.token, conversation)
    (user,) = [message for message in history["items"] if message["role"] == "user"]
    assert user["content"] == text
    assert user["attachments"] == [{"path": "uploads/photo.png", "size": len(photo)}]


@pytest.mark.spec("CNV-020")
def test_an_image_is_told_by_its_bytes_and_bounded_by_its_size(server: Server, seeing: Household) -> None:
    conversation = create_conversation(server, seeing.token)["id"]
    jpeg, gif, webp = _jpeg(), _gif(), _webp()
    with server.client(seeing.token) as client:
        attachments = [
            # Not an image, whatever its name says.
            _attach(client, conversation, "notes.png", b"just some text, named as an image"),
            # Images, whatever their names say.
            _attach(client, conversation, "scan.dat", jpeg),
            _attach(client, conversation, "moving", gif),
            _attach(client, conversation, "picture.webp", webp),
            # Too large to send: it stays a path.
            _attach(client, conversation, "huge.png", _png(IMAGE_MAX_BYTES + 1)),
        ]
    text = f"images? {secrets.token_hex(4)}"
    _, answer = _ask(server, seeing.token, conversation, text, attachments)
    assert answer == saw([jpeg, gif, webp])
    assert "uploads/huge.png" in _request_of(seeing.model, text)


@pytest.mark.spec("CNV-020", "MOD-020")
def test_a_model_not_known_to_accept_images_is_told_that_it_cannot_see_them(
    server: Server, household: Household
) -> None:
    conversation = create_conversation(server, household.token)["id"]
    with server.client(household.token) as client:
        path = _attach(client, conversation, "photo.png", _png())
    text = f"images? {secrets.token_hex(4)}"
    _, answer = _ask(server, household.token, conversation, text, [path])
    assert answer == saw([])
    request = _request_of(household.model, text)
    assert "uploads/photo.png" in request
    # It is told to say so to the user, rather than to try some other way.
    assert "cannot see images" in request
    # Nor is it offered the tool that looks at one.
    assert '"view_image"' not in request
    _, events = start_run(server, household.token, conversation, "look:uploads/photo.png")
    assert text_of(events) == "No tool view_image"


@pytest.mark.spec("CNV-020")
def test_the_assistant_looks_at_an_image_of_the_workspace(server: Server, seeing: Household) -> None:
    conversation = create_conversation(server, seeing.token)["id"]
    plot = _png()
    with server.client(seeing.token) as client:
        written = client.put(
            f"/conversations/{conversation}/workspace/file",
            params={"path": "charts/plot.png"},
            content=plot,
            headers=BINARY,
        )
        assert written.status_code == 201, written.text
        client.put(
            f"/conversations/{conversation}/workspace/file",
            params={"path": "charts/data.csv"},
            content=b"a,b\n1,2\n",
            headers=BINARY,
        )
    run_id, events = start_run(server, seeing.token, conversation, "look:charts/plot.png")
    assert wait_for_run(server, seeing.token, run_id)["status"] == "completed"
    assert text_of(events) == saw([plot])
    calls = [event for event in events if event.type == "TOOL_CALL_START"]
    assert [event.data.get("toolCallName") for event in calls] == ["view_image"]
    # A file that is not an image, a missing one and a path outside the workspace are told to the
    # model, and no image is sent.
    for path in ("charts/data.csv", "charts/missing.png", "../../etc/passwd"):
        other = create_conversation(server, seeing.token)["id"]
        if path == "charts/data.csv":
            with server.client(seeing.token) as client:
                client.put(
                    f"/conversations/{other}/workspace/file", params={"path": path}, content=b"a,b\n", headers=BINARY
                )
        run_id, events = start_run(server, seeing.token, other, f"look:{path}")
        assert wait_for_run(server, seeing.token, run_id)["status"] == "completed", path
        assert text_of(events) == saw([]), path


@pytest.mark.spec("CNV-020")
def test_an_image_follows_its_file_in_later_turns(database: Database, server: Server, seeing: Household) -> None:
    conversation = create_conversation(server, seeing.token)["id"]
    photo = _png()
    with server.client(seeing.token) as client:
        path = _attach(client, conversation, "photo.png", photo)
    first, answer = _ask(server, seeing.token, conversation, f"images? {secrets.token_hex(4)}", [path])
    assert answer == saw([photo])
    # The next turn's request holds the image again, read from the workspace.
    second, answer = _ask(server, seeing.token, conversation, "images? again", parent_run_id=first)
    assert answer == saw([photo])
    # Changed, the image is no longer the one the user sent: the model is told, and gets no image.
    with server.client(seeing.token) as client:
        changed = client.put(
            f"/conversations/{conversation}/workspace/file", params={"path": path}, content=_png(), headers=BINARY
        )
        assert changed.status_code == 201, changed.text
    text = f"images? changed {secrets.token_hex(4)}"
    third, answer = _ask(server, seeing.token, conversation, text, parent_run_id=second)
    assert answer == saw([])
    assert "no longer" in _request_of(seeing.model, text)
    # Gone, the same.
    with server.client(seeing.token) as client:
        deleted = client.delete(f"/conversations/{conversation}/workspace/entries", params={"path": path})
        assert deleted.status_code == 204, deleted.text
    text = f"images? gone {secrets.token_hex(4)}"
    _, answer = _ask(server, seeing.token, conversation, text, parent_run_id=third)
    assert answer == saw([])
    assert "no longer" in _request_of(seeing.model, text)
