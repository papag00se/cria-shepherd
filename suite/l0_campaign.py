#!/usr/bin/env python3
"""Fresh restored eight-model L0 campaign; launch serially and await semantic judgments."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

# Direct script launches put only suite/ on sys.path. Validate against the same
# local runtime config implementation used by module launches and the service.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from .battery_status import TASKS
    from .sampling_adapter import validate_knobs
except ImportError:
    from battery_status import TASKS
    from sampling_adapter import validate_knobs

SUITE = Path(__file__).resolve().parent
ROOT = Path.home()/'.cria/suite/_campaigns'
FLEET = Path.home()/'.local/share/cria/fleet'
CONFIG = Path.home()/'.config/llama-fleet/models.toml'
ROLES = CONFIG.with_name('roles.json')
LAUNCHER = Path.home()/'.local/bin/llama-fleet'
READINESS = FLEET/'restoration-state.json'
MODELS = ('gemma4_12b','ornith1.5_9b','bonsai2','nemotron-elastic','ling3.0_tiny',
          'phi4','k2_horizon_7b','qwen3.8_9b_distill')
GPU = 'GPU-393d4998-707c-0ef0-a514-761015477256'
RESULTS = SUITE/'results/results.jsonl'
POLICY = 'inferred-progress-15m-protected-30m-v1'


def campaign_dir(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',name):
        raise ValueError('campaign id must be a safe single directory name')
    return ROOT/name


def validate_revision(revision):
    def git(*args):
        return subprocess.run(['git',*args],cwd=SUITE.parent,capture_output=True,text=True,
                              check=True).stdout.rstrip("\n")
    if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-f]{40}',revision):
        raise ValueError('campaign revision must be the full immutable git revision')
    if git('rev-parse','HEAD') != revision:
        raise ValueError('campaign revision differs from HEAD')
    dirty = git('status','--porcelain','--untracked-files=all').splitlines()
    forbidden = [line[3:] for line in dirty if not line[3:].startswith(
        ('docs/','tests/','suite/results/')) and line[3:] != 'suite/README.md']
    if forbidden:
        raise ValueError('uncommitted runtime inputs: '+', '.join(forbidden))
    return revision


def validate_readiness(receipt):
    if (receipt.get('state') != 'completed_operational_restoration'
        or receipt.get('readiness_verified') is not True
        or receipt.get('logical_model_count') != 8
        or receipt.get('true_restoration_blockers') != []
        or set(receipt.get('models',{})) != set(MODELS)):
        raise ValueError('completed restored readiness receipt required')
    for model, entry in receipt['models'].items():
        if entry.get('state') != 'completed_operational_restoration' or entry.get('readiness_verified') is not True:
            raise ValueError('incomplete restored readiness: '+model)
    limits = receipt['models']['phi4'].get('known_limits')
    if not isinstance(limits,list) or not limits:
        raise ValueError('Phi Unicode limitation must remain explicit in readiness scope')


def fingerprint(path, *, large=False):
    path = Path(path)
    if not path.is_file(): raise ValueError('missing required asset: '+str(path))
    stat = path.stat()
    out={'path':str(path.resolve()),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,
         'inode':stat.st_ino,'device':stat.st_dev}
    if not large: out['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def fleet_snapshot():
    """Read-only validation. No switch, restart, model inference or implicit acquisition."""
    receipt=json.loads(READINESS.read_text())
    validate_readiness(receipt)
    completion=Path(receipt['completion_receipt'])
    final=json.loads(completion.read_text())
    validate_readiness(final)
    if final['models'] != receipt['models']:
        raise ValueError('readiness/completion artifact bindings differ')
    config=tomllib.loads(CONFIG.read_text())
    roles=json.loads(ROLES.read_text())
    recipes=json.loads((FLEET/'profiles/model-recipes.json').read_text())
    if config.get('operational_fleet_schema') != 1 or set(config['models']) != set(MODELS) or set(roles) != set(MODELS) or set(recipes) != set(MODELS):
        raise ValueError('canonical fleet must contain exactly eight logical identities')
    assets={}
    def add(path,large=False):
        path=Path(path)
        if any(part in ('Work','Recover','backup','backups') for part in path.resolve().parts):
            raise ValueError('obsolete/nonoperational asset path: '+str(path))
        assets[str(path)]=fingerprint(path,large=large)
    for p in (CONFIG,ROLES,READINESS,completion,LAUNCHER,FLEET/'profiles/model-recipes.json'):
        add(p)
    if not os.access(LAUNCHER,os.X_OK): raise ValueError('launcher not executable')
    for p in (FLEET/'tools').glob('*.py'): add(p)
    add(Path.home()/'.local/share/mise/installs/codex/0.159.3/bin/codex')
    add(Path.home()/'.cria/codex-home/config.toml')
    add(Path.home()/'.cria/suite-codex-policy.toml')
    live_config=validate_live(Path.home()/'.cria/cria.toml')
    effective_units={}
    for model in MODELS:
        cfg={**config.get('defaults',{}),**config['models'][model]}
        entry=receipt['models'][model]; binding=entry['assets']; recipe=recipes[model]
        if (cfg.get('alias') != model or cfg.get('cuda_device') != GPU or cfg.get('host') != '127.0.0.1'
            or cfg.get('port') != 18084 or cfg.get('device') != 'CUDA0' or cfg.get('main_gpu') != 0
            or cfg.get('split_mode') != 'none' or cfg.get('parallel') != 1):
            raise ValueError('unsafe fleet runtime config: '+model)
        for key,asset in (('model_path','weight'),('binary','runtime'),('lib_dir','library_dirs')):
            if cfg[key] != binding[asset]: raise ValueError('stale asset binding: '+model+' '+key)
        if cfg.get('template') != binding.get('template') or cfg['ctx'] != entry['model_context']:
            raise ValueError('template/context binding differs: '+model)
        if set(roles[model]) != {'coder','reasoner','classifier','compactor'} or roles[model] != recipe['roles']:
            raise ValueError('canonical four-role sampling differs: '+model)
        for knobs in roles[model].values(): validate_knobs(knobs)
        weight=Path(cfg['model_path']); add(weight,True)
        if weight.stat().st_size != binding['bytes'] or binding['bytes'] != recipe['expected_weight_bytes']:
            raise ValueError('restored weight size differs: '+model)
        add(cfg['binary'])
        if not os.access(cfg['binary'],os.X_OK): raise ValueError('runtime not executable')
        if cfg.get('template'): add(cfg['template'])
        for directory in cfg['lib_dir'].split(':'):
            lib=Path(directory)
            if not lib.resolve().is_relative_to(FLEET.resolve()) or not lib.is_dir():
                raise ValueError('missing/unsafe runtime library directory')
            libraries=list(lib.glob('*.so*'))
            if not libraries: raise ValueError('missing runtime libraries')
            for p in libraries: add(p)
        unit=binding['unit']
        if unit != recipe['unit'] or not re.fullmatch(r'llama-[A-Za-z0-9_.-]+\.service',unit):
            raise ValueError('unsafe unit binding')
        effective=subprocess.run(['systemctl','show',unit,
            '--property=ExecStart,User,WorkingDirectory,Environment,DropInPaths,Restart,KillMode'],
            capture_output=True,text=True,check=True).stdout
        values=dict(line.split('=',1) for line in effective.splitlines() if '=' in line)
        start=values.get('ExecStart','')
        expected=f'argv[]={LAUNCHER} serve {model} ;'
        if (expected not in start or start.count('argv[]=') != 1 or
            f'path={LAUNCHER} ;' not in start or values.get('User') != Path.home().name
            or values.get('WorkingDirectory') != str(FLEET) or values.get('Restart') != 'no'
            or values.get('KillMode') != 'control-group'
            or values.get('Environment') != f'HOME={Path.home()} PATH=/usr/bin:/bin HF_HUB_OFFLINE=1 LLAMA_ARG_OFFLINE=1'):
            raise ValueError('unsafe effective unit: '+unit)
        values["ExecStart"] = f"{LAUNCHER} serve {model}"
        effective_units[unit]=values
        for dropin in values.get('DropInPaths','').split(): add(dropin)
        proof=Path(entry['switch_receipt']); add(proof)
        switch=json.loads(proof.read_text()); sync=switch['sync']
        if (switch.get('model') != model or switch.get('unit') != unit or
            sync.get('GPU') != GPU or sync.get('actual_context') != cfg['ctx'] or
            sync.get('model_context_sync_verified') is not True):
            raise ValueError('invalid managed switch proof: '+model)
        for p in [entry['native_checks'],*entry.get('supplement_checks',[])]: add(p)
    return {'assets':assets,'effective_units':effective_units,'roles':roles,'live_config':live_config,
            'config':config,'known_limits':receipt.get('known_limits'),
            'phi4_known_limits':receipt['models']['phi4']['known_limits']}


def validate_live(config_path):
    from cria.config import _engagement_level
    cfg=tomllib.loads(Path(config_path).read_text())
    if (_engagement_level(cfg.get('engagement',{})) != 0 or
        cfg.get('planner',{}).get('enabled',False) is not False or
        cfg.get('logging',{}).get('capture_calls') is not True):
        raise ValueError('restored L0 requires live L0, planner off, capture_calls=true')
    service=subprocess.run(['systemctl','show','cria.service',
        '--property=MainPID,ExecMainStartTimestampMonotonic'],capture_output=True,text=True,check=True).stdout
    state=dict(line.split('=',1) for line in service.splitlines() if '=' in line)
    pid=int(state.get('MainPID',0)); started=int(state.get('ExecMainStartTimestampMonotonic',0))/1_000_000
    if not pid or not started: raise ValueError('live cria service is not running')
    command=[v.decode() for v in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0') if v]
    if '--config' in command:
        selected = Path(command[command.index('--config')+1])
        if not selected.is_absolute(): selected=(Path('/proc')/str(pid)/'cwd').resolve()/selected
        if selected.resolve() != Path(config_path).resolve():
            raise ValueError('live cria process uses a different config')
    else:
        # Config.load's documented default merges HOME_CONFIG with CWD_CONFIG. Refuse any
        # additional workspace override rather than treating a matching home file as live proof.
        from cria.config import HOME_CONFIG, CWD_CONFIG
        override=(Path('/proc')/str(pid)/'cwd').resolve()/CWD_CONFIG
        if Path(HOME_CONFIG).expanduser().resolve() != Path(config_path).resolve() or override.exists():
            raise ValueError('live default configuration has a workspace override')
    if Path(config_path).stat().st_mtime > time.time()-time.monotonic()+started+1:
        raise ValueError('live config changed after service startup; restart must precede campaign')
    return fingerprint(config_path)


def actual_sampling(snapshot, model, knobs):
    actual=[]
    for entry in snapshot.get('entries',[]):
        body=json.loads(Path(entry['request']).read_text())['body']
        fields={k:body[k] for k in validate_knobs(knobs) if k in body}
        if fields != knobs or body.get('model') != model:
            raise ValueError('actual upstream sampling/model differs from source coder request')
        actual.append({'request':entry['request'],'fields':fields})
    if not actual: raise ValueError('no upstream sampling capture')
    return actual


def read_rows():
    if not RESULTS.exists(): return []
    return [json.loads(line) for line in RESULTS.read_text().splitlines() if line.strip()]


def valid_row(row, manifest):
    try:
        from .fresh_l5_campaign import _valid_capture_evidence
    except ImportError:
        from fresh_l5_campaign import _valid_capture_evidence
    preserved = manifest.get('preserved_runs', {}).get(row.get('run_id'))
    if preserved and (preserved['model'], preserved['task']) != (row.get('model'), row.get('task')):
        return False
    revision = preserved['revision'] if preserved else manifest['revision']
    snapshot = preserved['fleet_snapshot'] if preserved else manifest['fleet_snapshot']
    if (row.get('campaign_id') != manifest['campaign_id'] or row.get('revision') != revision
        or row.get('code_revision') != revision or row.get('model') not in MODELS
        or row.get('task') not in TASKS or row.get('restored_fleet') is not True
        or row.get('level') != 0 or row.get('live_engagement_level') != 0
        or row.get('planner') != 'off' or row.get('planner_enabled') is not False
        or row.get('planner_phase_count') != 0 or row.get('aborted') or row.get('workspace_lost')
        or row.get('terminal') == 'harness-error' or row.get('pacing_policy') != POLICY
        or row.get('fleet_snapshot') != snapshot
        or not isinstance(row.get('capture_snapshot'),dict)):
        return False
    archive=Path(row.get('archive') or '')/'workspace'
    log=Path(row.get('harness_log') or '')
    if not archive.is_dir() or not log.is_file() or not _valid_capture_evidence(row): return False
    try:
        source=snapshot['roles'][row['model']]['coder']
        return (row.get('source_coder_sampling') == source and
                row.get('actual_sent_sampling') == actual_sampling(row['capture_snapshot'],row['model'],source)
                and bool(row.get('injected_sampling'))
                and all(item.get('fields') == source for item in row['injected_sampling']))
    except (OSError,ValueError,KeyError,TypeError): return False


def judgment(row):
    try:
        from . import usefulness
    except ImportError:
        import usefulness
    p=usefulness.verdict_path(row['run_id'])
    if not p.is_file() or usefulness._needs_judging(row): return None
    value=json.loads(p.read_text())
    return usefulness.parse(json.dumps(value))


def save(path, value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n'); temp.replace(path)


def create_manifest(campaign_id, revision, snapshot):
    return {'schema':1,'campaign_id':campaign_id,'revision':revision,'created':time.time(),
            'models':list(MODELS),'tasks':list(TASKS),'level':0,'planner':'off','pacing_policy':POLICY,
            'fleet_snapshot':snapshot,'cells':[{'model':m,'task':t,'state':'pending'} for m in MODELS for t in TASKS]}


def row_digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def valid_failed_row(row, manifest):
    # Evidence validation only: this never makes the original failed row scoreable.
    return (row.get('terminal') == 'harness-error'
            and row.get('started', 0) >= manifest['created']
            and valid_row({**row, 'terminal': 'infrastructure-evidence'}, manifest))


def preserved_failed_row(cell, rows, manifest):
    """Return the unchanged failure's authoritative row, never a completion judgment."""
    found = [r for r in rows if r.get('campaign_id') == manifest['campaign_id']
             and (r.get('model'), r.get('task')) == (cell['model'], cell['task'])]
    saved = manifest.get('preserved_runs', {}).get(cell.get('run_id'), {})
    if (len(found) == 1 and found[0].get('run_id') == cell.get('run_id')
            and row_digest(found[0]) == saved.get('unscored_failure_sha256')
            and valid_failed_row(found[0], manifest) and 'judgment' not in cell):
        return found[0]
    return None


def reconcile(manifest, rows):
    cohort=[r for r in rows if r.get('campaign_id') == manifest['campaign_id']]
    for cell in manifest['cells']:
        if cell['state'] == 'infrastructure-failed':
            if preserved_failed_row(cell, cohort, manifest) is None:
                cell.update(state='blocked', reason='preserved infrastructure failure changed; no automatic retry')
            continue
        if cell['state'] == 'blocked': continue
        found=[r for r in cohort if r.get('model') == cell['model'] and r.get('task') == cell['task']]
        if not found:
            if cell['state'] != 'pending': cell['state']='blocked'; cell['reason']='attempt has no result; no automatic retry'
            continue
        if (len(found) != 1 or found[0].get('started',0) < manifest['created']
            or not valid_row(found[0],manifest) or (cell.get('run_id') and cell['run_id'] != found[0]['run_id'])):
            cell.update(state='blocked',reason='invalid or duplicate fresh evidence; no automatic retry'); continue
        row=found[0]; verdict=judgment(row)
        cell.update(run_id=row['run_id'],state='done' if verdict else 'awaiting-usefulness')
        if verdict: cell['judgment']=verdict
    return manifest


def cell_command(manifest, cell):
    return [sys.executable,str(SUITE/'battery_run.py'),'--level','0','--model',cell['model'],
            '--task',cell['task'],'--restored-fleet','--campaign-id',manifest['campaign_id'],
            '--campaign-revision',manifest['revision']]


def resume_after_repair(manifest, previous_revision, revision, snapshot, rows, *, failed_run_id=None):
    """Explicit provenance transition; never retry an attempted cell or rewrite a result."""
    if manifest['revision'] != previous_revision or revision == previous_revision:
        raise ValueError('repair must name the previous and a new revision')
    previous_snapshot = manifest['fleet_snapshot']
    if previous_snapshot != snapshot:
        # Codex atomically rewrote ONLY its trust metadata. Restoring byte-identical
        # configuration cannot restore a deleted inode; all other assets stay exact.
        config = str(Path.home() / '.cria/codex-home/config.toml')
        old = previous_snapshot.get('assets', {}).get(config, {})
        new = snapshot.get('assets', {}).get(config, {})
        normalized = {**snapshot, 'assets': {**snapshot.get('assets', {}), config: old}}
        if (not old.get('sha256') or old['sha256'] != new.get('sha256')
                or old.get('size') != new.get('size') or normalized != previous_snapshot):
            raise ValueError('repair cannot adopt changed fleet assets')
    failure_cell = failure_row = None
    if failed_run_id is not None:
        found = [r for r in rows if r.get('campaign_id') == manifest['campaign_id']
                 and r.get('run_id') == failed_run_id]
        if len(found) != 1 or not valid_failed_row(found[0], manifest):
            raise ValueError('repair requires exact fresh infrastructure failure evidence')
        failure_row = found[0]
        matches = [c for c in manifest['cells'] if (c['model'], c['task']) ==
                   (failure_row['model'], failure_row['task'])]
        if (len(matches) != 1 or matches[0]['state'] != 'blocked'
                or 'attempted_at' not in matches[0] or 'judgment' in matches[0]
                or matches[0].get('run_id', failed_run_id) != failed_run_id
                or sum(r.get('campaign_id') == manifest['campaign_id']
                       and (r.get('model'), r.get('task')) == (failure_row['model'], failure_row['task'])
                       for r in rows) != 1):
            raise ValueError('repair can preserve only one blocked, unscored exact attempt')
        failure_cell = matches[0]
    if any(c['state'] not in ('done', 'pending', 'infrastructure-failed')
           and c is not failure_cell for c in manifest['cells']):
        raise ValueError('repair requires completed judgments and untouched pending cells')
    preserved = dict(manifest.get('preserved_runs', {}))
    for cell in manifest['cells']:
        if cell['state'] == 'infrastructure-failed':
            if preserved_failed_row(cell, rows, manifest) is None:
                raise ValueError('preserved infrastructure failure changed')
            continue
        if cell['state'] == 'pending':
            if 'attempted_at' in cell or 'run_id' in cell:
                raise ValueError('pending cell has an attempt; no automatic retry')
            continue
        if cell is failure_cell:
            row = failure_row
        else:
            found = [r for r in rows if r.get('campaign_id') == manifest['campaign_id']
                     and r.get('run_id') == cell['run_id']]
            if (len(found) != 1 or found[0].get('started', 0) < manifest['created']
                    or not valid_row(found[0], manifest) or not judgment(found[0])):
                raise ValueError('repair requires valid completed fresh evidence')
            row = found[0]
        preserved[row['run_id']] = {**{k: row[k] for k in ('revision', 'model', 'task')},
                                   'fleet_snapshot': row['fleet_snapshot']}
        if cell is failure_cell:
            preserved[row['run_id']]['unscored_failure_sha256'] = row_digest(row)
    if failure_cell is not None:
        failure_cell.update(state='infrastructure-failed', run_id=failed_run_id,
                            reason='explicitly preserved infrastructure failure; unscored, never retried')
    manifest.setdefault('repair_history', []).append({
        'at': time.time(), 'from_revision': previous_revision, 'to_revision': revision,
        'preserved_run_ids': sorted(preserved),
        **({'unscored_failed_run_id': failed_run_id} if failed_run_id is not None else {})})
    manifest.update(revision=revision, preserved_runs=preserved, fleet_snapshot=snapshot)
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--campaign-id',required=True)
    ap.add_argument('--campaign-revision',required=True)
    ap.add_argument('--resume-after-launcher-repair', '--resume-after-infrastructure-repair',
                    dest='resume_after_launcher_repair', metavar='PREVIOUS_REVISION',
                    help='explicitly preserve completed current cells under their original revision')
    ap.add_argument('--preserve-infrastructure-failure', metavar='RUN_ID',
                    help='with explicit repair resume, consume this exact failed slot without score or retry')
    ap.add_argument('--drive',action='store_true',help='drive serial cells, waiting for independent final judgments')
    args=ap.parse_args()
    if args.preserve_infrastructure_failure and not args.resume_after_launcher_repair:
        ap.error('--preserve-infrastructure-failure requires an explicit repair resume')
    directory=campaign_dir(args.campaign_id)
    validate_revision(args.campaign_revision)
    snapshot=fleet_snapshot()
    # Validate only this cohort's task runners, with no installs or inference.
    import shutil
    for exe in ('ruby','go','python','mvn','node','cargo'):
        if not shutil.which(exe): raise ValueError('missing task runner: '+exe)
    for task in TASKS:
        if not (SUITE/'tasks'/task/'prompt.txt').is_file(): raise ValueError('missing task prompt: '+task)
    directory.mkdir(parents=True,exist_ok=True)
    with (ROOT/'driver.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=directory/'manifest.json'
        manifest=json.loads(path.read_text()) if path.exists() else create_manifest(args.campaign_id,args.campaign_revision,snapshot)
        if args.resume_after_launcher_repair:
            # Exclusive driver lock is held. The original manifest remains immutable evidence.
            before = directory / ('manifest-before-repair-' + manifest['revision'] + '.json')
            original_text = json.dumps(manifest, indent=2) + '\n'
            resume_after_repair(manifest, args.resume_after_launcher_repair,
                                args.campaign_revision, snapshot, read_rows(),
                                failed_run_id=args.preserve_infrastructure_failure)
            with before.open('x') as original:
                original.write(original_text)
            save(path, manifest)
        if (manifest['revision'] != args.campaign_revision or manifest['fleet_snapshot'] != snapshot
            or manifest['models'] != list(MODELS) or manifest['tasks'] != list(TASKS)
            or manifest['campaign_id'] != args.campaign_id):
            raise ValueError('stale campaign manifest inputs; never credit changed assets/revision')
        while True:
            reconcile(manifest,read_rows()); save(path,manifest)
            blocked=[c for c in manifest['cells'] if c['state'] == 'blocked']
            if blocked:
                print(json.dumps(blocked,indent=2)); return 2
            waiting=[c for c in manifest['cells'] if c['state'] == 'awaiting-usefulness']
            pending=[c for c in manifest['cells'] if c['state'] == 'pending']
            print(json.dumps({'manifest':str(path),'done':sum(c['state']=='done' for c in manifest['cells']),
                              'infrastructure_failed': [c for c in manifest['cells'] if c['state'] == 'infrastructure-failed'],
                              'waiting':waiting,'next':pending[:1]}),flush=True)
            if not args.drive or not pending and not waiting: return 0
            if waiting:
                time.sleep(2); continue
            validate_revision(args.campaign_revision)
            if fleet_snapshot() != snapshot: raise ValueError('fleet changed before next cell')
            cell=pending[0]; cell.update(state='running',attempted_at=time.time()); save(path,manifest)
            with (directory/'driver.jsonl').open('a') as events:
                events.write(json.dumps({'event':'launch','at':time.time(),'cell':cell})+'\n')
            with (directory/f"{cell['model']}--{cell['task']}.log").open('x') as log:
                rc=subprocess.run(cell_command(manifest,cell),stdout=log,stderr=subprocess.STDOUT).returncode
            if rc:
                cell.update(state='blocked',reason=f'runner exit {rc}; no automatic retry'); save(path,manifest); return 2


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr); raise SystemExit(2)
