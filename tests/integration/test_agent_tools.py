"""The agent's tools, through runs: its workspace, questions to the user and its task list (AGT-011, AGT-014,
AGT-015, CNV-018, SBX-001, UX-009, ADR-0035, ADR-0053, ADR-0083).

The model the tests serve calls the agent's command tool when the user's
message is `run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import json
import time

import pytest

from tests.support.accounts import Account, body, create_account, create_tenant, login
from tests.support.approvals import approving
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import (
    create_conversation,
    messages,
    start_run,
    text_of,
    wait_for_run,
)
from tests.support.sandbox import Driver, host_docker
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _tool_results(model: HarnessModel, text: str) -> list[str]:
    """What the model received as results of the command tool, for the run of `text`."""
    return [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]


def _driver_ready(sandboxes: Driver) -> bool:
    with sandboxes.client() as client:
        return client.get("/health").status_code == 200


@pytest.mark.spec("AGT-011")
def test_the_file_tools_reach_the_workspace(
    server: Server, token: str, account: Account, default_model: HarnessModel, sandboxes: Driver
) -> None:
    # The user's files are in /workspace (ADR-0076): the file tools read and write them by their paths.
    conversation = create_conversation(server, token)["id"]
    marker = f"marker-{uuid7()}"
    written = sandboxes.sh(
        str(account.tenant_id),
        str(account.id),
        conversation,
        f"mkdir -p /workspace/notes && echo {marker} > /workspace/notes/a.txt",
    )
    assert written.exit_code == 0, written
    read = f"tool:read_file {json.dumps({'path': '/workspace/notes/a.txt'})}"
    run_id, events = start_run(server, token, conversation, read)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert marker in text_of(events)
    write = f"tool:write_file {json.dumps({'path': '/workspace/notes/b.txt', 'content': marker})}"
    run_id, _ = start_run(server, token, conversation, write)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    kept = sandboxes.sh(str(account.tenant_id), str(account.id), conversation, "cat /workspace/notes/b.txt")
    assert kept.stdout.strip() == marker


@pytest.mark.spec("AGT-011")
def test_the_file_tools_reach_the_scratch_folder(server: Server, token: str, default_model: HarnessModel) -> None:
    # Relative paths start where commands start, in /scratch (ADR-0076).
    conversation = create_conversation(server, token)["id"]
    marker = f"marker-{uuid7()}"
    # In one run: the scratch folder ends with the sandbox, after each run.
    text = (
        f"chain:write_file {json.dumps({'path': 'draft.txt', 'content': marker})}"
        f" >>> run_command {json.dumps({'command': 'cat /scratch/draft.txt'})}"
    )
    run_id, events = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert marker in text_of(events)


@pytest.mark.spec("AGT-011", "SBX-001")
def test_commands_run_in_the_sandbox_of_the_conversation_they_act_in(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    secret = f"secret-{uuid7()}"
    conversation = create_conversation(server, token)
    sandboxes.sh(str(account.tenant_id), str(account.id), conversation["id"], f"echo {secret} > /workspace/mine.txt")
    command = f"run:cat /workspace/mine.txt # {uuid7()}"
    start_run(server, token, conversation["id"], command)
    (result,) = _tool_results(default_model, command)
    assert secret in result


@pytest.mark.spec("AGT-011", "SBX-001")
@pytest.mark.parametrize("whose", ["another-user", "another-conversation"])
def test_the_agent_never_reaches_another_sandbox(
    database: Database,
    server: Server,
    sandboxes: Driver,
    account: Account,
    token: str,
    default_model: HarnessModel,
    whose: str,
) -> None:
    other = create_account(database, create_tenant(database)) if whose == "another-user" else account
    secret = f"theirs-{uuid7()}"
    sandboxes.sh(str(other.tenant_id), str(other.id), str(uuid7()), f"echo {secret} > /workspace/theirs.txt")
    conversation = create_conversation(server, token)
    command = f"run:cat /workspace/theirs.txt; ls -a /workspace # {uuid7()}"
    start_run(server, token, conversation["id"], command)
    (result,) = _tool_results(default_model, command)
    assert secret not in result


@pytest.mark.spec("AGT-014")
def test_large_tool_output_reaches_the_model_bounded_and_stays_in_the_scratch_folder(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    size = 60_000
    # Two commands in one answer: the sandbox, and the scratch folder, end with it (ADR-0076, ADR-0078).
    command = (
        f"runs:head -c {size} /dev/zero | tr '\\0' a"
        " ||| find /scratch -type f -size +50k | wc -l; find /workspace -type f -size +50k | wc -l"
    )
    # The second command reads the first's output, which is untrusted: it asks, and is approved (ADR-0090).
    _, _, last_run = approving(server, token, conversation["id"], command)
    assert wait_for_run(server, token, last_run)["status"] == "completed"
    (last,) = default_model.endpoint.requests_with(command)[-1:]
    first, second = [str(m.get("content", "")) for m in last.body.get("messages", []) if m.get("role") == "tool"]
    assert first.count("a") < size
    # The rest is in the scratch folder, not in the workspace.
    counts = [line.strip() for line in second.splitlines() if line.strip().isdigit()]
    assert counts[:2] == ["1", "0"], second


@pytest.mark.spec("AGT-011")
def test_the_agent_can_delete_files_in_its_workspace(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    name = f"delete-{uuid7()}.txt"
    command = f"run:echo gone > {name} && rm {name} && ls {name} || echo removed-{name}"
    run_id, _ = start_run(server, token, conversation["id"], command)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (result,) = _tool_results(default_model, command)
    # The sandbox, not a list of command names, decides what a command can do (ADR-0062).
    assert f"removed-{name}" in result, result


@pytest.mark.spec("CNV-018")
def test_a_tool_result_with_a_nul_character_is_kept(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    # As `cat` of a binary file prints it.
    run_id, events = start_run(server, token, conversation["id"], "run:printf 'before\\000after'")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "before" in text_of(events)
    history = messages(server, token, conversation["id"])["items"]
    results = [str(message.get("content", "")) for message in history if message.get("role") == "tool"]
    assert any("before\ufffdafter" in result for result in results), results


@pytest.mark.spec("AGT-008")
def test_a_call_that_may_have_run_twice_after_a_crash_says_so(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    marker = f"marker-{uuid7()}"
    # The worker dies while the command runs; the run is replayed, and the command runs again.
    run_id, events = start_run(server, token, conversation["id"], f"run:sleep 3; echo {marker}", stop_after=4)
    assert any(event.type == "TOOL_CALL_START" for event in events), [event.type for event in events]
    server.crash_and_restart_worker()
    assert wait_for_run(server, token, run_id, timeout=120)["status"] in {"completed", "failed"}
    with server.client(token) as client:
        response = client.get("/me/activity", params={"conversation_id": conversation["id"], "tool": "run_command"})
    assert response.status_code == 200, response.text
    (event,) = body(response)["items"]
    assert event["run_id"] == run_id
    assert event["repeated"] is True


@pytest.mark.spec("SBX-023", "SBX-015")
def test_a_run_whose_sandbox_cannot_be_reached_fails_as_such(
    server: Server, token: str, default_model: HarnessModel, sandboxes: Driver
) -> None:
    conversation = create_conversation(server, token)["id"]
    # Without its egress rules, the driver refuses sandboxes until isolation is verified again (SBX-015).
    host_docker("exec", sandboxes.netguard, "nft", "delete", "table", "inet", "sibillo")
    try:
        deadline = time.monotonic() + 20
        while _driver_ready(sandboxes):
            assert time.monotonic() < deadline, "the driver kept accepting sandboxes without egress rules"
            time.sleep(0.5)
        run_id, events = start_run(server, token, conversation, "run:echo unreachable")
        run = wait_for_run(server, token, run_id)
        assert (run["status"], run["error_code"]) == ("failed", "sandbox.unavailable")
        assert events[-1].type == "RUN_ERROR"
        assert events[-1].data.get("code") == "sandbox.unavailable"
    finally:
        sandboxes.wait_until_ready()
