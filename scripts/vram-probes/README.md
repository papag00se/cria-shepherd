# VRAM probes — measure, never trust the readout

Built 2026-08-19 while chasing a hidden CPU offload on the dual-GPU `qwen38` slot.
Full write-up: [`docs/model-settings.md` → VRAM accounting on WSL](../../docs/model-settings.md).

On this box **neither `nvidia-smi` nor `cudaMemGetInfo` tells you what you can allocate.**
CUDA overstates used VRAM by ~1.85 GB the moment a context exists; the NVIDIA driver and the
Windows host both disagree with it and agree with each other. Size configs from `allocmax`.

| File | Answers |
|---|---|
| `ctxprobe.cu` | What does a *bare* CUDA context cost? Prints CUDA's view; sample `nvidia-smi` alongside to see the gap. |
| `allocmax.cu` | What can actually be allocated? Descends 256→0.25 MiB chunks until free hits 0. **This is the real ceiling.** |
| `probe_fit.sh` | Where did llama.cpp actually put the layers? Boots the fleet config once with extra flags, prints the final placement, kills it. |

## Build & run

```bash
export LD_LIBRARY_PATH=/home/jesse/src/cuda-12.8-local/lib64:/usr/lib/wsl/lib
nvcc -O0 -arch=sm_86 -o /tmp/ctxprobe ctxprobe.cu && /tmp/ctxprobe 0
nvcc -O0 -arch=sm_86 -o /tmp/allocmax allocmax.cu && /tmp/allocmax 0 && /tmp/allocmax 1
```

`probe_fit.sh <tag> [extra llama-server args]` expects the 18084 unit **stopped** — it starts its
own instance. Logs go to `$TMPDIR`; set `MODEL=` for a slot other than `qwen38`.

```bash
systemctl stop llama-qwen38
./probe_fit.sh m192 -fitt 192
./probe_fit.sh neg  -fitt -600,-550
```

⚠ A load log contains several *trial* fits. Only the **last** `layer 0 assigned to device` block is
the configuration that actually ran — `probe_fit.sh` already accounts for this.

⚠ It kills the server **by PID**, deliberately. An earlier version used `pkill -f <pattern>`, which
also matched the calling shell whenever that shell's own command line contained the pattern — and
killed it. Do not reintroduce a pattern kill here.
