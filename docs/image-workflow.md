# Image observation and reinspection

Image viewing uses the model role that actually serves the turn, not a separate judge. That is normally the coder; the classifier sends question-class turns ("what does this image say?") to the reasoner, so declare the same `vision`/`vision_model` on `[roles.reasoner]` when it serves the same backend (a role without its own declaration never views images). Vision capability defaults to unknown. To opt in, merge these settings into the existing operator configuration, using the exact model identity resolved by the configured HTTP backend:

```toml
[roles.coder]
backend = "existing-http-backend"
vision = true
vision_model = "<exact wire model id>"
```

The backend table must already exist. For a served backend, the pin must match its `/v1/models` identity; for a keyed backend, it must match its configured wire model. A harness alias does not supply capability. Unknown, false, missing discovery, different providers/models, CLI backends and unresolved routes cannot authorize an image POST. `vision = true` requires a nonempty string model pin. Changing models requires deliberate configuration of the new identity.

Workspace reinspection has a separate, default-unbound harness contract. Only when the operator knows this deployment uses the native `view_image(path)` harness tool should they declare:

```toml
[tools]
workspace_image_tool = "view_image"
```

Merge this into an existing tools table rather than duplicating it. A request must also offer that tool with a compatible string `path` schema. A matching client name, schema, marker or path-shaped text alone never binds the contract. Other native contracts are currently unsupported. Attachment observation does not require this workspace declaration.

The original image remains private until a completed observation is correlated with its exact occurrence, selected provider, applied coder role/model and actual image-bearing POST. Subsequent coder context contains a labelled historical account, extracted text, uncertainty and a reinspection reference. It does not claim the account is verified perception. Task/root packets and unrelated tool history are preserved; projection happens only in the prepared model view.

For a retained attachment, `reinspect_image` sends the original source to the same coder again. For a workspace reference, it emits a fresh native read for the harness to execute. The returned image becomes a new occurrence and observation; the server does not read the workspace locally or silently reuse old pixels as current file contents. Data URLs retain their encoded source; remote URLs remain references rather than frozen remote bytes.

Private producer-issued call IDs correlate exact issued actions with returned result packets. They are not authentication credentials: the operator declaration does not authenticate an arbitrary API caller or independently prove that a harness executed a read. Observations remain labelled accounts of the image bytes reported by the harness. Duplicate, changed, unregistered or unsupported result structures are explicit errors.

Image token cost remains explicitly unknown when native measurement cannot establish it. No text-density estimate proves visual fit. Protected multipart reads settle only after their final full model request is measured and delivered; a prior image observation gives them no read credit. An unknown fit outcome preserves the received carriers without credit; a measured overflow withholds the encoded transport pages and tells the coder the file size and how to read it in narrower pieces, also without credit.

Chat text SSE remains token-progressive, including when an image tool is offered; the Responses wire is fake-streamed for every request (created first, then one delta per item once the completion exists), with or without images. Image-bearing requests buffer their internal observation/reinspection exchanges before emitting the final completion; the harness receives a complete, valid event stream (Responses: created, in_progress heartbeats, output item/content events, completed; Chat: keepalive comment, role chunk, content chunks, stop, `[DONE]`). Validated against a real vision model (gemma4_12b with its projector) through a scratch cria: Responses and Chat streaming with an image attachment, a text-only stream in the same server, and a real sandboxed Codex 0.159.3 using its native `view_image` tool (schema `{path: string}`, required, no additional properties). A changed file between two reads produced a fresh observation from the new bytes, and only the two observation requests carried pixels.

A Codex deployment must declare image input for the served model in its model catalog (`input_modalities` containing `image`). With a text-only catalog Codex itself refuses to execute `view_image` ("not allowed because you do not support image inputs") and cria passes that refusal text on to the coder as the tool's own result; no observation exists then.

An `http(s)` image URL is a reference, never fetched by cria: it is passed to the vision-capable backend unchanged (the backend, not cria, fetches it), the observation is labelled as made from a remote URL reference with no retained copy, and reinspection asks the backend to view the URL again. Without a declared vision role the request is refused with an explicit `image_unavailable`; the image is never dropped silently.

Completion judges and critics read an observed image packet (including a harness `view_image` result) as its labelled observation, the same text the coder sees, never as pixels or as nothing. A separate limitation remains: the closing file-based confirmation check cannot verify an account of image contents with `list_dir`/`read_file`, so a multi-step turn classified as a task whose only deliverable is a statement about an image can be refused by it until the completion-check bound is reached.

There is no trusted session-close authority wired yet. Retained private resources are not deleted on request end, model completion, cache eviction or idle timeout. Operator call captures and backend caches have separate retention. No automatic cleanup is enabled by these settings. Cleanup is an explicit operator act: `python -m cria.retention list` shows every retained multipart and image entry (size, age by last touch, state, kind) and `python -m cria.retention prune` removes entries only with `--apply` (dry run by default; it needs `--older-than 14d` and/or `--session ID`, optionally `--kind multipart|image`). The operator's invocation is the authority; cria never calls it, and idleness or age is the operator's judgment, not a close signal. Image sessions are removed through the store's own closed-seal path (seal outside the payload, payload, seal last), multipart state through its own lock file (session record first, then call associations); a live cria process holding an image session or the multipart lock is skipped, corrupt entries are only removed when selected by `--session`, symlinks and unrecognized names are never touched, and an interrupted run is retried by running it again. A conversation that continues after its state was pruned fails closed: removed multipart continuations yield the existing unverified/unavailable note and removed image sessions are not restorable, never a fabricated read. These checks catch mistakes, not authentication: any process running as the same user can forge or delete these files.
