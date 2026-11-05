#!/bin/sh
# usage: backup.sh SRC_DIR DEST_DIR
if [ $# -lt 2 ]; then
  echo "usage: backup.sh SRC_DIR DEST_DIR" >&2
  exit 2
fi
src=$1
dest=$2
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
tar -czf "$dest/backup-$stamp.tar.gz" -C "$src" .
echo "wrote $dest/backup-$stamp.tar.gz"
