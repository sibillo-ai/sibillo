"""The browser of a sandbox, for tests (AGT-039, AGT-040, SBX-026, ADR-0138).

The browser tools' names, the call that loads them, and pages served from
inside a conversation's sandbox, on its loopback address, where its browser
and its page reader reach them without the internet.
"""

from __future__ import annotations

import json
import shlex

from tests.support.accounts import Account
from tests.support.sandbox import Driver

# The browser tools of ADR-0138 point 4, by the names the model knows them by.
BROWSER_TOOLS = frozenset(
    {
        "browser_goto",
        "browser_markdown",
        "browser_tree",
        "browser_links",
        "browser_interactive_elements",
        "browser_find_element",
        "browser_click",
        "browser_fill",
        "browser_press",
        "browser_select_option",
        "browser_set_checked",
        "browser_hover",
        "browser_scroll",
        "browser_wait_for_selector",
        "browser_wait_for_state",
        "browser_evaluate",
        "browser_extract",
        "browser_run",
        "browser_download",
        "browser_get_url",
        "browser_popups",
        "browser_page_tools",
        "browser_call_page_tool",
    }
)
# The deferred capability of the browser, and Pydantic AI's tool that loads it (ADR-0138 point 5).
CAPABILITY = "browser"
LOAD = f"load_capability {json.dumps({'id': CAPABILITY})}"
# How the capability appears in the catalog of deferred capabilities in the model's instructions.
CATALOG_ENTRY = f"\n- {CAPABILITY}:"
# The browser's process in a sandbox.
PROCESS = "lightpanda"

PAGE_PORT = 8765

# A search form whose answer only the page's script writes, without leaving the page.
LIBRARY = """<!doctype html>
<html><head><title>Town library</title></head>
<body>
<h1>Town library</h1>
<form id="search"><label for="q">Branch</label> <input id="q" name="q"> <button type="submit">Find hours</button></form>
<p id="result"></p>
<script>
document.getElementById("search").addEventListener("submit", function (event) {
  event.preventDefault();
  var branch = document.getElementById("q").value;
  document.getElementById("result").textContent = "The " + branch + " branch opens at {opening} on Saturdays.";
});
</script>
</body></html>
"""

# A page whose HTML holds a frame and a script, which writes the article.
SEED_SWAP = """<!doctype html>
<html><head><title>Seed swap</title></head>
<body>
<main id="app">Loading</main>
<script>
setTimeout(function () {
  document.getElementById("app").innerHTML =
    "<article><h1>Spring seed swap</h1>" +
    "<p>Bring seeds you saved last autumn in paper envelopes, labelled with the variety and the year.</p>" +
    "<p>The swap opens at {opening} in the hall behind the church, and tea is served all afternoon.</p>" +
    "</article>";
}, 50);
</script>
</body></html>
"""


def call(tool: str, **arguments: object) -> str:
    """A call of the chain the model the tests serve makes: `<name> <arguments>` (tests/support/model.py)."""
    return f"{tool} {json.dumps(arguments)}"


def command(text: str) -> str:
    """A call of the command tool, for a chain."""
    return call("run_command", command=text, description="Look inside the sandbox")


def chain(*calls: str) -> str:
    return "chain:" + " >>> ".join(calls)


def serve_pages(sandboxes: Driver, account: Account, conversation_id: str, pages: dict[str, str]) -> str:
    """Serve `pages` by name from inside the conversation's sandbox, until its next answer ends; their address there,
    ending with a slash."""
    tenant, user = str(account.tenant_id), str(account.id)
    for name, html in pages.items():
        written = sandboxes.sh(
            tenant, user, conversation_id, f"mkdir -p /tmp/site && printf %s {shlex.quote(html)} > /tmp/site/{name}"
        )
        assert written.exit_code == 0, written
    first = next(iter(pages))
    started = sandboxes.sh(
        tenant,
        user,
        conversation_id,
        f"cd /tmp/site && (setsid python3 -m http.server {PAGE_PORT} --bind 127.0.0.1 >/dev/null 2>&1 &)"
        f" ; for _ in $(seq 50); do curl -fso /dev/null http://127.0.0.1:{PAGE_PORT}/{first} && exit 0; sleep 0.1;"
        " done; exit 1",
    )
    assert started.exit_code == 0, started
    return f"http://127.0.0.1:{PAGE_PORT}/"
