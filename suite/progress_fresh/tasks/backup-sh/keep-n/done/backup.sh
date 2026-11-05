#!/bin/sh
# usage: backup.sh SRC_DIR DEST_DIR
src=$1
dest=$2
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .
echo "wrote $dest/backup-$stamp.tar.gz"

keep=${3:-0}
if [ "$keep" -gt 0 ]; then
  ls -1 "$dest"/backup-*.tar.gz | sort | head -n -"$keep" | xargs -r rm --
fi
