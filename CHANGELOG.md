# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Until 1.0.0, minor versions may contain breaking changes; each one will come
with migration notes.

## [Unreleased]

### Security

- A security audit's findings, fixed in ADR-0116 to ADR-0132: untrusted
  skills, connection keys and MCP client secrets sent to new addresses,
  sign-in rate limits checked before passwords, bounded request bodies and
  outbound responses, the egress table kept while sandboxes run, gates of
  the repository run from the base branch, OAuth mix-up, what a rewind
  leaves behind, web pages and links, memory in untrusted runs, the sandbox
  driver's bounds, backups, accounts and the HTTP surface, and durable runs.
- Migration notes: the database must be recreated (migration 0001 changed);
  everyone signs in again once (the session cookie is now
  `__Host-sibillo_session`); archives made before ADR-0130 cannot be
  restored; an MCP service with a client given by hand needs its new
  callback registered at the service, shown in its settings (ADR-0122).

### Added

- Members in the settings: a household's admins add members, change their
  role, disable them, give a new initial password and delete a disabled
  account with everything of its user (AUTH-013, AUTH-014, UX-044,
  ADR-0144).
- Budgets per member: a cost limit on remote models and a token limit on
  local ones, per day, week or month, checked before each model request,
  with each member's usage over time for them and their admins (MOD-004,
  MOD-021, UX-045, ADR-0145). Migration notes: the database must be
  recreated (migration 0001 changed).
- Project foundation: vision, governance, contribution rules, security policy.
- Specifications: glossary, threat model, architecture decision records
  ADR-0001 to ADR-0020, draft requirements for phases 0–3.
- Repository governance checks: spec linting, pull request path policy, DCO
  sign-off verification.
