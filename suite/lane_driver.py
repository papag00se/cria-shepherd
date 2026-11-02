#!/usr/bin/env python3
"""Run restored-fleet battery cells in parallel on the lanes (suite/lanes.py): one cell per slot.

One model is served at a time (the RTX3090 lease names one model): its lanes run its pending cells across all
free slots, one cria instance per active row (lane x model x level), and the lanes switch to the next model only
when every slot has drained. A finished cell awaiting its usefulness judgment does not hold a slot or the
campaign; an invalid/failed cell blocks new launches, lets running cells finish and ends the run with no retry.

    python suite/lane_driver.py --campaign l5-20261102:5 [--campaign l0-20261102:0] \
        --campaign-revision "$(git rev-parse HEAD)" [--lanes 3090x4,3080x2] [--models M,..] [--tasks T,..]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
try:
    from . import l0_campaign, lanes
except ImportError:
    import l0_campaign
    import lanes


class Campaign:
    def __init__(self, campaign_id, level, revision, snapshot):
        self.id, self.level = campaign_id, level
        self.dir = l0_campaign.campaign_dir(campaign_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / 'manifest.json'
        self.manifest = (json.loads(self.path.read_text()) if self.path.exists()
                         else l0_campaign.create_manifest(campaign_id, revision, snapshot, level=level))
        if (self.manifest['revision'] != revision or self.manifest['fleet_snapshot'] != snapshot
                or self.manifest['level'] != level or self.manifest['planner'] != 'off'
                or self.manifest['models'] != list(l0_campaign.MODELS) or self.manifest['tasks'] != list(l0_campaign.TASKS)):
            raise ValueError('stale campaign manifest inputs; never credit changed assets/revision')

    def save(self):
        l0_campaign.save(self.path, self.manifest)

    def event(self, **fields):
        with (self.dir / 'driver.jsonl').open('a') as events:
            events.write(json.dumps({'at': time.time(), **fields}) + '\n')


class Driver:
    def __init__(self, campaigns, lane_names, models, tasks, max_cells):
        self.campaigns, self.lane_names = campaigns, lane_names
        self.models, self.tasks, self.max_cells = models, tasks, max_cells
        self.running = {}          # (campaign id, model, task) -> dict(proc, lane, row, cell, campaign)
        self.servers = {}          # lane -> server state
        self.rows = {}             # (lane, model, level) -> row dict
        self.model = None
        self.launched = 0
        self.blocked = False
        self.next_port = lanes.ROW_PORT_BASE

    # ------------------------------------------------------------------ planning
    def pending(self, model=None):
        out = []
        for campaign in self.campaigns:
            for cell in campaign.manifest['cells']:
                if (cell['state'] == 'pending' and cell['model'] in self.models and cell['task'] in self.tasks
                        and (model is None or cell['model'] == model)):
                    out.append((campaign, cell))
        return out

    def lanes_for(self, model):
        found = {}
        for name in self.lane_names:
            window = lanes.lane_window(model, name)
            if window is not None:
                found[name] = window
        if not found:
            raise ValueError(f'{model} fits none of the enabled lanes')
        return found

    def used(self, lane):
        return sum(1 for run in self.running.values() if run['lane'] == lane)

    # ------------------------------------------------------------------ lifecycle
    def stop_rows(self, keep=lambda key: False):
        for key, row in list(self.rows.items()):
            if not keep(key) and not any(r['row'] is row for r in self.running.values()):
                lanes.stop_row(row)
                del self.rows[key]

    def switch_model(self, model):
        self.stop_rows()
        for lane in list(self.servers):
            lanes.stop_server(lane)
            del self.servers[lane]
        for lane, window in self.lanes_for(model).items():
            self.servers[lane] = lanes.start_server(model, lane, window)
        self.model = model
        print(json.dumps({'event': 'lanes-up', 'model': model,
                          'lanes': {k: v['served'] for k, v in self.servers.items()}}), flush=True)

    def row_for(self, lane, model, level):
        key = (lane, model, level)
        if key not in self.rows:
            roles = self.campaigns[0].manifest['fleet_snapshot']['roles'][model]
            self.rows[key] = lanes.start_row(lane, model, level, roles, self.servers[lane]['window'], port=self.next_port)
            self.next_port += 1
        return self.rows[key]

    def launch(self, lane, campaign, cell):
        row = self.row_for(lane, cell['model'], campaign.level)
        command = l0_campaign.cell_command(campaign.manifest, cell, Path(row['dir']) / 'row.json')
        cell.update(state='running', attempted_at=time.time(), lane=lane)
        campaign.save()
        campaign.event(event='launch', cell=cell, row=row['dir'])
        log = (campaign.dir / f"{cell['model']}--{cell['task']}.log").open('x')
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        self.running[(campaign.id, cell['model'], cell['task'])] = dict(proc=proc, lane=lane, row=row, cell=cell,
                                                                       campaign=campaign)
        self.launched += 1
        print(json.dumps({'event': 'launch', 'campaign': campaign.id, 'model': cell['model'], 'task': cell['task'],
                          'lane': lane, 'row_port': row['port']}), flush=True)

    def reap(self):
        for key, run in list(self.running.items()):
            rc = run['proc'].poll()
            if rc is None:
                continue
            del self.running[key]
            if rc:
                run['cell'].update(state='blocked', reason=f'runner exit {rc}; no automatic retry')
                run['campaign'].save()
                self.blocked = True

    def reconcile(self):
        rows = l0_campaign.read_rows()
        active = lambda campaign: {(k[1], k[2]) for k, r in self.running.items() if r['campaign'] is campaign}
        for campaign in self.campaigns:
            l0_campaign.reconcile(campaign.manifest, rows, active(campaign))
            campaign.save()
            if any(c['state'] == 'blocked' for c in campaign.manifest['cells']):
                self.blocked = True

    def step(self):
        self.reap()
        self.reconcile()
        if self.blocked:
            return
        wanted = self.pending(self.model) if self.model else []
        if not self.running and not wanted:
            later = self.pending()
            if later and not self.capped():
                order = {m: i for i, m in enumerate(l0_campaign.MODELS)}
                self.switch_model(min((c['model'] for _, c in later), key=order.get))
                wanted = self.pending(self.model)
        for lane in self.servers:
            while wanted and self.used(lane) < lanes.LANES[lane].slots and not self.capped():
                campaign, cell = wanted.pop(0)
                self.launch(lane, campaign, cell)
        levels = {c.level for c, _ in self.pending(self.model)} if self.model and not self.capped() else set()
        self.stop_rows(keep=lambda key: key[1] == self.model and key[2] in levels)

    def capped(self):
        return self.max_cells is not None and self.launched >= self.max_cells

    def finished(self):
        if self.running:
            return False
        return self.blocked or self.capped() or not self.pending()

    def shutdown(self):
        for run in list(self.running.values()):
            try:
                os.killpg(run['proc'].pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        for run in list(self.running.values()):
            run['proc'].wait()
        self.running.clear()
        self.stop_rows()
        for lane in list(self.servers):
            lanes.stop_server(lane)
        self.servers.clear()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--campaign', action='append', required=True, metavar='ID:LEVEL')
    ap.add_argument('--campaign-revision', required=True)
    ap.add_argument('--lanes', default=','.join(lanes.LANES))
    ap.add_argument('--models', default=None, help='comma-separated subset (default: the campaign roster)')
    ap.add_argument('--tasks', default=None, help='comma-separated subset (default: all six)')
    ap.add_argument('--max-cells', type=int, default=None, help='launch at most this many cells (smoke runs)')
    args = ap.parse_args()
    lane_names = args.lanes.split(',')
    if any(n not in lanes.LANES for n in lane_names):
        ap.error('unknown lane')
    models = args.models.split(',') if args.models else list(l0_campaign.MODELS)
    tasks = args.tasks.split(',') if args.tasks else list(l0_campaign.TASKS)
    if not set(models) <= set(l0_campaign.MODELS) or not set(tasks) <= set(l0_campaign.TASKS):
        ap.error('model/task outside the campaign roster')
    l0_campaign.validate_revision(args.campaign_revision)
    specs = [(cid, int(level)) for cid, level in (item.rsplit(':', 1) for item in args.campaign)]
    for _, level in specs:
        if level not in (0, 5):
            ap.error('restored campaigns support only L0 or L5')
    import shutil
    for exe in ('ruby', 'go', 'python', 'mvn', 'node', 'cargo'):
        if not shutil.which(exe):
            raise ValueError('missing task runner: ' + exe)
    l0_campaign.ROOT.mkdir(parents=True, exist_ok=True)
    with (l0_campaign.ROOT / 'driver.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        campaigns = [Campaign(cid, level, args.campaign_revision, l0_campaign.fleet_snapshot(level=level, lanes=True))
                     for cid, level in specs]
        driver = Driver(campaigns, lane_names, models, tasks, args.max_cells)
        lanes.take_hardware(lane_names)
        try:
            with lanes.FleetLocks(lane_names):
                while True:
                    l0_campaign.validate_revision(args.campaign_revision)
                    driver.step()
                    if driver.finished():
                        break
                    time.sleep(3)
        finally:
            driver.shutdown()
            print(json.dumps({'event': 'restored', 'state': lanes.restore_hardware()}), flush=True)
        return 2 if driver.blocked else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
