"""Skills in the web client (UX-028, AGT-017, AGT-024 to AGT-026, ADR-0096).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in


def _skills_page(page: Page) -> None:
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    sections.get_by_role("group", name="Yours").get_by_role("button", name="Skills").click()


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nPlan the garden step by step.\n"


@pytest.mark.spec("UX-028", "AGT-017", "AGT-024", "UX-007")
def test_a_user_creates_edits_turns_off_and_deletes_a_skill(page: Page, member: Account) -> None:
    sign_in(page, member)
    _skills_page(page)
    skills = page.get_by_role("region", name="Skills")
    # The built-in skills come first, each with its switch, on.
    builtin = skills.get_by_role("list", name="Built-in skills").get_by_role("listitem")
    expect(builtin.first).to_be_visible()
    expect(builtin.first.get_by_role("switch")).to_be_checked()
    expect(skills).to_contain_text("No skills of your own yet")
    assert accessibility_violations(page) == []

    name = f"garden-{uuid4().hex[:6]}"
    skills.get_by_role("button", name="Create").click()
    dialog = page.get_by_role("dialog", name="New skill")
    dialog.get_by_label("SKILL.md").fill(_skill_md(name, "Use for garden plans."))
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_be_hidden()
    own = skills.get_by_role("list", name="Your skills").get_by_role("listitem")
    expect(own).to_have_count(1)
    expect(own.first).to_contain_text(name)
    expect(own.first).to_contain_text("Use for garden plans.")
    expect(own.first).to_contain_text("Written by you")

    own.first.get_by_role("button", name="Open").click()
    editor = page.get_by_role("dialog", name=name)
    expect(editor.get_by_role("list", name="Files")).to_contain_text("SKILL.md")
    editor.get_by_label("SKILL.md").fill(_skill_md(name, "Use for orchard plans."))
    assert accessibility_violations(page) == []
    editor.get_by_role("button", name="Save").click()
    editor.get_by_role("button", name="Close").click()
    expect(own.first).to_contain_text("Use for orchard plans.")

    switch = own.first.get_by_role("switch", name=name)
    switch.uncheck()
    page.reload()
    own = page.get_by_role("region", name="Skills").get_by_role("list", name="Your skills").get_by_role("listitem")
    expect(own.first.get_by_role("switch", name=name)).not_to_be_checked()

    own.first.get_by_role("button", name="Delete").click()
    confirm = page.get_by_role("alertdialog")
    expect(confirm).to_contain_text("cannot be undone")
    confirm.get_by_role("button", name="Delete").click()
    expect(page.get_by_role("region", name="Skills")).to_contain_text("No skills of your own yet")


@pytest.mark.spec("UX-028", "AGT-017", "AGT-025")
def test_an_uploaded_skill_is_marked_untrusted_until_trusted_after_its_files_are_shown(
    page: Page, member: Account, tmp_path: Path
) -> None:
    name = f"uploaded-{uuid4().hex[:6]}"
    archive = tmp_path / f"{name}.skill"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as written:
        written.writestr(f"{name}/SKILL.md", _skill_md(name, "Use for uploads."))
        written.writestr(f"{name}/scripts/run.sh", "echo run\n")
    archive.write_bytes(buffer.getvalue())
    sign_in(page, member)
    _skills_page(page)
    skills = page.get_by_role("region", name="Skills")
    skills.get_by_label("Upload a skill").set_input_files(str(archive))
    item = skills.get_by_role("list", name="Your skills").get_by_role("listitem").filter(has_text=name)
    expect(item).to_contain_text("Untrusted")
    expect(item).to_contain_text("Uploaded")
    expect(item).to_contain_text("someone other than you wrote")
    assert accessibility_violations(page) == []
    item.get_by_role("button", name="Trust").click()
    dialog = page.get_by_role("dialog", name=f"Trust {name}")
    # Its files are shown before it is trusted.
    expect(dialog).to_contain_text("scripts/run.sh")
    expect(dialog).to_contain_text("echo run")
    dialog.get_by_role("button", name="Trust").click()
    expect(item).not_to_contain_text("Untrusted")


@pytest.mark.spec("UX-028", "AGT-017")
def test_a_skill_is_turned_off_in_a_conversation(page: Page, member: Account, database: Database) -> None:
    name = f"conversation-{uuid4().hex[:6]}"
    content = _skill_md(name, "Use in one conversation.").encode()
    with database.superuser() as conn:
        skill_id = uuid7()
        conn.execute(
            "INSERT INTO skills (id, tenant_id, owner_id, name, description, origin, untrusted, size_bytes,"
            " created_at, updated_at) VALUES (%s, %s, %s, %s, 'Use in one conversation.', 'user', false, %s,"
            " now(), now())",
            (skill_id, member.tenant_id, member.id, name, len(content)),
        )
        conn.execute(
            "INSERT INTO skill_files (skill_id, tenant_id, owner_id, path, content)"
            " VALUES (%s, %s, %s, 'SKILL.md', %s)",
            (skill_id, member.tenant_id, member.id, content),
        )
    sign_in(page, member)
    _send(page, "hello")
    expect(page.get_by_role("main")).to_contain_text("hello", timeout=30_000)
    page.get_by_role("button", name="Chat settings").click()
    settings = page.get_by_role("dialog", name="Chat settings")
    switch = settings.get_by_role("group", name="Skills").get_by_role("switch", name=name)
    expect(switch).to_be_checked()
    switch.uncheck()
    assert accessibility_violations(page) == []
    settings.get_by_role("button", name="Save").click()
    expect(settings).to_have_count(0)
    page.reload()
    page.get_by_role("button", name="Chat settings").click()
    settings = page.get_by_role("dialog", name="Chat settings")
    expect(settings.get_by_role("group", name="Skills").get_by_role("switch", name=name)).not_to_be_checked()


@pytest.mark.spec("UX-028", "AGT-017", "AGT-026")
def test_loading_a_skill_shows_in_the_chat(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _skills_page(page)
    builtin = page.get_by_role("region", name="Skills").get_by_role("list", name="Built-in skills")
    name = builtin.get_by_role("listitem").first.get_by_role("switch").get_attribute("aria-label")
    assert name
    page.get_by_role("link", name="New chat").click()
    _send(page, f"tool:load_capability {json.dumps({'id': name})}")
    main = page.get_by_role("main")
    call = main.get_by_role("group", name="Using a skill")
    expect(call).to_contain_text(name, timeout=30_000)
    assert accessibility_violations(page) == []
    call.get_by_role("link", name="Skills").click()
    expect(page.get_by_role("region", name="Skills")).to_be_visible()
