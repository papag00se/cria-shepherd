# Vendored .gitignore templates

Verbatim copies of the canonical per-language templates from https://github.com/github/gitignore (CC0-1.0 / public domain). cria uses them as language-agnostic GUIDANCE for which directories are vendored/build/cache output and should NOT be walked into when collecting a language's source files for the lint floor (see cria/ignore.py). Each language's template is applied ONLY to that language's files, so e.g. Python's `lib/` rule never wrongly prunes Ruby source (whose `lib/` is real source).

Refresh: re-download from the upstream repo's main branch.
