from suite.progress_fresh.dsl import ed

SEED = {
"backup.sh": '''#!/bin/sh
# usage: backup.sh SRC_DIR DEST_DIR
src=$1
dest=$2
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .
echo "wrote $dest/backup-$stamp.tar.gz"
''',
"test.sh": '''#!/bin/sh
set -e
work=$(mktemp -d)
mkdir "$work/src"
echo hi > "$work/src/a.txt"
sh ./backup.sh "$work/src" "$work/out"
ls "$work/out" | grep -q '^backup-'
echo PASS
''',
"README.md": "# backup\n\nTar-gzips a directory into a timestamped archive.\n",
}
B = SEED["backup.sh"]
T = SEED["test.sh"]
R = SEED["README.md"]
TASK = dict(extension=True, name="backup-sh", language="Bash", seed=SEED,
unrelated={"README.md": R + "\nRequires `tar` and `date`.\n"},
reqs=[
dict(id="arg-check", text="Fail with a usage message on stderr and exit status 2 when fewer than two arguments are given or SRC_DIR is not a directory; the script must not create DEST_DIR in that case. Add a test for the missing-argument case.",
 partial={"backup.sh": ed(B, ("src=$1\n", 'if [ $# -lt 2 ]; then\n  echo "usage: backup.sh SRC_DIR DEST_DIR" >&2\n  exit 2\nfi\nsrc=$1\n'))},
 done={"backup.sh": ed(B, ("src=$1\ndest=$2\n", 'if [ $# -ne 2 ] || [ ! -d "$1" ]; then\n  echo "usage: backup.sh SRC_DIR DEST_DIR" >&2\n  exit 2\nfi\nsrc=$1\ndest=$2\n')),
       "test.sh": ed(T, ("echo PASS", 'if sh ./backup.sh 2>/dev/null; then\n  echo "expected failure without args"; exit 1\nfi\nsh ./backup.sh 2>/dev/null || [ $? -eq 2 ]\necho PASS'))}),
dict(id="keep-n", text="Add an optional third argument KEEP: after writing the new archive, delete the oldest backup-*.tar.gz files in DEST_DIR so only the newest KEEP remain; add a test that creates several archives and checks the count.", ns=True,
 partial={"backup.sh": B + '\nkeep=${3:-0}\nif [ "$keep" -gt 0 ]; then\n  ls -1 "$dest"/backup-*.tar.gz | sort | tail -n +"$((keep + 1))" | xargs -r rm\nfi\n'},
 done={"backup.sh": B + '\nkeep=${3:-0}\nif [ "$keep" -gt 0 ]; then\n  ls -1 "$dest"/backup-*.tar.gz | sort | head -n -"$keep" | xargs -r rm --\nfi\n',
       "test.sh": ed(T, ("echo PASS", 'for i in 1 2 3; do touch "$work/out/backup-2000010$i-000000.tar.gz"; done\nsh ./backup.sh "$work/src" "$work/out" 2 >/dev/null\n[ "$(ls "$work/out" | wc -l)" -eq 2 ]\nls "$work/out" | grep -vq 20000101\necho PASS'))}),
dict(id="exclude-docs", text="Support an --exclude PATTERN option (passed to tar) placed before the directories, and document it in the README with an example.",
 partial={"backup.sh": ed(B, ("src=$1\ndest=$2\n", 'exclude=""\nif [ "$1" = "--exclude" ]; then\n  exclude="--exclude=$2"\n  shift 2\nfi\nsrc=$1\ndest=$2\n'), ('tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .', 'tar -czf "$dest/backup-$stamp.tar.gz" $exclude -C "$src" .'))},
 done={"backup.sh": ed(B, ("src=$1\ndest=$2\n", 'exclude=""\nif [ "$1" = "--exclude" ]; then\n  exclude="--exclude=$2"\n  shift 2\nfi\nsrc=$1\ndest=$2\n'), ('tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .', 'tar -czf "$dest/backup-$stamp.tar.gz" $exclude -C "$src" .')),
       "README.md": R + "\n## Options\n\n`--exclude PATTERN` skips matching files (tar `--exclude` syntax); it must come first:\n\n    sh backup.sh --exclude '*.log' ./site /var/backups\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["arg-check"]["test.sh"] = ed(T, ("echo PASS", 'if sh ./backup.sh 2>/dev/null; then\n  echo "expected failure without args"; exit 1\nfi\necho PASS'))
_P["keep-n"]["test.sh"] = ed(T, ("echo PASS", 'for i in 1 2 3; do touch "$work/out/backup-2000010$i-000000.tar.gz"; done\nsh ./backup.sh "$work/src" "$work/out" 2 >/dev/null\n[ "$(ls "$work/out" | wc -l)" -eq 2 ]\necho PASS'))
