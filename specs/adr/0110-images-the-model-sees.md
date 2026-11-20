# ADR-0110: Images the model sees

- **Status:** Proposed
- **Date:** 2026-11-20
- **Deciders:** @tapionx
- **Related:** CNV-020, MOD-020, UX-036, CNV-017, AGT-003, MOD-003, UX-015, ADR-0079, ADR-0090, ADR-0093

## Context

A file attached to a message reaches the model as a path in the workspace
and a size (CNV-017, ADR-0079). For a photo or a screenshot that is not
enough: the model cannot see a path, and the sandbox has no text
recognition. Many models accept images, and their providers say which:
OpenRouter lists `input_modalities`, an Ollama server lists the capability
`vision`. Another OpenAI-compatible server says nothing.

Images are large, and they are untrusted content: a picture may hold
instructions, as a page of the web does. The control plane must not decode
them, since image decoders are a classic way into a process, and the
history of a conversation, kept in the database and sent again at every
request, must not grow by megabytes for each picture.

## Decision

1. **The gateway knows which models accept images.** A model of a
   connection has `images`: true, false, or unknown. For OpenRouter it is
   whether `architecture.input_modalities` holds `image`; for a recognized
   Ollama server, whether its capabilities hold `vision`. For any other
   OpenAI-compatible server it is unknown until a tenant admin says which
   of its models accept images: a list of model names kept with the
   connection, `image_models`, which listing the models again does not
   lose. What a recognized server says wins over the list. The API shows
   `images` wherever it shows `tools`, and the model picker shows it
   (UX-015).
2. **Only a model known to accept images gets them.** Unknown counts as
   no: an image sent to a model that cannot take it fails the request.
3. **An attached image reaches the model as an image, after the listing of
   attachments.** When a run starts, each attachment that is a PNG, JPEG,
   WebP or GIF image, told by its first bytes and never by its name, of at
   most 5 MiB, is read from the workspace through the sandbox driver and
   added to the user's message as an image. The listing with paths and
   sizes stays (CNV-017). A larger image, or another format, stays a path:
   the assistant can convert or shrink it in the sandbox and look at the
   result.
4. **A tool looks at an image of the workspace.** `view_image`, in the tool
   group Files, takes a path of the workspace and returns that image to
   the model, under the same limits. It is offered only to a model that
   accepts images. It reads untrusted content, as reading a file does, and
   follows the same tool permission and approvals as reading a file
   (ADR-0090).
5. **Images are untrusted content.** A message with attachments already
   counts as untrusted content (AGT-003); the result of `view_image` counts
   as well. Nothing changes in the lethal trifecta mitigation.
6. **The history keeps where an image is, never the image.** The stored
   message holds, for each image, its path in the workspace and the SHA-256
   of its bytes. Before each request to the model, the gateway puts the
   image in the place of that reference, read again from the workspace. An
   image that is gone, or whose bytes changed, becomes a line of text that
   says so. Rewinding and forks need nothing more: a fork copies the
   workspace (ADR-0076).
7. **The control plane never decodes an image.** It reads the first bytes
   to tell the format, hashes the file and passes it on. It never fetches
   an image from an address: only files of the conversation's workspace
   are sent, and only to the conversation's model, which the data egress
   policy already governs (MOD-003).
8. **A model that does not accept images is told so.** With such a model,
   the listing of attachments says that it cannot see the images and that
   it should tell the user, rather than try to read them some other way;
   `view_image` is not offered.
9. **Pasting attaches.** In the app, pasting files or an image into the
   message field uploads them as picking does (CNV-017); a pasted image
   without a name is named `pasted-image` with its format's extension.
   Attached images show as small previews: in the composer from the file
   on the device, in a sent message from the workspace's preview of the
   file (UX-020). Text pasted with no file is inserted as before.

## Consequences

- A photo of a letter or a screenshot of an error can be read by a model
  that accepts images; with any other model the assistant says it cannot.
- The database stays small, and a conversation's images follow its
  workspace: deleting the file takes the image out of later requests.
- Every request sends the images of the path again, which providers bill
  as input. Compaction replaces old turns with a summary, images included.
- Reading the images adds calls to the sandbox driver before a request,
  and starts the sandbox when it is not running.
- An admin of a server Sibillo does not recognize has one more thing to
  set, per model.
- The test harness's model lists which of its models accept images, as
  each kind of server does, and answers saying which images it received.

## Alternatives considered

- **Storing the images in the messages:** simplest, but megabytes of
  base64 in every stored message and checkpoint, and no way to forget an
  image the user deleted.
- **Sending images to every model and learning from the error:** a failed
  first turn for the user, and errors differ from server to server.
- **Shrinking images in the control plane:** it would decode untrusted
  images outside the sandbox. The sandbox has the tools for it.
- **Text recognition in the sandbox instead of images:** loses everything
  in a picture that is not text, and is a large addition to the sandbox
  image.
- **A switch for the whole connection instead of a list of models:** one
  server often serves models that see and models that do not.
