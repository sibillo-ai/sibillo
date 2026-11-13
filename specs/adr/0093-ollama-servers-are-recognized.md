# ADR-0093: Ollama servers are recognized, and a cut prompt fails the run

- **Status:** Proposed
- **Date:** 2026-11-14
- **Deciders:** @tapionx
- **Related:** ADR-0041, ADR-0066, ADR-0069, ADR-0073, ADR-0081, ADR-0092, AGT-016, MOD-007, MOD-009, MOD-014, MOD-017, MOD-018, MOD-019, CNV-013

## Context

A connection to the household's own server has a context window, 8192
tokens unless a tenant admin sets another (ADR-0073), and it applies to
every model of the server. Ollama, the most common such server, runs each
model with a window of its own: `OLLAMA_CONTEXT_LENGTH`, a model's
`num_ctx`, or its default, 4096 tokens. Its OpenAI-compatible API, which
Sibillo uses, ignores a window sent with a request.

When a prompt is larger than that window, Ollama does not fail: it drops
the oldest part of the prompt, the instructions and the user's message
first, and answers what is left. With Sibillo's instructions and tools at
about 3,400 tokens, one page of search results is enough. The model then
answers as if nobody had asked anything, and neither the user nor Sibillo
can tell why. The first eval suite (ADR-0092) and the maintainer's own
conversation with a small local model both met it.

Ollama also says more than the OpenAI-compatible API does: `/api/version`
identifies it, `/api/show` lists each model's capabilities, among them
`tools` and `thinking`, and `/api/ps` lists the loaded models with the
window each runs with. A model is listed there only once loaded, that is
after a request.

## Decision

1. **A cut prompt fails the run.** After every model response, the gateway
   compares the prompt tokens the server reported with the model's context
   window as Sibillo knows it (point 3). A prompt that reached the window,
   less one token, was cut: the run fails with `model.context_exceeded`
   (MOD-017), and the answer is not kept. This holds for every connection;
   OpenRouter and servers that refuse a prompt too large never report one.
2. **Ollama is recognized.** When a connection of kind `openai` is added,
   its address changed or its models listed again, Sibillo asks
   `/api/version` at the root of its address, the address without a final
   `/v1`. A server that answers with a version is Ollama; the connection
   records it and the version. Its models' `tools` and `reasoning` then come
   from the capabilities `/api/show` lists, `tools` and `thinking`, instead of
   being unknown (MOD-014, CNV-013). These requests follow the connection's
   address rules (MOD-009).
3. **The served window.** After every model response from an Ollama
   connection, before point 1's check, the gateway asks `/api/ps` and records
   the window of the model, its *served context window*. The window Sibillo
   uses for the model, for the context meter (MOD-007), compaction (AGT-016)
   and point 1, is then the smaller of the served window and the
   connection's. Asking `/api/ps` failing changes nothing: the last recorded
   window stays. The window is kept in a table of its own, which any user of
   the household may write, since a run records it for whichever user it is
   for: a wrong value could only lower the window, and the model list, with
   its prices and capabilities, stays with tenant admins.
4. **The household admin is told.** Where a model's served window is smaller
   than its connection's, the connection's settings say so, with both
   numbers, and how to raise the server's: `OLLAMA_CONTEXT_LENGTH` on the
   server, then the connection's window to match.

## Consequences

- A conversation never continues from an answer to a prompt the model did
  not see whole; the user is told to start a new conversation or to raise
  the window, and the admin is told how.
- Compaction starts in time for small windows once Sibillo has seen the
  served window; before the first response it relies on the connection's.
- Small models without tools are recognized on Ollama, not found out by a
  failed run.
- One more request to the server after every response of an Ollama
  connection; it is local and small.
- Other servers, such as llama.cpp's or vLLM's, get point 1 only. They can
  be recognized the same way later.

## Alternatives considered

- **Sibillo sets the window:** Ollama's native API takes `num_ctx` with each
  request, so the connection's window would apply without configuring the
  server. It needs a second model client for one server, and every change
  of window reloads the model on a machine the household shares.
- **Warn and keep the answer:** the answer to a cut prompt is usually
  nonsense, as the conversation that found it showed.
- **Read the window once, when the models are listed:** `/api/ps` knows only
  loaded models, and the server's setting can change at any time.
