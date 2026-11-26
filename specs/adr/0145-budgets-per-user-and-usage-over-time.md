# ADR-0145: Budgets per user, and usage over time

- **Status:** Accepted
- **Date:** 2026-11-26
- **Deciders:** @tapionx
- **Related:** MOD-004, MOD-006, MOD-007, MOD-010, MOD-021, TEN-007, UX-045, ADR-0042, ADR-0069, ADR-0073, ADR-0091

## Context

The cost ledger records every model request made for a user, with its
tokens and its cost, and no content (MOD-006, ADR-0042). A user sees their
own spend over the last 24 hours and the last 30 days (MOD-007), and nobody
else sees it: the ledger is private, and its contract promised tenant
admins "a function that returns only sums per user".

Nothing limits what a member spends. A household that pays for a remote
provider, such as OpenRouter, finds out at the end of the month what a
teenager's long conversations cost; one that runs its own models, such as
Ollama, has no money to count but a machine that one member can keep busy.

MOD-004 asked for spending limits per user and per tenant in phase 4, in one
sentence. What a limit counts, over which period, and what a run does when
it is reached were left open.

## Decision

We will:

1. **Give each user a budget of up to two limits,** set by a tenant admin:
   - a **cost limit**, an amount in a currency, on the requests to remote
     models (MOD-010), which are the ones that cost money;
   - a **token limit**, on the input and output tokens of the requests to
     local models, which cost nothing but the household's hardware.
   Each limit has its own period and time zone. A user may have either,
   both or neither.
2. **Count calendar periods,** not rolling windows: a day from midnight, a
   week from Monday, a month from its first day, in the limit's time zone,
   which the web app sets to the admin's own. A period's share used reads
   plainly ("62% of this week"), and it starts again at a moment everyone
   can tell, rather than a little at a time as old requests leave a
   window.
3. **Count from the cost ledger.** A cost limit counts the cost of the
   user's entries in its currency since the period started; the price of
   local models is zero, so they add nothing. A token limit counts the
   input and output tokens of the entries whose `price_source` is `free`,
   which are those of local models. A remote request whose price is unknown
   has no cost to count: it is counted as unpriced, as on the usage page
   (MOD-007), and an admin who sees such requests can choose a model whose
   provider reports its price.
4. **Check before each model request,** in the model gateway, as the data
   egress policy is checked (ADR-0091): before every request of a run,
   compaction and delegated runs included, before a conversation's title,
   and before speech. Once a period's use reaches its limit, no request for
   that kind of model is sent until the period ends:
   - a new run is refused with `409 budget.exhausted`, before it is
     created, when its model is of the kind whose limit is reached; so is
     speech;
   - a run in progress, including a task's run, fails with the run error
     `budget.exhausted` before its next model request. Its tool calls run
     between requests, so a run never stops in the middle of one;
   - a title is not asked for: the conversation stays without one, as when
     its title fails.
   The cost of a request is known only once it is answered, so the last
   request of a period may go over the limit by its own cost. This is
   accepted.
5. **Store budgets in a table of the tenant's configuration,** `budgets`,
   one row per user and kind of limit. Its user reads it, so that the
   gateway checks it under the user's request context; tenant admins read
   and write the rows of their tenant (ADR-0069). A tenant admin may set
   their own budget too.
6. **Show usage over time to the user and their tenant admins** through one
   function of the database contract, `usage_of_user(user_id, time_zone)`.
   It is `SECURITY DEFINER`, checks that the caller is the user or a tenant
   admin of their tenant, and returns only sums per day, in the given time
   zone, per provider, model, price source and currency. The API builds
   from it the user's totals since the account was created, per month, per
   day over the last 30 days and per model, and the state of each limit.
   Nothing per conversation or per run leaves the function, so a tenant
   admin learns how much and with which model, never about what (TEN-007).
7. **Warn before the limit.** The usage overview gives each limit's share
   used, and the web app warns the user where they write once a limit's
   current period is 80% used, and says, when a run is refused, that the
   budget the household's admin set is used up until a given time.

## Consequences

- MOD-004 moves from phase 4 to phase 3, rewritten; MOD-021 and UX-045
  are new. A budget for the whole household is left out: a household that
  wants one sets the limits of its members to add up to it.
- Every model request reads the user's budget and, when they have a limit
  for its kind, sums the ledger since the period started, indexed by owner
  and time.
- A run of a task can fail on its budget at night; its conversation shows
  the error, and the task's next firing tries again.
- The ledger keeps no location; a token limit relies on `price_source`
  being `free` exactly for local models, as the gateway and speech record
  it (ADR-0069).
- Budgets are configuration, not privileges: any tenant admin sets any
  member's, an instance admin's included.

## Alternatives considered

- **One limit in money for every model, local ones at an imputed price:** a
  household would have to make up a price for its own hardware.
- **Rolling windows (the last 7 days):** what is left changes every hour,
  and "the budget is used up until …" has no single answer.
- **Refusing only new runs, letting the one in progress finish:** a long
  run, or a task, would spend without bound once started.
- **Stopping a run during a tool call:** the tool's work, such as a
  command, would be cut halfway, and the run's history left with a call
  without a result.
- **Granting tenant admins `SELECT` on the ledger:** every entry, with its
  conversation, run and time, would reach the admin; the function returns
  only sums per day.
- **Limits on the number of requests:** they say nothing of cost, and a
  request with a large context costs a hundred small ones.
