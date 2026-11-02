"""DEV ONLY (operator rule 2026-11-01: development runs on the GPU; the CPU only for timings). Run cria's real System 1 classifier (cria.system1.System1Runtime, the live bundle) on the RTX 3090.
Same code path and graph as production; only the ONNX execution provider is CUDA instead of CPU.
Use the CPU (the production env) only when you need TIMINGS.

usage: ~/.local/share/cria/envs/system1-dev-gpu/bin/python scripts/system1_gpu_judge.py FAMILY IN.json OUT.json
  IN.json  = list of state dicts for the family, e.g. [{"candidate_briefing": "..."}]  (retrospective)
  OUT.json = list of labels in the same order
One process at a time machine-wide (lock below). Runs from the repo checkout at /home/jesse/src/cria-shepherd."""
import fcntl, json, os, sys
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "GPU-907a7f7a-b541-8208-2bce-e1361e3110d6")
sys.path.insert(0, "/home/jesse/src/cria-shepherd")
lock = open("/var/tmp/system1_gpu_judge.lock", "w"); fcntl.flock(lock, fcntl.LOCK_EX)
import onnxruntime as _ort
_ort.preload_dlls()
from cria import system1

class _Sess(_ort.InferenceSession):
    def __init__(self, path, sess_options=None, providers=None, **kw):
        super().__init__(path, sess_options=sess_options,
                         providers=[("CUDAExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"], **kw)
    def get_providers(self):
        return ["CPUExecutionProvider"]

class _Ort:
    def __getattr__(self, k):
        return _Sess if k == "InferenceSession" else getattr(_ort, k)

_imp = system1._import
system1._import = lambda n: _Ort() if n == "onnxruntime" else _imp(n)
family, inp, out = sys.argv[1:4]
rt = system1.System1Runtime("/home/jesse/.cria/models/system1/expanded-v2-live", 4)
states = json.load(open(inp))
labels = []
for s in states:
    try:
        labels.append(rt.judge(family, s))
    except Exception as e:  # report, never guess
        labels.append(f"ERR {type(e).__name__}: {e}")
json.dump(labels, open(out, "w"))
print(json.dumps({l: labels.count(l) for l in set(labels)}))
