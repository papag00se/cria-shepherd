# mini_md

A very small markdown renderer.

## Security

`<`, `>` and `&` in the input are HTML-escaped before tags are added, so rendered output cannot contain injected markup.
