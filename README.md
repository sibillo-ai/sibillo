# Sibillo

**A private, self-hosted AI assistant for your household.**

> **Status: phase 1 has started.** Accounts, separate conversations with
> versions, streamed answers from a model you configure, and a per-user
> gVisor sandbox where the assistant runs commands, through a web app you can
> install on your phone and computer. Do not rely on it for anything
> important yet.

In the folklore of central Italy, the *mazzamurello* is a small household
spirit: it lives in the house, knows everything that happens there, and
quietly helps the family. Sibillo is one of them, by name. This project aims
to be exactly that — an assistant that lives on your own server, works for
your family, and keeps what it knows inside your home.

## What it will be

- **Self-hosted, server only.** One installation per household, deployed with
  Docker Compose on a Linux home server. Like Immich or Home Assistant, but for
  an AI assistant.
- **Private by design.** Your data stays on your server. Every user has private
  data, and every conversation a private, strongly isolated sandbox. Nothing
  runs on the host on behalf of users.
- **Capable.** The assistant can search the web, read pages, run code, install
  software and launch programs — inside each conversation's sandbox, which
  reaches the internet only once you allow it, and never your home network. Searches go through a search
  engine running on your server, never through the model's provider.
- **Model-agnostic.** Local models (Ollama, llama.cpp, any OpenAI-compatible
  server) or remote providers (e.g. OpenRouter), with per-user and per-space
  rules on what may leave the house.
- **Multi-user, multi-tenant ready.** Built for a family from day one, with a
  tenant model that also allows serving several households or a small
  organization with isolated, private data.
- **Separate conversations.** Many independent chats, one per purpose — on the
  web and on your phone.
- **Transparent memory.** Users can see, edit and delete everything the
  assistant remembers about them.

See [VISION.md](VISION.md) for the full picture, including what Sibillo
is deliberately **not**.

## Architecture at a glance

```
 phone / browser
        │  one public HTTP API (OpenAPI, SSE streaming)
 ┌──────▼─────────────────────────────┐   ┌──────────────┐
 │ control plane                      ├──►│ search       │  SearXNG: asks public
 │ (FastAPI, Pydantic AI, Postgres)   │   │ (queries     │  search engines, keeps
 └──────┬─────────────────────────────┘   │  only)       │  no logs
        │ minimal, authenticated API      └──────────────┘
 ┌──────▼──────┐
 │ sandbox     │  the only component allowed to manage containers,
 │ driver      │  in the sandbox engine: a Docker of its own, with gVisor
 └──────┬──────┘
 ┌──────▼──────┐ ┌─────────────┐ ┌─────────────┐
 │ sandbox A   │ │ sandbox B   │ │ sandbox C   │  one per conversation, gVisor,
 │ workspace A │ │ workspace B │ │ workspace C │  internet yes, LAN no, no secrets
 └─────────────┘ └─────────────┘ └─────────────┘
```

The reasoning behind every component is recorded in the
[architecture decision records](specs/adr/), and the security model in the
[threat model](specs/threat-model.md).

## Installation

Sibillo runs on one Linux host (x86_64 or arm64) with Docker Compose.
Hardware virtualization is not needed (OPS-009).

**Prerequisites**

- Docker Engine with a recent Compose plugin (2.40 is the one tested).
  Nothing else is installed on the host: gVisor, which isolates the
  sandboxes, comes inside Sibillo's own images (ADR-0114).
- Docker running as root, not rootless, and allowed to run a privileged
  container, on a host with cgroup v2 and loop devices, as every common
  distribution provides: the sandboxes run in a Docker of their own inside
  one privileged container, and each workspace is a disk of its own,
  attached to a loop device (ADR-0098).
- About 8 GB of disk for the images and the sandbox engine, and internet
  access to build them.

**Install**

```bash
git clone https://github.com/sibillo-ai/sibillo.git
cd sibillo/deploy
docker compose run --rm --no-deps init
docker compose up --detach --build --wait
docker compose run --rm setup
```

1. `init` writes `deploy/.env` with fresh random secrets. Keep it private; it
   is never overwritten. There are no default passwords anywhere (AUTH-007).
2. `up` builds the images and starts the database, the API, the worker, the
   search service, the backup service, the sandbox engine, the sandbox
   driver and the network guard. The engine is a Docker of its own, where
   the sandboxes run under gVisor; the guard keeps them away from your home
   network and from the host with a firewall table inside the engine. The
   host's Docker configuration and firewall are not changed. The first start
   takes about half a minute longer, while the engine loads the sandbox
   image.
3. `setup` asks for the household's name and creates its first administrator,
   with the password you choose. It works only once.

The web app now opens at `http://127.0.0.1:8080/` on the server itself, and
the API answers at `http://127.0.0.1:8080/v1`; `curl
http://127.0.0.1:8080/v1/health` says `degraded` until a model is configured.

**Connect a model**

Sign in to the web app as the administrator, open **Settings**, then
**Models**, and choose **Add a connection** (MOD-008):

- **OpenRouter** needs only its API key, and brings every OpenRouter model,
  most used first.
- **Your own server**, such as Ollama, llama.cpp, vLLM or LM Studio, needs
  its address, like `http://192.168.1.10:11434/v1`, and brings every model it
  serves. Addresses on your home network work only for the server's
  administrator, the account `setup` created (MOD-009).

The connection is tested step by step before it is saved; if it fails, the
test says which step failed and why. Then choose the **Default model** that
new conversations start with. Anyone in the household can switch models in a
conversation, from the message box. API keys are stored encrypted and never
shown again, and a key is sent only to the address it was given for: moving
a server that has a key to a new address asks for the key again, or for its
removal (ADR-0117).

The same can be done through the API. With Ollama on your network:

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "YOUR-USERNAME", "password": "YOUR-PASSWORD", "device_name": "terminal"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
CONNECTION=$(curl -s http://127.0.0.1:8080/v1/tenant/connections \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Home server", "kind": "openai", "base_url": "http://192.168.1.10:11434/v1", "location": "local"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')
curl -s -X PUT http://127.0.0.1:8080/v1/tenant/default-model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"connection_id\": \"$CONNECTION\", \"model\": \"llama3.2\"}"
```

For OpenRouter, send `{"name": "OpenRouter", "kind": "openrouter",
"api_key": "sk-or-..."}` instead; it reports the cost of each answer, which
is recorded as it is, in US dollars.

**Turn on voice**

Voice turns need a model that transcribes and a model that reads aloud
(UX-005, ADR-0088). They come from your connections, like chat models: in
**Settings**, then **Models**, choose the household's **Transcription model**
and **Speech model**, with its voice. Then the message box offers **Dictate**
and **Hands-free**, and every answer **Read aloud**. The assistant is told
when a message was dictated, so it reads past misheard words, and in
hands-free mode that its answer will be read aloud, so it writes it for
listening.

- **OpenRouter** lists its transcription and speech models and their voices.
  Your voice then leaves the household, as the settings and the hands-free
  screen say.
- **Your own speech server** keeps it at home: any server with
  OpenAI-compatible `/audio/transcriptions` and `/audio/speech`, such as
  [speaches](https://github.com/speaches-ai/speaches) (Whisper with Piper or
  Kokoro voices) or [LocalAI](https://github.com/mudler/LocalAI). Add it as a
  connection; its models whose names say `whisper`, `transcribe` or `stt`
  transcribe, those that say `tts`, `speech`, `voice`, `kokoro` or `piper`
  speak, and you type the voice's name. Small CPUs transcribe well with
  Whisper `small`; the local voices sound plainer than remote ones.

Hands-free mode is made for the car: one large button, and your headset's or
car's next-track button, start and end a turn, and short sounds tell you
when it listens, works and answers. Once an answer is read, it listens
again by itself, so a conversation needs one press per turn, to end it. Keep the phone unlocked with the app
open: a web app stops recording when the screen locks.

**Updating before the first release**

Until the first release, the database schema is rewritten instead of
migrated (ADR-0071). After an update that changes it, set the installation
up again, which deletes its conversations, accounts and settings; `deploy/.env`
and its secrets stay:

```bash
cd deploy
docker compose down --volumes
docker compose up --detach --build --wait
docker compose run --rm setup
```

**Reaching it from other devices**

By default the web app and the API listen only on `127.0.0.1:8080`. To reach
them from your phone, put them behind the reverse proxy you already use for
HTTPS (Caddy, Traefik, nginx), then set in `deploy/.env`:

```bash
SIBILLO_PUBLISH=127.0.0.1:8080
SIBILLO_TRUSTED_PROXIES=172.18.0.1
```

`SIBILLO_TRUSTED_PROXIES` is the address the API sees the proxy connect from, so
that rate limits count the real client (ADR-0047). For a proxy on the same
host it is the gateway of the deployment's network:
`docker network inspect sibillo_internal --format '{{(index .IPAM.Config 0).Gateway}}'`.
Run `docker compose up --detach --wait` again after changing `.env`.

The web app needs HTTPS, or `localhost`: it signs in with a `Secure` cookie,
which browsers keep only over HTTPS (ADR-0067). Through the proxy, open the
app's address on your phone and use the browser's **Add to Home Screen** to
install it. Publishing plain HTTP on your network
(`SIBILLO_PUBLISH=0.0.0.0:8080`) leaves only the API usable, and sends passwords
and tokens unencrypted: do it only on a network you fully trust.

The proxy must also let large uploads through: a file attached to a message
can be up to 1 GB (`SIBILLO_UPLOAD_MAX_MB`), and nginx refuses anything over
1 MB unless told otherwise. In nginx, add to the app's `server` block:

```nginx
client_max_body_size 1g;
```

**Passwords**

A household's administrator creates each member's account with a first
password (AUTH-002). That password only signs them in the first time: the
app then asks them to choose their own and shows nothing else until they do,
so that the administrator never knows the password they use (AUTH-012,
ADR-0105). Through the API, such an account is answered `403` with
`auth.password_change_required` until it calls `POST /v1/me/password`.

Anyone changes their password in **Settings**, then **Security**, with their
current one; their other devices are then signed out (AUTH-011). Nobody else
can change it, not even an administrator, so a forgotten password cannot be
recovered yet.

**Passkeys**

Each person can protect their account with passkeys, so that signing in
needs their phone or laptop, unlocked with a fingerprint, a face or a PIN,
on top of their password (AUTH-010, ADR-0094). Passkeys belong to the
address people open, so tell the API what it is, in `deploy/.env`, and run
`docker compose up --detach --wait` again:

```bash
SIBILLO_PUBLIC_ORIGIN=https://sibillo.example.org
```

Use the HTTPS address of your reverse proxy, or `http://localhost:8080` when
the app is only opened on the server itself. Passkeys work only at that
address: opened at another one, such as the server's address on your
network, the app signs in with passwords alone for accounts without
passkeys, and refuses the others. Then each person adds a passkey in
**Settings**, then **Security**, once on each device they use.

A passkey that is lost, with the phone it was on, never locks anyone out: a
household's administrator removes a member's passkeys in **Settings**, then
**Members**, and the member signs in with their password again. The
instance administrator's own are removed on the server:

```bash
docker compose run --rm setup sibillo_server remove-passkeys YOUR-USERNAME
```

**Notifications**

Each person can be told on their phone or computer when an answer is ready,
or when the assistant waits for their approval or an answer, while they are
away from the chat (UX-004, ADR-0101). Notifications need the same
`SIBILLO_PUBLIC_ORIGIN` as passkeys, and an HTTPS address, which browsers
require; nothing else to configure. Each person turns them on in
**Settings**, then **Notifications**, once on each device. On an iPhone or
iPad, add Sibillo to the Home Screen first and open it from there.

A notification says only what happened, never what the chat says. It
travels through the browser maker's push service (Google, Mozilla, Apple or
Microsoft), which learns that your server notified a device and when, but
nothing of the conversation. No notification comes for a chat that is open
on one of the person's devices.

While they are off on a device, the app says so in its menu, with a button
that turns them on; **Hide** hides that sign on that device.

**Sharing into Sibillo**

On Android, Sibillo installed on the home screen appears in the share sheet
of other apps (UX-006, ADR-0102). Sharing a page, a photo or a file to it
opens a new chat with the text and link in the message box and the files
attached; nothing is sent until you send it. What was shared stays on the
phone until then, and is offered only if you sign in within an hour. iPhones,
iPads and most computers do not let web apps join the share sheet: there,
attach files in the chat as usual.

**The assistant's language**

The assistant answers in the language you write in. In Settings, Assistant,
each person can choose a preferred language (I18N-003, ADR-0103): the
assistant then uses it for messages without a language of their own, such as
a shared link, a pasted equation or a file sent without a word, while a
message in another language, or a request for one, still gets its answer in
that language. The interface itself is in English for now.

**Memory**

The assistant remembers what each person would want it to know in their
other chats, such as who is in the household or how they like answers, and
says so in the chat whenever it remembers, changes or forgets something
(MEM-007, ADR-0095). Everything it remembers is listed in **Settings**, then
**Memory**, where each person edits or deletes any of it, adds their own, or
turns memory off. Temporary chats never use it. Memory is short, at most
10,000 characters a person, and it is given to the model whole in every chat,
so the data egress policy applies to it as to the rest of the chat.

An item the assistant wrote after reading a web page, a command's output or
an attached file is marked untrusted: it could have been planted by what it
read. Until its owner saves it, the assistant treats it with caution, and a
request for internet access says that the chat holds content from elsewhere. Deleting an item deletes it from
the database for good. It stays in three places outside memory: the chat
where the assistant wrote it, until that chat is deleted; backup archives,
until they are rotated; and, for remote models, whatever the provider keeps
of what it was sent.

**Skills**

Skills teach the assistant how to do a kind of task, in the open Agent
Skills format: a folder with a `SKILL.md` and any scripts or notes it needs
(AGT-017, ADR-0096). Every chat sees each skill's name and description, and
the assistant reads the rest only when a task calls for it. Sibillo comes
with built-in skills for PDF files, office files, images and media, data and
charts, and for making new skills. In **Settings**, then **Skills**, each
person turns skills on or off, writes their own, uploads a `.zip` or `.skill`
file, imports from a GitHub repository (`owner/repo`, or the address of a
folder of one) or from the address of an archive, and downloads any of
theirs. They can also ask the assistant to turn work it just did into a
skill, which it saves after they approve it. A chat's settings turn off
skills for that chat alone.

A skill's files are in the sandbox, read-only, at `/skills`: the assistant
runs a skill's scripts there, like any command, and cannot change them. A
skill someone else wrote, uploaded, imported, or saved by the assistant after
it read a web page or a command's output, is marked untrusted: while one is
on, every chat that is offered it counts as holding content from elsewhere,
because its description reaches the assistant whether or not it is used. A
request for internet access then says so, until its owner reads its files
and marks it trusted, or turns it off (ADR-0116). Imports are downloaded in a
sandbox of their own, never by the server. Skills are kept in the database,
so backups hold them.

**Web search**

The assistant searches the web through SearXNG, a search engine that runs
on your server as the `search` service and asks public search engines on
the assistant's behalf: they see your server's address and the query, never
who asked (ADR-0075). It keeps no logs. The engines it uses are set in
`deploy/search/settings.yml`: SearXNG's defaults, plus Google. Edit the file
and run `docker compose restart search` to change them. Pages the assistant
reads are fetched from the conversation's sandbox.

**Internet access**

A chat has no internet access until you give it (AGT-034, ADR-0113,
ADR-0115): its sandbox has no network at all, and the assistant can neither
search the web nor read pages. The **Internet access** switch in the chat's
top bar shows whether it has it, and turns it on or off at any time, also
while the assistant works; on the new-chat screen it gives it to the chat
from its first message. Nothing turns it on for new chats. Commands need no approval: without network they cannot
send anything out, and the tools of the sandbox need none. When the work
needs the internet, the assistant asks once, for all it is about to do:
**Deny**, **Allow for this turn** or **Allow in this chat**. The request
says what the assistant could then do, that what the chat holds could be
sent out, and whether the chat holds content from elsewhere that could be
steering it. Allowed for the turn, the switch stays on until the turn ends;
turning the switch on answers the request as **Allow in this chat**. A
denial holds for the rest of the turn. Turning the switch off, or
withdrawing internet access in **Chat settings**, takes the sandbox's
network at once. A fork starts without it, and no setting gives it
to new chats. In hands-free mode, the request plays a sound of its own, is
said aloud, and is answered only by its large buttons, never by voice.

Every setting is listed in the
[configuration contract](specs/contracts/configuration.md).

**MCP servers**

The assistant can use the tools of services that speak the Model Context
Protocol over Streamable HTTP, such as Home Assistant, GitHub, Notion or
Linear (AGT-019, ADR-0099). A household's administrator adds each one in
**Settings**, then **MCP servers**, with a name, a short prefix that its
tools carry for the model (`home` makes `home__HassTurnOn`), its address, and
how people sign in to it:

- **No sign-in**, for a server that needs no account;
- **Each person's own token**, such as a Home Assistant long-lived access
  token or a GitHub personal access token;
- **Each person signs in**, with OAuth, at the service's own sign-in page
  (ADR-0100). Sibillo finds the service's sign-in on its own. A service
  that reads Client ID Metadata Documents, such as Home Assistant, fetches
  Sibillo's own description of that service's client from
  `SIBILLO_PUBLIC_ORIGIN` followed by `/v1/mcp-client/` and the service's
  ID, so it must reach that address, over HTTPS; another service registers
  Sibillo when it allows it. Each service has its own callback, so that a
  sign-in to one cannot be finished as another (ADR-0122). For the rest,
  such as GitHub, create an OAuth app at the service, add the service in
  Sibillo with the app's client ID, then set the app's callback to the one
  Sibillo shows for that service.
  Signing in needs `SIBILLO_PUBLIC_ORIGIN` (see **Passkeys**).

Nobody shares an account: each person connects their own in **Settings**,
then **Services**, and acts on the service as themselves, with what their
account may do there. Give a token the least rights it needs. Removing it
in Sibillo forgets it; revoke it at the service to end it there too.

The administrator then reviews the server's tools, one by one, and accepts
those the assistant may use: the model reads every word of a tool's
description, and a server could hide instructions in it. A tool that
changes afterwards is not offered until it is accepted again; **Refresh**
shows what changed. The assistant asks before every call, showing its
arguments and the server's address, and treats what comes back as content
from elsewhere: after a call, a request for internet access says so. In **Settings**, then **Tool permissions**, an administrator
can deny a server to a member, and each person switches a server on or off
for themselves or for a chat, beside the other tools. A server on the
household's network, such as `http://homeassistant.local:8123/api/mcp`, can
be added only by the instance's administrator; anyone else needs a public
`https` address. A call that takes longer than two minutes is stopped
(`SIBILLO_MCP_CALL_SECONDS`).

**Tasks**

A task starts a conversation on its own, without anyone writing (TSK-001,
ADR-0106): a press review every morning, a weekly report, a word when
something happens. Each person makes theirs in **Settings**, then **Tasks**,
or asks the assistant in a chat, which proposes one for them to approve. A
task has instructions, written as in a chat, and one or more triggers:

- **A schedule**: a start, in the task's time zone, and how it repeats,
  written as calendars do (iCalendar, RFC 5545, as in Google Calendar):
  nothing to run once; `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` for
  weekdays; `RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=2` for the first Monday of
  the next two months; `UNTIL=` to stop on a date, `EXDATE` to skip one,
  `RDATE` to add one (ADR-0109). No more often than every 15 minutes. If
  the server was off when it was due, it runs once when it is back; after
  its last time, the schedule shows as ended.
- **A webhook address**, shown once, for anything that can send an HTTP
  request, such as a Home Assistant automation: the request's body, up to
  64 KiB, is the event the task reads. Replacing the address stops the old
  one at once.
- **An event of an MCP server** that offers the MCP Events extension, such
  as a new mail. The administrator accepts a server's event types in
  **MCP servers**, as its tools; Sibillo polls for them every minute or
  more, or, with `SIBILLO_PUBLIC_ORIGIN` set, the service delivers them to
  that address.

Each time it runs, the task starts a new conversation, listed with the
others and under the task, and the notification says it is ready. Nobody is
there to approve calls, so a task carries **grants**: **Internet access**,
for the web and its sandbox's network, the tools it may use without asking,
such as **Read files**, or one exact call, such as a fixed command. A call
no grant covers is denied without asking, and the answer says what could not
be done; continue the conversation to do it with the usual approvals.
Sibillo refuses grants that would let content read on the way send private
data out: a task with internet access can't also read files or use memory,
and a task started by an event can't have internet access. A task runs at most 10 times an hour and one run at a time; the
worker checks for due tasks every 30 seconds (`SIBILLO_TASK_SWEEP_SECONDS`).

**Run now** starts a task at once, also while it is paused, to try it;
**Edit** changes its instructions, triggers and grants. The new
conversation appears in the list as it starts, marked **Running** until its
answer is ready. In a chat, the assistant can list your tasks and how they
last went, and change one: it shows the whole change and waits for your
approval, as when it proposes a task.

**Your other chats**

The assistant can search your earlier chats and read one, to pick up where
you left off or say how a task went (AGT-032, AGT-033). It never sees
temporary chats, what you rewound, or anyone else's. If a chat it reads
holds content from elsewhere, such as web pages, the current chat counts as
holding it too, and a request for internet access says so.
Switch **Your other chats** off among the tools to keep each chat apart.

**Sandboxes and workspaces**

Every conversation has a sandbox of its own, which no other conversation
sees (ADR-0078). It keeps one folder, `/workspace`, for what the user wants
to keep from that conversation: scripts, results and notes the assistant
made. Everything else, including software installed into it and programs it
started, is discarded when the answer ends, and the next answer gets a new
sandbox (ADR-0076). Deleting a conversation deletes its workspace; a fork
starts with a copy. Each workspace has a quota, 2 GiB by default
(`SIBILLO_SANDBOX_WORKSPACE_QUOTA_MB`); the assistant is told when it nears it.

No sandbox can fill the server's disk (SBX-016, ADR-0098). Each workspace is
a disk of its own, the quota plus 10% and 32 MiB, and a write beyond it fails
inside the sandbox; everything outside the workspace is limited to 4 GiB
(`SIBILLO_SANDBOX_DISK_MB`), for the length of an answer. Disks are sparse
files under Docker's volumes: they take the space their files use, not their
size, so a household can promise more than the server holds; size the quota
with the number of conversations in mind. Raising the quota grows existing
disks; lowering it applies to new conversations only. Workspaces from before
these limits are converted the first time they are used, keeping their files.

Sandboxes resolve names only through the instance's resolver, Quad9 by
default (`SIBILLO_SANDBOX_RESOLVER`, which must be a public address): the
network guard blocks DNS to any other server (SBX-007).

**Files** opens a conversation's workspace beside it, or full screen on a
phone: browse it as a tree, preview text, images, PDF, audio and video,
download a file or a folder as a `.zip`, upload, rename, move and delete
(ADR-0079). Files attached to a message upload at once into
`/workspace/uploads/`, and the assistant can offer a file as a card with a
download button. Previews never run a file: an HTML page shows as its
source.

Pasting an image or a file into the message box attaches it, and attached
images show as small previews (UX-036). A model that accepts images sees
the PNG, JPEG, WebP and GIF images attached to a message, up to 5 MiB each,
and can look at any image of the workspace; the model picker marks such
models **Sees images**. A larger image, or one in another format, stays a
file: ask the assistant to shrink or convert it and look at the result.
With any other model the assistant says that it cannot see images.
OpenRouter and Ollama say which of their models accept images; for another
server, an administrator names them in the connection, under **Models that
see images** (MOD-020). A conversation keeps where an image is, never the
image: deleting the file takes it out of what the model is sent from then
on (CNV-020, ADR-0110).

Workspaces from before sandboxes were per conversation are no longer used:
`docker volume ls --filter label=dev.sibillo.sandbox=workspace` lists
them, and those without a third identifier in their name can be removed.

**Logs**

Every service logs to Docker, so `docker compose logs` shows them, for
example `docker compose logs --follow worker`. Docker keeps at most three
files of 10 MB per service and drops the oldest lines first (OBS-005), with
no change to the host: services created before this setting get it when they
are recreated, as `docker compose up --detach --build --wait` does. Logs
never carry messages, files, memory or credentials (OBS-003), and nothing
sends them anywhere. Sibillo collects no metrics (OBS-002, ADR-0104).

**Backups**

The `backup` service backs everything up every night at 03:00 UTC
(`SIBILLO_BACKUP_TIME`) into `deploy/backups/` (`SIBILLO_BACKUP_DIR`), and keeps the
newest 14 archives (`SIBILLO_BACKUP_KEEP`). Each archive is one encrypted file
with the database, the secret key and every workspace (ADR-0077). To make
one now:

```bash
docker compose exec backup python -m sibillo_server backup
```

Archives are encrypted with `SIBILLO_BACKUP_KEY` from `deploy/.env`. **Keep a
copy of that key away from the server**, for example in your password
manager: without it, no archive can be restored. An installation from
before backups gets its key with `docker compose run --rm --no-deps init`,
which adds only missing secrets. `/health` reports `degraded` when the last
backup failed or is more than two days old.

Copy the archives elsewhere too, for example with restic:
`restic -r sftp:nas:/backups/sibillo backup deploy/backups`. They are
already encrypted.

**Restore**

Into a fresh installation, on this server or another one, with the same
version of Sibillo:

1. Install as above with `init` and `up`, but without `setup`.
2. In the new `deploy/.env`, replace `SIBILLO_BACKUP_KEY` with your saved key,
   then put the archive into `deploy/backups/`.
3. Restore, then restart with the restored secret key:

```bash
docker compose run --rm restore /backups/sibillo-20261106T030000Z.tar.age
docker compose up --detach --wait
```

To bring back only one user's workspaces from an earlier archive, for example
after something went wrong in them, in a running instance:

```bash
docker compose run --rm restore --workspace alice /backups/sibillo-20261101T030000Z.tar.age
```

**Uninstall**

```bash
cd sibillo/deploy
docker compose down --volumes
```

This deletes the database, with every account and conversation, and the
sandbox engine, with every sandbox and workspace. Nothing of Sibillo is left
on the host but the images, which `docker compose down --volumes --rmi all`
removes too.

**Upgrading an installation that had gVisor on the host**

Earlier versions ran the sandboxes in the host's Docker, with gVisor
installed on the host. The database stays where it is, but workspaces do not
move by themselves: make a backup before the upgrade, and bring each user's
workspaces back from it after.

```bash
cd sibillo/deploy
docker compose exec backup python -m sibillo_server backup   # before updating the code
docker compose down
docker ps -aq --filter label=dev.sibillo.sandbox | xargs -r docker rm -f
docker volume ls -q --filter label=dev.sibillo.sandbox | xargs -r docker volume rm
docker network rm sibillo-sandboxes
git pull
docker compose up --detach --build --wait
docker compose run --rm restore --workspace alice /backups/THE-ARCHIVE-YOU-MADE.tar.age
```

Run the last command once for each user. gVisor on the host is no longer
used, and can be removed.

## How this project is built

Sibillo is written and reviewed by AI agents under strict human
direction. The method is simple to state:

1. **Specs are the source of truth.** Requirements have IDs, priorities and
   verification methods ([specs/](specs/)).
2. **Tests are the executable form of the specs.** They are written before the
   code, and implementation changes may not modify them.
3. **Code is ephemeral; contracts are not.** Code can be regenerated. Database
   schemas, public APIs, on-disk formats and security invariants cannot.
4. **Rules are enforced by CI, not by good intentions.** Pull request types,
   allowed paths, spec format and sign-offs are checked mechanically.

The rules every agent (and human) follows are in [AGENTS.md](AGENTS.md); the
full workflow is in [docs/development/workflow.md](docs/development/workflow.md).

## Repository map

| Path | Contents |
|---|---|
| [`VISION.md`](VISION.md) | What the project is, for whom, and what it is not |
| [`ROADMAP.md`](ROADMAP.md) | Phases and their exit criteria |
| [`AGENTS.md`](AGENTS.md) | Rules of engagement for AI agents and humans |
| [`specs/`](specs/) | Requirements, ADRs, contracts, glossary, threat model |
| [`docs/`](docs/) | Documentation (development workflow today, user docs later) |
| [`src/`](src/) | The server, the web app, the sandbox driver and the network guard |
| [`migrations/`](migrations/) | The database schema, as migrations |
| [`deploy/`](deploy/) | The Compose deployment and its images |
| [`tests/`](tests/) | The executable specs: design, integration, security, web and end-to-end tests |
| [`tools/`](tools/) | Repository governance checks run by CI |

## Contributing

Contributions are welcome, and they start from the specs: a new feature begins
as a spec proposal, not as code. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.
All commits require a [Developer Certificate of Origin](https://developercertificate.org/)
sign-off (`git commit -s`).

Please report security issues privately — see [SECURITY.md](SECURITY.md).

This project has a [Code of Conduct](CODE_OF_CONDUCT.md).
Governance is described in [GOVERNANCE.md](GOVERNANCE.md).

## License

Sibillo is free software: the server is licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE). If you run a
modified version as a service for others, you must offer them its source.

Specifications and documentation are licensed under
[CC BY 4.0](LICENSES/CC-BY-4.0.txt). Licensing of every file is declared in
[`REUSE.toml`](REUSE.toml) following the [REUSE](https://reuse.software/)
specification. See [ADR-0002](specs/adr/0002-licensing-agpl-dco-reuse.md).
