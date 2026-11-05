"""Install the standard System 1 bundle on first use, outside the workspace."""
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import Request

from . import ratelimit

# The release asset is not published until the operator approves distribution.
BUNDLE_URL = "https://github.com/papag00se/cria-shepherd/releases/download/system1-v2/system1-v2.tar.gz"
FILES = frozenset({"config.json", "model.onnx", "model.onnx.data", "tokenizer.json",
                   "tokenizer_config.json", "selftest.json", "policy/dictation.txt",
                   "policy/retrospective.txt"})


def install(destination: Path, validate) -> None:
    """Download and validate in private staging; never replace an existing installation."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".system1-", dir=destination.parent) as tmp:
        root = Path(tmp)
        archive = root / "bundle.tar.gz"
        request = Request(BUNDLE_URL, headers={"User-Agent": "cria-shepherd"})
        with ratelimit.open_response(request, timeout=120) as response:
            if response.status != 200:
                raise OSError(f"System 1 download returned HTTP {response.status}")
            with archive.open("wb") as out:
                shutil.copyfileobj(response, out)
        stage = root / "bundle"
        stage.mkdir()
        with tarfile.open(archive, "r:gz") as tf:
            members = tf.getmembers()
            if {m.name for m in members} != FILES or any(not m.isfile() for m in members) or len(members) != len(FILES):
                raise ValueError("System 1 archive has unexpected members")
            for member in members:
                path = stage / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as source, path.open("wb") as out:
                    shutil.copyfileobj(source, out)
        validate(stage)
        try:
            os.rename(stage, destination)
        except OSError:
            if not destination.is_dir():
                raise
