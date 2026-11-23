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
import re
import secrets
import shlex
import stat
import time
import zipfile
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.approvals import (
    approval_of,
    approve,
    approving,
    completed,
    fresh_query,
    holds_untrusted_content,
    interrupts,
    resumed,
)
from tests.support.database import ROOT, Database
from tests.support.fixtures import HarnessModel
from tests.support.model import ModelRequest
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


def _request(server: Server, token: str, model: HarnessModel, conversation_id: str, text: str) -> ModelRequest:
    completed(server, token, conversation_id, text)
    return model.endpoint.requests_with(text)[0]


def _new_request(server: Server, token: str, model: HarnessModel) -> ModelRequest:
    conversation_id = create_conversation(server, token)["id"]
    return _request(server, token, model, conversation_id, f"hello {secrets.token_hex(4)}")


def _tool(name: str, **arguments: Any) -> str:
    return f"tool:{name} {json.dumps(arguments)}"


def _load(name: str) -> str:
    return _tool("load_capability", id=name)


def _marker(skill_md: str) -> str:
    found = re.search(r"marker [0-9a-f]{12}", skill_md)
    assert found is not None
    return found.group(0)


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


@pytest.mark.spec("AGT-024")
def test_built_in_skills_are_listed_on_and_trusted(server: Server, token: str) -> None:
    skills = _skills(server, token)
    assert skills["own"] == []
    assert (skills["used_bytes"], skills["limit_bytes"], skills["limit_skills"]) == (0, 100 * 1024 * 1024, 100)
    assert skills["builtin"], "the instance comes with built-in skills"
    for skill in skills["builtin"]:
        assert (skill["id"], skill["builtin"], skill["enabled"], skill["origin"]) == (None, True, True, "builtin")
        assert skill["untrusted"] is False
        assert skill["description"]
    names = [skill["name"] for skill in skills["builtin"]]
    assert names == sorted(names)


@pytest.mark.spec("AGT-024", "SBX-021")
def test_built_in_skills_describe_every_tool_of_the_sandbox_image(server: Server, token: str) -> None:
    texts: list[str] = []
    with server.client(token) as client:
        for skill in _skills(server, token)["builtin"]:
            response = client.get(f"/me/skills/builtin/{skill['name']}")
            assert response.status_code == 200, response.text
            detail = body(response)
            assert detail["files"][0]["path"] == "SKILL.md"
            texts += [file["text"] or "" for file in detail["files"]]
    described = "\n".join(texts)
    missing = [tool for tool in _image_tools() if not re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", described)]
    assert missing == [], "tools of the sandbox image that no built-in skill describes (AGT-024)"
    # One of them tells the assistant how to make a skill and save it (AGT-026).
    assert "save_skill" in described


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


def _image_tools() -> list[str]:
    """Every tool of the sandbox image, by the name the agent uses: Debian's packages, Typst and the Python
    libraries of the agent's environment (SBX-021, ADR-0080)."""
    folder = ROOT / "deploy" / "images" / "sandbox"
    dockerfile = (folder / "Dockerfile").read_text()
    install = dockerfile.split("apt-get install --yes --no-install-recommends", 1)[1].split("&&", 1)[0]
    packages = [word for word in install.replace("\\", " ").split() if word not in _IMAGE_BASE]
    tools = [command for package in packages for command in _COMMANDS.get(package, [package])]
    tools.append("typst")
    for line in (folder / "tools.in").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            tools.append(re.split(r"[\[<>=]", line, maxsplit=1)[0])
    return tools


@pytest.mark.spec("AGT-017", "AGT-025")
def test_the_user_creates_edits_and_deletes_a_skill(server: Server, token: str) -> None:
    name = _name()
    skill = _create(server, token, _skill_md(name, "Use for garden plans."))
    assert (skill["name"], skill["description"], skill["builtin"], skill["enabled"]) == (
        name,
        "Use for garden plans.",
        False,
        True,
    )
    # Written in the editor: the user's, and trusted.
    assert (skill["origin"], skill["untrusted"], skill["source_url"], skill["conversation"]) == (
        "user",
        False,
        None,
        None,
    )
    assert [file["path"] for file in skill["files"]] == ["SKILL.md"]
    # A text file beside it, executable, then a new SKILL.md that renames the skill.
    response = _write(server, token, skill["id"], "scripts/plan.sh", "echo plan\n", executable=True)
    assert response.status_code == 200, response.text
    renamed = _name("renamed")
    response = _write(server, token, skill["id"], "SKILL.md", _skill_md(renamed, "Use for orchards."))
    assert response.status_code == 200, response.text
    detail = body(response)
    assert (detail["id"], detail["name"], detail["description"]) == (skill["id"], renamed, "Use for orchards.")
    files = {file["path"]: file for file in detail["files"]}
    assert list(files) == ["SKILL.md", "scripts/plan.sh"]
    assert (files["scripts/plan.sh"]["text"], files["scripts/plan.sh"]["executable"]) == ("echo plan\n", True)
    assert detail["size_bytes"] == sum(file["size_bytes"] for file in detail["files"])
    assert _skills(server, token)["used_bytes"] == detail["size_bytes"]
    with server.client(token) as client:
        # SKILL.md stays; other files go.
        assert_problem(
            client.delete(f"/me/skills/{skill['id']}/file", params={"path": "SKILL.md"}), 422, "skill.invalid"
        )
        response = client.delete(f"/me/skills/{skill['id']}/file", params={"path": "scripts/plan.sh"})
        assert response.status_code == 200, response.text
        assert [file["path"] for file in body(response)["files"]] == ["SKILL.md"]
        assert (
            client.get(f"/me/skills/{skill['id']}/file", params={"path": "SKILL.md"}).content.decode().startswith("---")
        )
        assert client.delete(f"/me/skills/{skill['id']}").status_code == 204
        assert_problem(client.get(f"/me/skills/{skill['id']}"), 404, "resource.not_found")
        assert_problem(client.delete(f"/me/skills/{skill['id']}"), 404, "resource.not_found")
    assert _own(server, token) == []


@pytest.mark.spec("AGT-017", "AGT-024")
def test_skills_are_checked_by_the_agent_skills_rules(server: Server, token: str) -> None:
    taken = _create(server, token, _skill_md(_name("taken")))
    builtin = _skills(server, token)["builtin"][0]["name"]
    with server.client(token) as client:
        for invalid in (
            "No frontmatter at all.",
            "---\nname: Not-Valid\ndescription: Upper case.\n---\n",
            "---\nname: double--hyphen\ndescription: Two hyphens.\n---\n",
            f"---\nname: {'a' * 65}\ndescription: Too long a name.\n---\n",
            "---\nname: no-description\n---\nBody.\n",
            f"---\nname: long-description\ndescription: {'d' * 1025}\n---\n",
        ):
            assert_problem(client.post("/me/skills", json={"skill_md": invalid}), 422, "skill.invalid")
        # Names are unique among the user's skills and the built-in ones.
        assert_problem(client.post("/me/skills", json={"skill_md": _skill_md(taken["name"])}), 409, "resource.conflict")
        assert_problem(client.post("/me/skills", json={"skill_md": _skill_md(builtin)}), 409, "resource.conflict")
        other = _create(server, token, _skill_md(_name("other")))
        assert_problem(
            client.put(
                f"/me/skills/{other['id']}/file", params={"path": "SKILL.md"}, json={"text": _skill_md(taken["name"])}
            ),
            409,
            "resource.conflict",
        )
        # A path that leaves the skill's folder is refused.
        for path in ("../escape.md", "a/../../b.md", "a//b.md"):
            response = client.put(f"/me/skills/{other['id']}/file", params={"path": path}, json={"text": "x"})
            assert_problem(response, 422, "request.validation_failed")
    assert sorted(skill["name"] for skill in _own(server, token)) == sorted([taken["name"], other["name"]])


@pytest.mark.spec("AGT-017")
def test_a_skill_over_its_limits_is_refused(server: Server, token: str) -> None:
    skill = _create(server, token, _skill_md(_name()))
    with server.client(token) as client:
        assert_problem(
            client.put(f"/me/skills/{skill['id']}/file", params={"path": "SKILL.md"}, json={"text": "x" * 100_001}),
            422,
            "request.validation_failed",
        )
        # More than 10 MiB in one skill, through an archive.
        big = _zip({"big/SKILL.md": _skill_md("big"), "big/data.bin": secrets.token_bytes(10 * 1024 * 1024)})
        assert_problem(_upload(server, token, big), 413, "skill.too_large")
        # More than 200 files.
        many: dict[str, bytes | str] = {f"many/f{index}.txt": "x" for index in range(200)}
        many["many/SKILL.md"] = _skill_md("many")
        assert_problem(_upload(server, token, _zip(many)), 413, "skill.too_large")
    assert [own["name"] for own in _own(server, token)] == [skill["name"]]


@pytest.mark.spec("AGT-017", "AGT-025")
def test_an_uploaded_archive_is_an_untrusted_skill(server: Server, token: str) -> None:
    name = _name("uploaded")
    archive = _zip(
        {
            f"{name}/SKILL.md": _skill_md(name),
            f"{name}/references/guide.md": "# Guide\n",
            f"{name}/assets/logo.bin": b"\x00\xff\x00",
        }
    )
    response = _upload(server, token, archive, f"{name}.skill")
    assert response.status_code == 201, response.text
    skill = body(response)
    assert (skill["name"], skill["origin"], skill["untrusted"], skill["enabled"]) == (name, "upload", True, True)
    files = {file["path"]: file for file in skill["files"]}
    assert list(files) == ["SKILL.md", "assets/logo.bin", "references/guide.md"]
    # Text is shown; anything else is downloaded.
    assert (files["references/guide.md"]["text"], files["assets/logo.bin"]["text"]) == ("# Guide\n", None)
    # SKILL.md may also be at the archive's root.
    root = _name("root")
    response = _upload(server, token, _zip({"SKILL.md": _skill_md(root), "notes.md": "notes"}))
    assert response.status_code == 201, response.text
    assert body(response)["name"] == root


@pytest.mark.spec("AGT-017")
@pytest.mark.parametrize(
    "entries",
    [
        {"evil/SKILL.md": _skill_md("evil"), "evil/../outside.md": "x"},
        {"evil/SKILL.md": _skill_md("evil"), "/etc/evil.md": "x"},
        {"one/SKILL.md": _skill_md("one"), "two/SKILL.md": _skill_md("two")},
        {"README.md": "no skill here"},
    ],
    ids=["parent-segment", "absolute-path", "two-skills", "no-skill"],
)
def test_archives_with_entries_outside_one_skill_are_refused(
    server: Server, token: str, entries: dict[str, bytes | str]
) -> None:
    assert_problem(_upload(server, token, _zip(entries)), 422, "skill.invalid")
    assert _own(server, token) == []


@pytest.mark.spec("AGT-017")
def test_archives_with_links_are_refused(server: Server, token: str) -> None:
    archive = _zip({"linked/SKILL.md": _skill_md("linked")}, links={"linked/secret": "/etc/passwd"})
    assert_problem(_upload(server, token, archive), 422, "skill.invalid")
    assert _own(server, token) == []


@pytest.mark.spec("AGT-017")
def test_a_skill_downloads_as_a_zip_named_after_it(server: Server, token: str) -> None:
    name = _name()
    skill_md = _skill_md(name)
    skill = _create(server, token, skill_md)
    _write(server, token, skill["id"], "scripts/run.py", "print('hi')\n", executable=True)
    with server.client(token) as client:
        response = client.get(f"/me/skills/{skill['id']}/archive")
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == [f"{name}/SKILL.md", f"{name}/scripts/run.py"]
        assert archive.read(f"{name}/SKILL.md").decode() == skill_md
        mode = archive.getinfo(f"{name}/scripts/run.py").external_attr >> 16
        assert mode & 0o100


@pytest.mark.spec("AGT-017")
def test_every_run_is_offered_the_skills_that_are_on_by_name_and_description(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    skill_md = _skill_md(_name("garden"), "Use when planning a vegetable garden.")
    skill = _create(server, token, skill_md)
    request = _new_request(server, token, default_model)
    system = json.dumps(request.body)
    assert skill["name"] in system
    assert "Use when planning a vegetable garden." in system
    # Only the name and the description, until the model loads it.
    assert _marker(skill_md) not in system
    assert "load_capability" in request.tool_names()
    # Turned off by the user: not offered in any conversation.
    assert _patch(server, token, skill["id"], enabled=False).status_code == 200
    system = json.dumps(_new_request(server, token, default_model).body)
    assert skill["name"] not in system


@pytest.mark.spec("AGT-017", "AGT-024")
def test_without_skills_on_there_is_nothing_to_load(server: Server, token: str, default_model: HarnessModel) -> None:
    with server.client(token) as client:
        for skill in _skills(server, token)["builtin"]:
            assert client.patch(f"/me/skills/builtin/{skill['name']}", json={"enabled": False}).status_code == 200
    assert all(not skill["enabled"] for skill in _skills(server, token)["builtin"])
    assert "load_capability" not in _new_request(server, token, default_model).tool_names()
    first = _skills(server, token)["builtin"][0]["name"]
    with server.client(token) as client:
        response = client.patch(f"/me/skills/builtin/{first}", json={"enabled": True})
    assert response.status_code == 200, response.text
    assert body(response)["enabled"] is True
    request = _new_request(server, token, default_model)
    assert "load_capability" in request.tool_names()
    assert first in json.dumps(request.body)


@pytest.mark.spec("AGT-017")
def test_a_conversation_turns_off_skills_and_new_ones_are_on(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    off = _create(server, token, _skill_md(_name("off")))
    conversation = create_conversation(server, token)
    assert conversation["disabled_skills"] == []
    with server.client(token) as client:
        response = client.patch(f"/conversations/{conversation['id']}", json={"disabled_skills": [off["name"]]})
    assert response.status_code == 200, response.text
    assert body(response)["disabled_skills"] == [off["name"]]
    # A skill added afterwards is on in the conversation.
    added = _create(server, token, _skill_md(_name("added")))
    system = json.dumps(_request(server, token, default_model, conversation["id"], f"x {secrets.token_hex(4)}").body)
    assert off["name"] not in system
    assert added["name"] in system
    # Elsewhere, it is on.
    assert off["name"] in json.dumps(_new_request(server, token, default_model).body)


@pytest.mark.spec("AGT-017")
def test_loading_a_skill_gives_the_model_its_body(server: Server, token: str, default_model: HarnessModel) -> None:
    skill_md = _skill_md(_name("loaded"))
    skill = _create(server, token, skill_md)
    conversation_id = create_conversation(server, token)["id"]
    text = _load(skill["name"])
    events = completed(server, token, conversation_id, text)
    assert _marker(skill_md) in _everything_sent(default_model, text)
    assert interrupts(events) == []
    # The model is told where the skill's files are in the sandbox.
    assert f"/skills/{skill['name']}" in _everything_sent(default_model, text)
    assert skill["name"] in json.dumps(messages(server, token, conversation_id)["items"])


@pytest.mark.spec("AGT-017", "MEM-003")
def test_runs_keep_no_copy_of_skills_in_their_inputs(
    database: Database, server: Server, token: str, default_model: HarnessModel
) -> None:
    skill_md = _skill_md(_name())
    skill = _create(server, token, skill_md)
    _new_request(server, token, default_model)
    with database.superuser() as conn:
        for needle in (skill["description"], _marker(skill_md)):
            inputs = conn.execute(
                "SELECT count(*) FROM dbos.workflow_status WHERE inputs LIKE %s", (f"%{needle}%",)
            ).fetchone()
            assert inputs == (0,)
    with server.client(token) as client:
        assert client.delete(f"/me/skills/{skill['id']}").status_code == 204
    with database.superuser() as conn:
        assert conn.execute("SELECT count(*) FROM skill_files WHERE skill_id = %s", (skill["id"],)).fetchone() == (0,)


@pytest.mark.spec("AGT-025", "AGT-003", "AGT-004")
def test_an_untrusted_skill_makes_every_run_it_reaches_untrusted_until_the_user_trusts_it(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    name = _name("untrusted")
    response = _upload(server, token, _zip({f"{name}/SKILL.md": _skill_md(name)}))
    assert response.status_code == 201, response.text
    skill = body(response)
    # Offered, marked as from an untrusted source.
    request = _new_request(server, token, default_model)
    system = json.dumps(request.body)
    around = system[max(0, system.index(name) - 300) : system.index(name) + 300].lower()
    assert "untrusted" in around
    # Its description reaches the run whether or not it is loaded: the run is untrusted from its start, and its
    # first request for internet access says so (ADR-0116).
    assert holds_untrusted_content(server, token, create_conversation(server, token)["id"]) is True
    # A conversation that turns it off is not offered it, and is trusted.
    off = create_conversation(server, token)["id"]
    with server.client(token) as client:
        response = client.patch(f"/conversations/{off}", json={"disabled_skills": [name]})
    assert response.status_code == 200, response.text
    assert holds_untrusted_content(server, token, off) is False
    # Loaded: what it brought in stays untrusted content of the conversation.
    loaded = create_conversation(server, token)["id"]
    completed(server, token, loaded, _load(name))
    # Marked trusted by the user: runs that are offered it, or load it, are trusted again; the conversation that
    # loaded it while it was untrusted still holds untrusted content.
    with server.client(token) as client:
        assert_problem(
            client.patch(f"/me/skills/{skill['id']}", json={"untrusted": True}), 422, "request.validation_failed"
        )
    response = _patch(server, token, skill["id"], untrusted=False)
    assert response.status_code == 200, response.text
    assert body(response)["untrusted"] is False
    assert holds_untrusted_content(server, token, create_conversation(server, token)["id"]) is False
    trusted_conversation = create_conversation(server, token)["id"]
    completed(server, token, trusted_conversation, _load(name))
    assert holds_untrusted_content(server, token, trusted_conversation) is False
    assert holds_untrusted_content(server, token, loaded) is True


@pytest.mark.spec("AGT-025")
def test_editing_a_skill_does_not_change_whether_it_is_trusted(server: Server, token: str) -> None:
    name = _name("edited")
    uploaded = body(_upload(server, token, _zip({f"{name}/SKILL.md": _skill_md(name)})))
    response = _write(server, token, uploaded["id"], "SKILL.md", _skill_md(name, "Edited by the user."))
    assert response.status_code == 200, response.text
    assert body(response)["untrusted"] is True
    assert body(response)["origin"] == "upload"
    written = _create(server, token, _skill_md(_name("written")))
    response = _write(server, token, written["id"], "notes.md", "pasted from somewhere")
    assert body(response)["untrusted"] is False


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


def _make_folder(name: str, label: str = "made") -> str:
    """A command that writes a skill named `name` into the sandbox's scratch folder."""
    skill_md = _skill_md(name, f"Use for {label} work.", f"Do the {label} work. marker {secrets.token_hex(6)}")
    return (
        f"mkdir -p /scratch/{name}/scripts && printf %s {shlex.quote(skill_md)} > /scratch/{name}/SKILL.md"
        f" && printf 'echo {label}\\n' > /scratch/{name}/scripts/go.sh && chmod +x /scratch/{name}/scripts/go.sh"
    )


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


@pytest.mark.spec("AGT-025", "AGT-003")
def test_a_loaded_skill_that_becomes_untrusted_makes_later_runs_untrusted(
    server: Server, token: str, database: Database, default_model: HarnessModel, search_service: SearchServer
) -> None:
    name = _name("turned")
    skill = _create(server, token, _skill_md(name))
    conversation_id = create_conversation(server, token)["id"]
    completed(server, token, conversation_id, _load(name))
    # Replaced since by a run with untrusted content elsewhere: it is untrusted now.
    with database.superuser() as conn:
        conn.execute("UPDATE skills SET untrusted = true WHERE id = %s", (skill["id"],))
    assert holds_untrusted_content(server, token, conversation_id) is True


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


@pytest.mark.spec("AGT-026", "CNV-011")
def test_temporary_conversations_cannot_save_skills(server: Server, token: str, default_model: HarnessModel) -> None:
    with server.client(token) as client:
        response = client.post("/conversations", json={"temporary": True})
    assert response.status_code == 201, response.text
    text = f"temporary {secrets.token_hex(4)}"
    request = _request(server, token, default_model, body(response)["id"], text)
    assert "save_skill" not in request.tool_names()
    # Skills are still offered there.
    assert "load_capability" in request.tool_names()


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


def _sandboxes_of(account: Account) -> list[str]:
    """The containers and workspaces the driver keeps for the user, who has run no command."""
    containers = docker("ps", "-a", "--format", "{{.Names}}").split()
    volumes = docker("volume", "ls", "--format", "{{.Name}}").split()
    return [name for name in containers + volumes if str(account.id) in name]


@pytest.mark.spec("AGT-017", "TEN-006")
def test_skills_of_others_cannot_be_read_changed_or_deleted(
    database: Database, server: Server, token: str, account: Account
) -> None:
    mine = _create(server, token, _skill_md(_name("mine")))
    for other in (create_account(database, account.tenant_id), create_account(database, create_tenant(database))):
        other_token = login(server, other)
        assert _own(server, other_token) == []
        with server.client(other_token) as client:
            for response in (
                client.get(f"/me/skills/{mine['id']}"),
                client.get(f"/me/skills/{mine['id']}/archive"),
                client.get(f"/me/skills/{mine['id']}/file", params={"path": "SKILL.md"}),
                client.patch(f"/me/skills/{mine['id']}", json={"enabled": False}),
                client.put(f"/me/skills/{mine['id']}/file", params={"path": "x.md"}, json={"text": "x"}),
                client.delete(f"/me/skills/{mine['id']}"),
            ):
                assert_problem(response, 404, "resource.not_found")
            # Another user may use the same name.
            _create(server, other_token, _skill_md(mine["name"]))
    assert [skill["id"] for skill in _own(server, token)] == [mine["id"]]


@pytest.mark.spec("AGT-017")
def test_a_skills_front_matter_is_bounded_before_it_is_read(server: Server, token: str) -> None:
    # Aliases that nest to billions of items, which a parser would build in full (ADR-0132).
    layers = ['a0: &a0 ["x","x","x","x","x","x","x","x","x"]']
    layers += [f"a{n}: &a{n} [" + ",".join([f"*a{n - 1}"] * 9) + "]" for n in range(1, 9)]
    bomb = "---\nname: bomb\n" + "\n".join(layers) + "\ndescription: *a8\n---\n\nBody.\n"
    started = time.monotonic()
    with server.client(token) as client:
        refused = client.post("/me/skills", json={"skill_md": bomb})
        assert_problem(refused, 422, "skill.invalid")
        # Front matter longer than 16 KiB is refused unread.
        long = "---\nname: long\ndescription: " + "y" * 17_000 + "\n---\n\nBody.\n"
        assert_problem(client.post("/me/skills", json={"skill_md": long}), 422, "skill.invalid")
    assert time.monotonic() - started < 10
