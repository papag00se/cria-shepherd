# VRAM probes — measure, never trust the readout

## Dory three-loop RTX3090 tuning (native Linux, 2026-10-20)

`tune_dory.py` is an explicitly authorized, machine-local experiment, not part of cria's runtime or the battery. It borrows the exact existing RTX3090 Docker container, refuses to stop it if its metrics report active/queued requests, launches Dory only on the RTX3090 UUID and private port 18486, and restores the original container in `finally`. The RTX3080 fleet configuration/service and cria are untouched. Do not run it without permission to interrupt the RTX3090 server. Container ID and GPU UUIDs are named machine constants; inspect them before reusing the script after a container replacement.

Run detached with an independent systemd restoration hook, so stopping or losing the Python driver still starts the original container:

```bash
systemd-run --user --unit=dory-tune-3090 --collect \
  --property=WorkingDirectory=/home/jesse/src/cria-shepherd \
  --property='ExecStopPost=/usr/bin/docker start 37d22bcfd043cb7c9498e3dfe14b4e6ff66e07509d6e8375f1b031b1d9105b24' \
  /usr/bin/python3 /home/jesse/src/cria-shepherd/scripts/vram-probes/tune_dory.py \
  --output /home/jesse/.cria/calls/dory-tuning-3090-NEW-RUN --repeats 3
```

The sweep compares Flash Attention, F16/Q8/Q4 cache combinations, prompt batch sizes, last-loop cache sharing, two n-gram drafters and CUDA graph optimization. All arms retain three loops and a 49,152-token allocated context. It records complete streaming requests/replies and native timing/draft counters, one excluded warmup plus measured cold/reused pairs for each workload, GPU process snapshots, and narrow arithmetic/tool/continuation/retrieval/Python-structure checks. The finite 192-token, ignore-EOS generation probes measure speed, **not task completion or code usefulness**. Generated code is parsed but never executed. Benchmark prompts live in `cria/prompts/dory_tune_cases.txt`.

`--arms NAME ...` selects existing arms for a follow-up comparison. `--novel-check` adds three distinct first-seen coding prompts; `--long-check` adds the large-context retrieval smoke. `--bench-temp 1` repeats throughput measurements at publisher-recommended sampling instead of the default greedy zero; narrow quality smokes remain deterministic. Output directories must be new; prior failures and measurements are not overwritten. The original vLLM's empty HTTP-200 health response is accepted; its model identity is checked with the container's existing API key without saving the key. Rate-limit signals abort this finite experiment with the server's delay preserved, rather than retrying that origin or contaminating timing results. Results and limits belong in [the Dory runtime guide](../../docs/dory-runtime.md). The older probes/accounting notes below describe the historical WSL setup, not a new allocation measurement on native Linux.

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
