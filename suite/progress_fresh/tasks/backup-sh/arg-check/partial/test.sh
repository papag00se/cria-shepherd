#!/bin/sh
set -e
work=$(mktemp -d)
mkdir "$work/src"
echo hi > "$work/src/a.txt"
sh ./backup.sh "$work/src" "$work/out"
ls "$work/out" | grep -q '^backup-'
if sh ./backup.sh 2>/dev/null; then
  echo "expected failure without args"; exit 1
fi
echo PASS
