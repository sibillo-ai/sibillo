# ADR-0138: A browser in the sandbox

- **Status:** Proposed
- **Date:** 2026-11-24
- **Deciders:** @tapionx
- **Related:** AGT-003, AGT-014, AGT-021, AGT-034, AGT-039, AGT-040, SBX-001, SBX-008, SBX-018, SBX-021, SBX-024, SBX-026, ADR-0030, ADR-0072, ADR-0074, ADR-0075, ADR-0078, ADR-0080, ADR-0087, ADR-0090, ADR-0113, T-08, T-50, T-51

## Context

`read_page` fetches a page and keeps its main text with Trafilatura, without
running its scripts (ADR-0075). Many pages build their content with
JavaScript: their HTML holds a frame and a script, and `read_page` returns a
few words. ADR-0075 left pages that need JavaScript, and browser automation,
for later; the roadmap places browser automation in the sandbox in phase 4.

Pages are also more than text to read. Finding a train, filtering a list of
flats or paging through results means typing in fields, choosing from menus
and clicking, step by step, looking at the page between steps. The model
needs a browser it can drive, one action per tool call.

Each conversation has its own sandbox, which lives for one answer
(ADR-0078); a household's server runs several at once. A browser in each
must cost nothing to the conversations that do not use it, and little to
those that do. The same holds for the model's context: the definitions of
the browser tools below take about 30,000 characters with Lightpanda's
descriptions, and about 6,000 with a first sentence each and bare
parameters, measured on 2026-11-24; tools offered to the model are sent with
every request of every run.

Pydantic AI 2.64, the version in the lock file, has deferred capabilities:
a capability with `defer_loading` keeps its tools and instructions from the
model, which sees only the capability's name and description in a catalog of
its instructions, and a `load_capability` tool. When the model calls it, the
capability's tools and instructions are offered from the next request on.
Which capabilities are loaded is read from the message history, so a load
holds for the rest of the conversation. On providers with a native surface
for it (Anthropic, OpenAI) the tools are revealed without invalidating the
prompt cache; elsewhere the cached prefix is lost once, when the capability
is loaded.

Lightpanda is a headless browser written for automation, AGPL-3.0 like
Sibillo, as one binary. It runs pages' JavaScript, but does not lay out or
paint them. Besides fetching a page as Markdown, HTML or a semantic tree, it
serves its tools over the Model Context Protocol (`lightpanda mcp`): opening
an address, reading the page whole or in part, listing and finding its
interactive elements, clicking, filling, pressing keys, choosing options,
waiting, running JavaScript in the page, extracting data with selectors,
downloading files with the session's cookies, and calling the tools a page
registers for agents (WebMCP). Some of its tools ask a decision model of a
third party (Gemini or TypeSafe, with an API key): `login`, `acceptCookies`
and `classify`; `search` calls search services with keys. It sends usage
telemetry to its makers unless `LIGHTPANDA_DISABLE_TELEMETRY` is set.

A spike on 2026-11-24 compared it with Chromium, on Ubuntu 26.04 with kernel
7.0, an AMD Ryzen 9 5950X without `/dev/kvm`, gVisor `release-20261116.0`,
in a sandbox engine of its own beside the deployment's. Each measurement ran
in a new gVisor sandbox with the limits of a real one (1 CPU, 1 GiB) and the
sandbox image; memory is the peak of the sandbox's control group, about
11 MB when idle. Lightpanda 1.0.5 ran with no option for gVisor; Chromium
was Playwright 1.65's headless shell, with `--disable-dev-shm-usage`. Pages
were loaded until the network was idle, for at most 15 seconds.

| | Lightpanda 1.0.5 | Chromium headless shell |
|---|---|---|
| Added to the sandbox image | 78 MB (29 MB compressed) | 583 MB, with its system libraries and Playwright |
| Simple pages (Wikipedia, Hacker News, a page rendered by JavaScript) | 0.9–1.3 s, 23–34 MB | 3.4–3.8 s, 215–247 MB |
| Heavy pages (ANSA, Booking, Subito) | 3–5 s, 120–133 MB | 8–9.5 s, 367–409 MB |
| An application written in JavaScript (Uniswap) | 9.6 s, 203 MB | 17 s, 518 MB |
| Reddit | 13 s, 262 MB, the posts | blocked: "You've been blocked by network security" |
| ilmeteo.it | an empty page: a script of the page fails in it | read |
| immobiliare.it; npm, once | 403, a check against bots | the same |
| Three tasks driven a step at a time: paging, a search form, a React application | 3 of 3, 4.5 s, 52 MB | 3 of 3, 6 s, 299 MB |

Chromium's times include about 2 seconds to start Python, Playwright and
the browser; once started, it was slightly faster at each step. On the same
16 pages, `read_page` returned less than 200 characters for 5 that
Lightpanda read, and failed on npm, which Lightpanda read once.

## Decision

1. **Lightpanda is in the sandbox image,** one release from its official
   repository, pinned and verified by checksum when the image is built, and
   raised like any pinned version. The image sets
   `LIGHTPANDA_DISABLE_TELEMETRY=true`, and gives no API key of any
   service to it or to anything else (SBX-008). Chromium is not in the
   image.

2. **It runs only when used.** No browser runs when a sandbox starts. The
   first browser tool called in a sandbox starts one, as a background
   process of the sandbox; later calls in the same sandbox use it, with its
   page, its cookies and its scripts' state. A sandbox has at most one
   browser. It lives as long as its sandbox: through a run that waits for
   the user's answer or approval (SBX-018), not beyond the answer. Nothing
   of it is kept in the workspace: no cookies, no profile. A browser that has
   died, killed by the sandbox's memory limit or by a command, is started
   again by the next call, whose result says that the browser started
   afresh, so that the model does not act on a page that is gone.

3. **How the harness reaches it.** The browser listens for the Model Context
   Protocol over HTTP on the sandbox's loopback address only. Each browser
   tool runs a client command of the sandbox image, `sibillo-browser`, in
   the conversation's sandbox, through the sandbox driver, as `read_page`
   runs its reader (ADR-0075): the client starts the browser when none
   answers, passes it one call and prints its result. No new path between
   the control plane and the sandbox is opened, and the browser is reached
   from nowhere but the sandbox itself, whose commands may use it too: they
   run with the same rights.

4. **The browser tools are tools of the system.** Their names, descriptions
   and parameters are written by the system, shorter than Lightpanda's, and
   checked against the pinned release; an upgrade of Lightpanda never adds
   or changes a tool the model sees. They are:

   | Tool | Lightpanda's | What it does |
   |---|---|---|
   | `browser_goto` | `goto` | Opens an `http` or `https` address |
   | `browser_markdown` | `markdown` | The page, or one element, as Markdown |
   | `browser_tree` | `tree` | The page's semantic outline, with node IDs |
   | `browser_links` | `links` | The visible links |
   | `browser_interactive_elements` | `interactiveElements` | The elements one can act on |
   | `browser_find_element` | `findElement` | Elements by role and accessible name |
   | `browser_click` | `click` | Clicks an element |
   | `browser_fill` | `fill` | Types into a field |
   | `browser_press` | `press` | Presses a key |
   | `browser_select_option` | `selectOption` | Chooses an option of a menu |
   | `browser_set_checked` | `setChecked` | Checks or unchecks a box |
   | `browser_hover` | `hover` | Moves the pointer over an element |
   | `browser_scroll` | `scroll` | Scrolls the page or an element |
   | `browser_wait_for_selector` | `waitForSelector` | Waits for an element |
   | `browser_wait_for_state` | `waitForState` | Waits for the page to load or the network to be idle |
   | `browser_evaluate` | `evaluate` | Runs JavaScript in the page |
   | `browser_extract` | `extract` | Extracts data with CSS selectors |
   | `browser_run` | `run` | Runs a script of several pages, such as reading ten addresses at once |
   | `browser_download` | `download` | Saves a file into the sandbox, with the session's cookies |
   | `browser_get_url` | `getUrl` | The current address |
   | `browser_popups` | `popups` | The windows the page opened |
   | `browser_page_tools` | `pageTools` | The tools the page registers for agents |
   | `browser_call_page_tool` | `callPageTool` | Calls one of them |

   They are not in the model's context until it asks for them (point 5).

   Left out: `login`, `acceptCookies` and `classify`, which send the page to
   a decision model of a third party with a key in the sandbox, and `login`
   also the user's password; `search`, which needs keys, where `web_search`
   exists (ADR-0074); `getEnv`, which reads credentials the sandbox does not
   have; `getCookies`, which would put session tokens in the model's context;
   `save`, which writes a reusable script for automations Sibillo does not
   have; the session tools, since a sandbox has one browser; and `html`,
   `screenshot`, `nodeDetails`, `detectForms`, `structuredData`,
   `consoleLogs` and `waitForScript`, which the tools above cover.

5. **The browser is loaded on request.** The browser tools, and the
   working instructions about them, are one deferred capability of Pydantic
   AI, `browser`, with a description of one sentence: what the browser is
   for, and that `read_page` is enough to read a page. Until the model loads
   it with `load_capability`, the model sees that sentence and the
   `load_capability` tool, and nothing else of the browser; once loaded, the
   browser tools are offered for the rest of the conversation, and loading it
   again changes nothing. Loading it runs nothing in the sandbox and needs no
   internet access: the browser starts with the first browser tool called
   (point 2). The capability is offered while any browser tool is switched on
   (point 6), with only the tools that are; with all of them off, it is not
   in the catalog. `load_capability` is the framework's tool, not a browser
   tool: it has no switch of its own, and its result is the system's, not
   untrusted content. A model that should have browsed and did not is caught
   by evals, and `read_page` renders pages that need JavaScript without
   any load (point 7).

6. **They are web tools.** The browser tools have the classes of `read_page`,
   `ingests_untrusted` and `external_communication`, and need internet
   access as it does (AGT-034): without it they do not run, and a call asks
   for it in the same approval request as the other web calls of the run.
   Without internet access the sandbox has no network, so neither has the
   browser. Their results are untrusted content (AGT-003), each starting
   with the line that says so, and bounded like other tool output: a long
   page reaches the model as an excerpt, and the rest stays in the scratch
   folder, where the model can search it (AGT-014). Each tool has its
   switch, in a Browser group of the clients (ADR-0087). Downloads land in
   the sandbox: in the scratch folder unless the model names a path in the
   workspace.

7. **`read_page` renders pages that need JavaScript.** The reader first
   reads the page as it does today. When that fails, or keeps less than
   1,000 characters of main text, it loads the page in Lightpanda (`fetch`,
   until the network is idle, for at most 10 seconds), and returns the
   rendered page as Markdown, without what Lightpanda's reader mode strips
   as clutter, with a note that it was rendered. It runs its own browser
   process, which ends with the read: it does not touch the session of the
   browser tools. Its output is bounded like any other (AGT-014).

8. **Tests** never reach the internet: as for the reader (ADR-0075), pages
   are served from inside the sandbox, on its loopback address, including
   pages that build their content with JavaScript and forms to fill. The
   tests verify that a sandbox starts no browser until a browser tool is
   called, that the browser listens on loopback only, that the image sets
   `LIGHTPANDA_DISABLE_TELEMETRY`, and that the browser tools do not run
   without internet access, and that a run that has not loaded the browser
   is offered none of its tools.

9. **Declared destinations** (ADR-0072): nothing changes for the control
   plane. The sandbox reaches the internet only with internet access, and
   the browser is one more program in it; its telemetry is turned off by
   the image.

## Consequences

- The model reads pages that need JavaScript, and acts on sites step by
  step: searching, filtering, paging, filling forms.
- A conversation that does not browse pays nothing but the disk of a larger
  image, once for the instance: 78 MB, and the time CI takes to load it. One
  that browses pays about 25 to 260 MB while its browser runs.
- A conversation that does not browse carries one line of the catalog and
  the `load_capability` tool in its context, instead of 23 tool
  definitions. One that browses spends one step to load the browser, once,
  and on providers without native tool search loses its cached prompt
  prefix once.
- A model may miss that it can load the browser, and settle for what
  `read_page` gives. Evals must show that models load it when a task needs
  a site, and do not when reading is enough.
- Sites that check for bots still refuse the browser, as they refuse
  `read_page`, and some pages break in a browser that is not a complete one,
  as ilmeteo.it does: the model can say so, and the user can paste the page.
- A login does not survive the turn, and the browser tools cannot sign in
  with the user's credentials: that needs a decision of its own, about where
  passwords live and who types them.
- Driving a site lets injected instructions in a page act on that site: fill
  and send forms, follow links, post where no sign-in is needed. What the
  conversation holds can be sent out this way as with any web call, which
  internet access already governs (T-08, T-50).
- Lightpanda is young, and its compatibility changes with every release:
  upgrades are reviewed, and the spike's pages are worth trying again.

## Alternatives considered

- **Chromium in the sandbox:** the most complete browser, and the one that
  read ilmeteo.it. It made the image 583 MB larger, used three to ten times
  more memory per page, took longer for each page, and was blocked by
  Reddit as a headless browser. It may come back as a fallback for pages
  Lightpanda cannot read, if they prove common.
- **A browser service of the instance, with a context per conversation:**
  one process for all conversations costs less memory, but a renderer
  exploit would reach every conversation's pages and sessions, and the
  control plane would fetch addresses chosen by the model, against AGT-013
  and the reasons ADR-0075 gave for keeping SearXNG out of the sandbox
  network.
- **A browser service of a third party** (Browserbase, Steel, Cloudflare's
  rendering): nothing to run, but every page the household reads, and what
  it types, would pass through a company and an account, the reason
  ADR-0074 keeps web search in the instance.
- **The 23 browser tools always offered:** simplest, and the model needs no
  step to find them, but they would cost about 2,000 to 7,500 tokens to every
  request of every conversation, browsing or not.
- **Fewer tools with more parameters,** such as `browser_read` with a view and
  `browser_act` with an action: about six definitions, always offered. Their
  cost is smaller but paid by every request still, and a parameter that
  changes what a tool does is easier for a small model to get wrong than a
  tool of its own.
- **A built-in skill and a command, without tools:** the browser driven with
  a command of the sandbox, such as `sibillo-browser click "li.next a"`,
  through `run_command`, taught by a built-in skill (AGT-024). It costs the
  skill's line until used, and commands already carry the rules of
  untrusted, bounded output and of the sandbox's network. But the tools lose
  their switches and typed parameters, a model must write the command line
  right, and the browser's calls are told apart from other commands only by
  reading them.
- **Only rendering in `read_page`, without browser tools:** cheaper in
  context, but the model could not act on a page, and a site that needs a
  search or a click stays out of reach.
- **A new browser for every call, replaying the earlier steps:** no process
  to keep, but slow, and steps that send a form would be sent again.
- **The model writing a script for each task (`browser_run` alone):** no
  state between calls, but the model plans every step without seeing the
  page in between, which is what driving a browser is for.
- **Lightpanda's MCP server as an MCP server of the user (AGT-029):** its
  tool list would follow the binary, including the tools that call third
  parties, and MCP servers are reached from the control plane, not run in a
  sandbox.
