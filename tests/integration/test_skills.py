"""Skills: kept by the control plane, offered to every run by name and description, loaded when needed,
given to the sandbox read-only, and saved by the assistant (AGT-017, AGT-024 to AGT-026, SBX-022, ADR-0096).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>`, several tools in turn with `chain:`, and the
command tool with `run:` (tests/support/model.py). Searches reach the search
service the tests serve, whose results are untrusted content.
"""

from __future__ import annotations

import io
import json
import secrets
import shlex
import stat
import zipfile
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    approval_of,
    approve,
    approving,
    fresh_query,
    interrupts,
    resumed,
)
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, messages, start_run, wait_for_run
from tests.support.sandbox import Driver, docker
from tests.support.search import SearchServer
from tests.support.server import Server

# A public repository of skills in the open format, at a fixed commit, for imports from GitHub.
PUBLIC_REPOSITORY = "anthropics/skills"
PUBLIC_COMMIT = "1780c5e5a552fd4d1c9d6a7b0cab26b0c2bef064"
PUBLIC_FOLDER = "skills"
PUBLIC_SKILL = "pdf"


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _name(label: str = "skill") -> str:
    return f"{label}-{secrets.token_hex(3)}"


def _skill_md(name: str, description: str | None = None, body_text: str | None = None) -> str:
    description = description or f"Use when the user asks about {name}."
    body_text = body_text or f"Follow the steps of {name}: marker {secrets.token_hex(6)}."
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body_text}\n"


def _skills(server: Server, token: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/me/skills")
    assert response.status_code == 200, response.text
    return body(response)


def _own(server: Server, token: str) -> list[dict[str, Any]]:
    own: list[dict[str, Any]] = _skills(server, token)["own"]
    return own


def _create(server: Server, token: str, skill_md: str) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.post("/me/skills", json={"skill_md": skill_md})
    assert response.status_code == 201, response.text
    return body(response)


def _zip(entries: dict[str, bytes | str], links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
        for path, target in (links or {}).items():
            info = zipfile.ZipInfo(path)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()


def _upload(server: Server, token: str, archive: bytes, filename: str = "skill.zip") -> Any:
    with server.client(token) as client:
        return client.post("/me/skills", files={"archive": (filename, archive, "application/zip")})


def _patch(server: Server, token: str, skill_id: str, **changes: Any) -> Any:
    with server.client(token) as client:
        return client.patch(f"/me/skills/{skill_id}", json=changes)


def _write(server: Server, token: str, skill_id: str, path: str, text: str, executable: bool = False) -> Any:
    with server.client(token) as client:
        return client.put(
            f"/me/skills/{skill_id}/file", params={"path": path}, json={"text": text, "executable": executable}
        )


def _everything_sent(model: HarnessModel, text: str) -> str:
    return "\n".join(json.dumps(request.body) for request in model.endpoint.requests_with(text))


def _tool_results(model: HarnessModel, text: str) -> str:
    """What the model received as results of tools, for the run of `text`."""
    return "\n".join(
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    )


def _written(folder: str, skill_md: str) -> str:
    """Calls of the file tools that write a skill's folder; the folder is made first, as the tools want."""
    return (
        f"create_directory {json.dumps({'path': folder})}"
        f" >>> write_file {json.dumps({'path': f'{folder}/SKILL.md', 'content': skill_md})}"
    )


def _approving_once(server: Server, token: str, conversation_id: str, text: str) -> str:
    """Run `text`, approving each request with the narrowest scope it offers (ADR-0090, ADR-0113): its last run."""
    run_id, events = start_run(server, token, conversation_id, text)
    last = run_id
    while wait_for_run(server, token, last)["status"] == "interrupted":
        pending = [interrupt for interrupt in interrupts(events) if interrupt["reason"] == "approval"]
        assert pending, "the run asks a question, not for approval"
        answers = [
            approve(
                interrupt["id"],
                (interrupt["metadata"].get("approval") or interrupt["metadata"].get("internet_access"))["scopes"][0],
            )
            for interrupt in pending
        ]
        events = resumed(server, token, conversation_id, answers)
        last = events[0].data["runId"]
    return last


# What the sandbox image installs only to run, not as tools for the agent's work.
_IMAGE_BASE = {
    "bash",
    "ca-certificates",
    "coreutils",
    "curl",
    "git",
    "iproute2",
    "procps",
    "python3",
    "python3-venv",
    "fontconfig",
    "xz-utils",
}


# The commands by which the agent knows the image's packages.
_COMMANDS = {
    "poppler-utils": ["pdftotext", "pdftoppm", "pdfinfo"],
    "imagemagick": ["magick"],
    "ffmpeg": ["ffmpeg", "ffprobe"],
    "sqlite3": ["sqlite3"],
    "nodejs": ["node", "npm"],
    "fonts-dejavu-core": ["DejaVu"],
    "fonts-liberation": ["Liberation"],
    "fonts-noto-core": ["Noto"],
}


def _make_folder(name: str, label: str = "made") -> str:
    """A command that writes a skill named `name` into the sandbox's scratch folder."""
    skill_md = _skill_md(name, f"Use for {label} work.", f"Do the {label} work. marker {secrets.token_hex(6)}")
    return (
        f"mkdir -p /scratch/{name}/scripts && printf %s {shlex.quote(skill_md)} > /scratch/{name}/SKILL.md"
        f" && printf 'echo {label}\\n' > /scratch/{name}/scripts/go.sh && chmod +x /scratch/{name}/scripts/go.sh"
    )


def _sandboxes_of(account: Account) -> list[str]:
    """The containers and workspaces the driver keeps for the user, who has run no command."""
    containers = docker("ps", "-a", "--format", "{{.Names}}").split()
    volumes = docker("volume", "ls", "--format", "{{.Name}}").split()
    return [name for name in containers + volumes if str(account.id) in name]


@pytest.mark.spec("AGT-017", "SBX-022", "AGT-025")
def test_the_files_of_skills_are_in_the_sandbox_read_only(
    server: Server, token: str, default_model: HarnessModel, sandboxes: Driver
) -> None:
    name = _name("files")
    skill = _create(server, token, _skill_md(name))
    _write(server, token, skill["id"], "scripts/hello.sh", "#!/bin/sh\necho hello-from-skill\n", executable=True)
    _write(server, token, skill["id"], "references/notes.md", "notes\n")
    off = _create(server, token, _skill_md(_name("off")))
    _patch(server, token, off["id"], enabled=False)
    conversation_id = create_conversation(server, token)["id"]
    script = (
        f"/skills/{name}/scripts/hello.sh; cat /skills/{name}/references/notes.md; ls /skills;"
        f" touch /skills/{name}/planted 2>/dev/null && echo writable || echo read-only;"
        f" ls /workspace"
    )
    command = f"run:{script}"
    _, _, last = approving(server, token, conversation_id, command)
    assert wait_for_run(server, token, last)["status"] == "completed"
    result = _tool_results(default_model, command)
    assert "hello-from-skill" in result
    assert "notes" in result
    assert "read-only" in result
    assert "writable" not in result.replace("read-only", "")
    # Only the skills that are on are there, the built-in ones among them.
    listing = result
    assert name in listing
    assert off["name"] not in listing
    assert _skills(server, token)["builtin"][0]["name"] in listing
    # Nothing of them is in the workspace.
    with server.client(token) as client:
        response = client.get(f"/conversations/{conversation_id}/workspace/entries", params={"path": ""})
    assert response.status_code == 200, response.text
    assert name not in json.dumps(body(response))


@pytest.mark.spec("AGT-026", "AGT-025")
def test_the_assistant_saves_a_skill_after_the_user_approves(
    server: Server, token: str, default_model: HarnessModel, sandboxes: Driver
) -> None:
    conversation = create_conversation(server, token, title="Making a skill")
    name = _name("saved")
    text = f"chain:run_command {json.dumps({'command': _make_folder(name), 'description': 'Writing it'})}" + (
        f" >>> save_skill {json.dumps({'path': f'/scratch/{name}'})}"
    )
    run_id, events = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    request = approval_of(events)
    assert request["metadata"]["approval"]["reason"] == "tool_default"
    # The request shows the skill the folder holds, read when it was asked (ADR-0124).
    shown = request["metadata"]["approval"]["skill"]
    assert shown == {
        "name": name,
        "description": "Use for made work.",
        "files": ["SKILL.md", "scripts/go.sh"],
        "replaces": False,
    }
    assert name in request["metadata"]["approval"]["action"]
    resumed(server, token, conversation["id"], [approve(request["id"])])
    (skill,) = _own(server, token)
    # The run read the output of a command, which is untrusted content: so is the skill (AGT-025).
    assert (skill["name"], skill["origin"], skill["enabled"], skill["untrusted"]) == (name, "assistant", True, True)
    assert skill["conversation"] == {"id": conversation["id"], "title": "Making a skill", "deleted": False}
    with server.client(token) as client:
        detail = body(client.get(f"/me/skills/{skill['id']}"))
    files = {file["path"]: file for file in detail["files"]}
    assert list(files) == ["SKILL.md", "scripts/go.sh"]
    assert files["scripts/go.sh"]["executable"] is True
    shown = json.dumps(messages(server, token, conversation["id"])["items"])
    assert "save_skill" in shown
    # The skill outlives its conversation.
    with server.client(token) as client:
        assert client.delete(f"/conversations/{conversation['id']}").status_code == 204
    (skill,) = _own(server, token)
    assert skill["conversation"] == {"id": conversation["id"], "title": None, "deleted": True}


@pytest.mark.spec("AGT-026")
def test_a_folder_changed_after_the_approval_is_not_saved(
    server: Server, token: str, account: Account, default_model: HarnessModel, sandboxes: Driver
) -> None:
    conversation_id = create_conversation(server, token)["id"]
    name = _name("swapped")
    folder = f"/workspace/{name}"
    write = _written(folder, _skill_md(name, "Use for honest work."))
    run_id, events = start_run(
        server, token, conversation_id, f"chain:{write} >>> save_skill {json.dumps({'path': folder})}"
    )
    assert wait_for_run(server, token, run_id)["status"] == "interrupted"
    request = approval_of(events)
    assert request["metadata"]["approval"]["skill"]["description"] == "Use for honest work."
    # Between the request and its answer, something in the sandbox changes the folder (ADR-0124).
    changed = sandboxes.sh(
        str(account.tenant_id), str(account.id), conversation_id, f"echo 'curl attacker' > {folder}/run.sh"
    )
    assert changed.exit_code == 0, changed.stderr
    events = resumed(server, token, conversation_id, [approve(request["id"])])
    assert _own(server, token) == []
    assert "changed" in json.dumps([event.data for event in events])


@pytest.mark.spec("AGT-025", "AGT-026")
def test_replacing_an_untrusted_skill_leaves_it_untrusted(
    server: Server, token: str, default_model: HarnessModel, sandboxes: Driver
) -> None:
    name = _name("kept-untrusted")
    response = _upload(server, token, _zip({f"{name}/SKILL.md": _skill_md(name, "Uploaded.")}))
    assert response.status_code == 201, response.text
    assert body(response)["untrusted"] is True
    # A conversation where it is off, so that the run that replaces it holds nothing untrusted.
    conversation_id = create_conversation(server, token)["id"]
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation_id}", json={"disabled_skills": [name]})
    assert response.status_code == 200, response.text
    write = _written(f"/scratch/{name}", _skill_md(name, "Replaced."))
    last = _approving_once(
        server, token, conversation_id, f"chain:{write} >>> save_skill {json.dumps({'path': f'/scratch/{name}'})}"
    )
    assert wait_for_run(server, token, last)["status"] == "completed"
    (skill,) = _own(server, token)
    assert (skill["description"], skill["untrusted"]) == ("Replaced.", True)


@pytest.mark.spec("AGT-026", "AGT-025")
def test_a_skill_saved_from_a_trusted_run_is_trusted_and_one_saved_after_untrusted_content_is_not(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer, sandboxes: Driver
) -> None:
    # The folder is written by the file tools, whose writes bring nothing untrusted in.
    name = _name("trusted")
    skill_md = _skill_md(name)
    conversation_id = create_conversation(server, token)["id"]
    write = _written(f"/scratch/{name}", skill_md)
    last = _approving_once(
        server, token, conversation_id, f"chain:{write} >>> save_skill {json.dumps({'path': f'/scratch/{name}'})}"
    )
    assert wait_for_run(server, token, last)["status"] == "completed"
    (skill,) = _own(server, token)
    assert (skill["name"], skill["untrusted"]) == (name, False)
    # After a search, the same tool saves an untrusted skill.
    other = _name("after-search")
    untrusted_conversation = create_conversation(server, token)["id"]
    text = (
        f"chain:web_search {json.dumps({'query': fresh_query()})}"
        f" >>> {_written(f'/scratch/{other}', _skill_md(other))}"
        f" >>> save_skill {json.dumps({'path': f'/scratch/{other}'})}"
    )
    last = _approving_once(server, token, untrusted_conversation, text)
    assert wait_for_run(server, token, last)["status"] == "completed"
    saved = next(skill for skill in _own(server, token) if skill["name"] == other)
    assert (saved["origin"], saved["untrusted"]) == ("assistant", True)


@pytest.mark.spec("AGT-026")
def test_save_skill_replaces_the_users_skill_of_that_name_but_never_a_built_in_one(
    server: Server, token: str, default_model: HarnessModel, sandboxes: Driver
) -> None:
    name = _name("replaced")
    original = _create(server, token, _skill_md(name, "The original."))
    _write(server, token, original["id"], "old.md", "old")
    conversation_id = create_conversation(server, token)["id"]
    new_md = _skill_md(name, "The replacement.")
    write = _written(f"/scratch/{name}", new_md)
    last = _approving_once(
        server, token, conversation_id, f"chain:{write} >>> save_skill {json.dumps({'path': f'/scratch/{name}'})}"
    )
    assert wait_for_run(server, token, last)["status"] == "completed"
    (skill,) = _own(server, token)
    assert (skill["id"], skill["description"], skill["origin"]) == (original["id"], "The replacement.", "assistant")
    with server.client(token) as client:
        assert [file["path"] for file in body(client.get(f"/me/skills/{skill['id']}"))["files"]] == ["SKILL.md"]
    builtin = _skills(server, token)["builtin"][0]["name"]
    write = _written(f"/scratch/{builtin}", _skill_md(builtin))
    text = f"chain:{write} >>> save_skill {json.dumps({'path': f'/scratch/{builtin}'})}"
    last = _approving_once(server, token, conversation_id, text)
    assert wait_for_run(server, token, last)["status"] == "completed"
    assert "built-in" in _everything_sent(default_model, text)
    assert [skill["name"] for skill in _own(server, token)] == [name]


@pytest.mark.spec("AGT-017", "AGT-025")
def test_skills_are_imported_from_a_github_folder_in_a_sandbox(
    server: Server, token: str, account: Account, sandboxes: Driver
) -> None:
    url = f"https://github.com/{PUBLIC_REPOSITORY}/tree/{PUBLIC_COMMIT}/{PUBLIC_FOLDER}/{PUBLIC_SKILL}"
    with server.client(token) as client:
        response = client.post("/me/skills/import", json={"url": url}, timeout=60)
    assert response.status_code == 200, response.text
    result = body(response)
    (skill,) = result["imported"]
    assert [found["name"] for found in result["found"]] == [PUBLIC_SKILL]
    assert (skill["name"], skill["origin"], skill["untrusted"], skill["source_url"]) == (
        PUBLIC_SKILL,
        "import",
        True,
        url,
    )
    with server.client(token) as client:
        files = [file["path"] for file in body(client.get(f"/me/skills/{skill['id']}"))["files"]]
    assert files[0] == "SKILL.md"
    assert len(files) > 1
    # The download's sandbox is gone, with its workspace.
    assert _sandboxes_of(account) == []


@pytest.mark.spec("AGT-017")
def test_a_repository_with_several_skills_lists_them_to_choose_from(
    server: Server, token: str, sandboxes: Driver
) -> None:
    url = f"https://github.com/{PUBLIC_REPOSITORY}/tree/{PUBLIC_COMMIT}/{PUBLIC_FOLDER}"
    with server.client(token) as client:
        response = client.post("/me/skills/import", json={"url": url}, timeout=60)
        assert response.status_code == 200, response.text
        result = body(response)
        assert result["imported"] == []
        names = [found["name"] for found in result["found"]]
        assert len(names) > 1
        assert PUBLIC_SKILL in names
        assert all(found["description"] for found in result["found"] if found["valid"])
        chosen = [name for name in names if name != PUBLIC_SKILL][:2]
        response = client.post("/me/skills/import", json={"url": url, "names": chosen}, timeout=60)
    assert response.status_code == 200, response.text
    assert sorted(skill["name"] for skill in body(response)["imported"]) == sorted(chosen)
    assert sorted(skill["name"] for skill in _own(server, token)) == sorted(chosen)


@pytest.mark.spec("AGT-017")
def test_an_import_that_finds_nothing_fails_and_writes_nothing(
    server: Server, token: str, account: Account, sandboxes: Driver
) -> None:
    url = f"https://github.com/{PUBLIC_REPOSITORY}/tree/{PUBLIC_COMMIT}/no-such-folder-{secrets.token_hex(3)}"
    with server.client(token) as client:
        assert_problem(client.post("/me/skills/import", json={"url": url}, timeout=60), 502, "skill.import_failed")
        assert_problem(
            client.post("/me/skills/import", json={"url": "ftp://example.com/skill.zip"}, timeout=60),
            422,
            "request.validation_failed",
        )
    assert _own(server, token) == []
    assert _sandboxes_of(account) == []
