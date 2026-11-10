# handoff_overflow fixture

`inbound-08730a48-responses.json.gz` is, byte for byte (gzip only; nothing trimmed), the inbound Responses request
`inbound-08730a48-responses.json` captured by cria for Codex session `01a1c367-4972-7d92-a250-58ba33f50864`
(suite row `shipping-rates-rb_phi4_codex_poff_1794279681`, phi4, 16,384-token window, rev e54a2408, 2026-11-10 03:04:53 UTC).
It carries the task and a 225,427-character user-role handoff. cria answered it with the `input-not-delivered`
stop message, which ended the session. `capture_inbound` already redacts cria's credentials.

`inbound-4990c314-responses.json.gz` is, byte for byte (gzip only), the inbound request cria could not prepare on 2026-11-10
04:20:42 UTC (Ruby verify run, session `01a1c3a8-3ace-7660-a25c-9a766aa71e4b`): a 13,475-character handoff whose packet was bounded
(`187 earlier evidence block(s) were omitted`). Preparing the next request deep-copied the omission note and raised
`ValueError: Cannot specify ',' with 's'`.
