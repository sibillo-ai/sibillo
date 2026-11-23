# ADR-0096: Skills kept by the control plane, given to each sandbox read-only

- **Status:** Proposed
- **Date:** 2026-11-15
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0035, ADR-0043, ADR-0044, ADR-0071, ADR-0076, ADR-0077, ADR-0078, ADR-0080, ADR-0081, ADR-0082, ADR-0087, ADR-0090, ADR-0095, AGT-003, AGT-004, AGT-017, AGT-024, AGT-025, AGT-026, SBX-021, SBX-022, UX-028, T-25, T-36

## Context

ADR-0044 chose the open Agent Skills format and the harness `Skills`
capability, and said that a user's skills would be copied into a reserved,
read-only directory of the user's workspace. Since then each conversation
has its own sandbox and workspace, which live for one answer (ADR-0078), and
only `/workspace` persists (ADR-0076): there is no workspace of the user to
copy skills into, and a directory inside a conversation's workspace would be
writable by the agent, kept in backups, and copied into forks.

Several forces shape the rest:

- **Where skills come from.** People write skills, find them in repositories
  of other people, or ask the assistant to make one from the work it just
  did. There is no open registry of skills that other agent tools agree on:
  directories such as skills.sh and SkillsMP index public Git repositories,
  and command-line installers take a repository, `owner/repo`, or a folder
  of one. A repository, a folder of one, or an archive is how skills travel.
- **Untrusted content.** A skill from someone else is instructions written by
  a stranger, and scripts the assistant will run (T-25). A skill the
  assistant saves after reading a web page may carry the page's injected
  instructions into every later conversation (T-36), as memory could
  (ADR-0095).
- **Context.** Only names and descriptions are in every run; the body and
  the files are read when needed (progressive disclosure). The sandbox
  toolbox (ADR-0080) is listed in full in every run's instructions today,
  and nothing keeps that list in step with the image.

## Decision

1. **The control plane keeps skills.** A user's skills are private rows,
   under the same row-level security as the rest of their data: a skill, and
   its files, each with its path and content. A skill holds at most 200
   files and 10 MiB, its `SKILL.md` at most 100,000 characters; a user has at
   most 100 skills and 100 MiB of them. A skill's name and description are those of its
   `SKILL.md`, validated with the harness's loader by the Agent Skills rules
   (a name of at most 64 lowercase letters, digits and single hyphens, a
   description of at most 1,024 characters), and a user's skill names are
   unique among their skills and the built-in skills. Skills are in the
   database, so backups hold them (ADR-0077).
2. **Built-in skills come with the instance** (AGT-024), in the server's
   package: always trusted, the same for every user, read-only. They teach
   the sandbox toolbox, one skill per kind of work: PDF files, office files,
   images and media, data and charts. A test checks that every tool the
   sandbox image installs is named in a built-in skill. The working
   instructions of the toolbox shrink to one sentence naming the tools,
   with the built-in skills for how to use them; ADR-0080 point 9 holds in
   that form. A built-in skill, making skills, tells the assistant how to
   write a skill in the Agent Skills format and save it (point 5).
3. **Skills reach a run in two ways.**
   - **The catalog and the bodies** are read by the worker when the run
     starts, for the skills that are on (point 6), and given to the harness's
     `Skills` capability through an in-process workspace backend
     (ADR-0043): the model sees each skill's name and description, and
     loads one with `load_capability`, which returns its body. Like memory
     items, skills are read for each run and never copied into a workflow's
     input (ADR-0095).
   - **The files** are given to the sandbox read-only at `/skills/<name>/`
     (SBX-022). Before a run's first command, the worker sends the driver an
     archive of the run's skills; the driver keeps it outside the
     workspace and mounts it read-only at `/skills` when it creates the
     sandbox's container, and deletes it with the container. The working
     instructions tell the model that a loaded skill's files are in
     `/skills/<name>/`, and that it runs a skill's scripts from there,
     reading and writing its own files elsewhere. Nothing at `/skills`
     persists, is backed up with the workspace, or can be changed by the
     agent.
4. **People make and bring skills in four ways** (AGT-017):
   - **in the editor** of the client: a new skill from a `SKILL.md`, and
     changes to the `SKILL.md` and the text files of a skill;
   - **by uploading an archive**: a `.zip` or `.skill` file holding one
     skill, with `SKILL.md` at its root or in its one top folder;
   - **by importing from a URL**: a GitHub repository, `owner/repo`, or a
     folder of one (`https://github.com/owner/repo/tree/ref/path`), or the
     URL of a `.zip` or `.skill` archive. The download runs in a sandbox of
     its own, with a fresh identifier and no conversation, which the API
     removes with its workspace when the import ends: the control plane
     never fetches the URL (ADR-0044, T-21). A source with several skills
     lists them, names and descriptions, and the user chooses which to
     import;
   - **by asking the assistant** (point 5).
   Archives are read by the control plane without being extracted to disk:
   entries outside the skill's folder, absolute paths, `..` segments, links,
   and archives beyond the limits are refused. A skill can be downloaded as
   a `.zip` archive, so that people can read every file and take it
   elsewhere.
5. **The assistant saves skills with a tool** (AGT-026): `save_skill`, with
   the path of a folder of the sandbox holding a `SKILL.md`, creates the
   user's skill of that name, or replaces the files of the user's skill of
   that name; built-in skills are never replaced. To change a skill, the
   assistant copies it from `/skills` into its scratch folder, edits it and
   saves it. Its declaration has no capability classes and asks for
   approval by default (AGT-005): unlike a memory item, a skill carries
   scripts and pages of instructions, and the approval shows the user the
   skill's name and description before it reaches later conversations. It
   is not offered in temporary conversations, as memory is not (ADR-0082),
   and clients list it in a group of its own, Skills, with its switch
   (ADR-0087).
6. **Which skills are on.** Each of a user's skills is on or off, and the
   user turns each built-in skill on or off for themselves: a new skill is
   on, and so are built-in skills until the user turns one off. A
   conversation can turn off skills that are on, as it turns off tools
   (CNV-013, ADR-0081): the conversation's own list starts empty, so that a
   skill the user turns on or adds later is on in their conversations. A
   run gets the skills that are on for the user and not off in its
   conversation; `load_capability` has no switch of its own, and the run has
   it only while a skill is on.
7. **Provenance** (AGT-025). Each skill records its origin: `user` when the
   user created it in the editor, `upload`, `import` with its URL, or
   `assistant` with the conversation and the time. Uploaded and imported
   skills are untrusted; a skill `save_skill` writes in a run that has
   untrusted content when it calls the tool (AGT-003) is untrusted, and
   otherwise trusted. Editing a skill does not change whether it is
   trusted: the user marks an untrusted skill trusted explicitly, after
   being shown its files, and that is the only way one becomes trusted.
   - The catalog marks untrusted skills, and their descriptions, as from an
     untrusted source: descriptions are short and bounded, so they do not
     make a run untrusted. Amended by ADR-0116: a run offered an untrusted
     skill has untrusted content from its start.
   - Loading an untrusted skill makes the run have untrusted content from
     that tool result on, so the trifecta rule applies (AGT-004): the
     loaded body is marked, as attachments are, and `has_untrusted_content`
     reads the mark, also in later runs of the path. Loading a trusted
     skill does not; reading any file of `/skills` with a tool that ingests
     untrusted content does, as it does for any file.
   - The scripts of every skill run only in the sandbox, as every command
     does (ADR-0062).
8. **Skills outlive their conversation** (ADR-0095 point 8): deleting,
   rewinding or forking a conversation does not change skills; a skill keeps
   the ID of the conversation that saved it as an identifier, without a
   reference. Deleting a skill deletes its rows. A skill turned off in a
   conversation and then deleted leaves its name in the conversation's list,
   where it is ignored; a new skill of the same name is then off in that
   conversation, which the client shows.
9. **API.** `GET /me/skills` lists the built-in skills and the user's, each
   with whether it is on, its provenance and its size; `POST /me/skills`
   creates one from a `SKILL.md`, or from an uploaded archive;
   `POST /me/skills/import` imports from a URL; `GET`, `PATCH` and `DELETE`
   on `/me/skills/{id}` read a skill with its list of files, turn it on or
   off, mark it trusted, and delete it; `PUT` and `DELETE` on
   `/me/skills/{id}/file?path=…` write and remove a text file, `SKILL.md`
   included, which renames the skill when its name changes; `GET` on it
   reads a file, and `/me/skills/{id}/archive` downloads the skill.
   Built-in skills are read the same way and turned on or off with
   `PATCH /me/skills/builtin/{name}`. Conversation settings gain
   `disabled_skills`.
10. **Clients** (UX-028) have a Skills page in the settings: the built-in
    skills and the user's, each with its switch, where it came from, and
    untrusted ones marked; creating, editing, uploading, importing,
    downloading and deleting, the last after asking; and marking trusted,
    after showing the files. Conversation settings list the skills that
    are on, each with a switch. In a conversation, loading a skill shows
    which skill the assistant is using, and a call to `save_skill` shows
    the skill saved, leading to the Skills page.

This refines ADR-0044 point 2: skills are given read-only to each sandbox,
not copied into a workspace. ADR-0044 stays in force otherwise.

## Consequences

- Skills from other agent tools work unchanged when they need only
  instructions, files and a shell; a skill that relies on another tool's
  placeholders, hooks or allowed tools gets none of them.
- Every run whose skills are on pays for their names and descriptions,
  about 100 tokens per skill; a run that runs a command sends one archive of
  its skills to the driver first.
- The toolbox's instructions shrink, and the image cannot gain a tool that
  the built-in skills do not describe.
- An untrusted skill costs nothing until the assistant uses it; using one
  can then ask the user to approve a search, until they mark it trusted.
- A household can share a skill only by downloading and uploading it, until
  shared spaces (TEN-007).
- `ToolName`, the tool switches and the tool declarations grow by one tool;
  `load_capability` is declared, without a switch.

## Alternatives considered

- **Skills in a folder of each conversation's workspace:** no change to the
  driver, but the agent can change them, backups and forks copy them, and
  quotas count them.
- **Reading skills from the sandbox at the start of every run:** the harness
  reads the catalog through the run's workspace, but every run, even one
  that runs no command, would start a sandbox.
- **One registry, such as skills.sh:** its API needs an account with a
  vendor, and it indexes GitHub, which a URL reaches directly.
- **Downloading imports in the control plane:** simpler, but it fetches
  arbitrary URLs from inside the instance (T-21), and outbound requests go
  only to declared destinations (ADR-0072).
- **Treating untrusted skills as untrusted from the start of every run,** as
  memory items are: a user with one imported skill would be asked to approve
  the first search of every conversation, used or not. Chosen by ADR-0116,
  once ADR-0113 made searches follow internet access instead.
- **Trusting a skill when the user edits it,** as saving a memory item does:
  an edit to `SKILL.md` says nothing of the scripts beside it.
- **Scanning skills for injected instructions** with the harness's artifact
  scanner: heuristic, and no substitute for provenance; a later ADR may add
  it as a warning on the Skills page.
