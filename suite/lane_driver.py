#!/usr/bin/env python3
"""Run restored-fleet battery cells in parallel on the lanes (suite/lanes.py): one cell per slot.

One model is served at a time: its lanes run its pending cells across all free slots, one cria instance per
active row (lane x model x level), and the lanes switch to the next model only when every slot has drained.
A campaign is an id and a level; a cell (model, task) with no result row under that id runs, and runs again if
its run ended without one. A finished cell awaiting its usefulness judgment does not hold a slot or the run.

    python suite/lane_driver.py --campaign l5-20261102:5 [--campaign l0-20261102:0] \
        [--lanes 3090x4,3080x2] [--models M,..] [--tasks T,..]
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

RETRY_SECONDS = 120

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
try:
    from . import l0_campaign, lanes
except ImportError:
    import l0_campaign
    import lanes


class Campaign:
    def __init__(self, campaign_id, level):
        self.id, self.level = campaign_id, level
        self.dir = l0_campaign.campaign_dir(campaign_id)
        self.dir.mkdir(parents=True, exist_ok=True)

    def event(self, **fields):
        with (self.dir / 'driver.jsonl').open('a') as events:
            events.write(json.dumps({'at': time.time(), **fields}) + '\n')


class Driver:
    def __init__(self, campaigns, lane_names, models, tasks, max_cells):
        self.campaigns, self.lane_names = campaigns, lane_names
        self.models, self.tasks, self.max_cells = models, tasks, max_cells
        self.running = {}          # (campaign id, model, task) -> dict(proc, lane, row, campaign)
        self.retry_at = {}           # (campaign id, model, task) -> earliest relaunch time
        self.servers = {}          # lane -> server state
        self.rows = {}             # (lane, model, level) -> row dict
        self.lane_model = {}       # lane -> the model its server serves (each card switches on its own)
        self.launched = 0
        self.next_port = lanes.ROW_PORT_BASE

    # ------------------------------------------------------------------ planning
    def pending(self, model=None):
        """(campaign, model, task) cells with no result row that are not running now."""
        rows = l0_campaign.read_rows()
        out = []
        for campaign in self.campaigns:
            for m, task, state in l0_campaign.cells(campaign.id, campaign.level, rows):
                if (state == 'pending' and m in self.models and task in self.tasks and (model is None or m == model)
                        and (campaign.id, m, task) not in self.running
                        and time.time() >= self.retry_at.get((campaign.id, m, task), 0)):
                    out.append((campaign, m, task))
        return out

    def used(self, lane):
        return sum(1 for run in self.running.values() if run['lane'] == lane)

    # ------------------------------------------------------------------ lifecycle
    def stop_rows(self, keep=lambda key: False):
        for key, row in list(self.rows.items()):
            if not keep(key) and not any(r['row'] is row for r in self.running.values()):
                lanes.stop_row(row)
                del self.rows[key]

    def fits(self, model, lane):
        return lanes.lane_window(model, lane) is not None

    def switch_lane(self, lane, model):
        self.stop_rows(keep=lambda key: key[0] != lane)
        if lane in self.servers:
            lanes.stop_server(lane)
            del self.servers[lane]
        self.servers[lane] = lanes.start_server(model, lane, lanes.lane_window(model, lane))
        self.lane_model[lane] = model
        print(json.dumps({'event': 'lane-up', 'lane': lane, 'model': model,
                          'slots': self.servers[lane]['slots'], 'window': self.servers[lane]['window']}), flush=True)

    def next_model(self, lane, pending):
        """The model this idle card serves next: the other card's model if it fits here and has work, else the
        first roster model with pending work that fits here and is not already being served elsewhere."""
        have = {m for _, m, _ in pending if self.fits(m, lane)}
        others = {self.lane_model.get(n) for n in self.lane_names if n != lane}
        shared = [m for m in others if m in have]
        if shared:
            return shared[0]
        free = [m for m in l0_campaign.MODELS if m in have and m not in others]
        return free[0] if free else None

    def row_for(self, lane, model, level):
        key = (lane, model, level)
        if key not in self.rows:
            roles = l0_campaign.role_sampling(model)
            self.rows[key] = lanes.start_row(lane, model, level, roles, self.servers[lane]['window'], port=self.next_port)
            self.next_port += 1
        return self.rows[key]

    def launch(self, lane, campaign, model, task):
        row = self.row_for(lane, model, campaign.level)
        command = l0_campaign.cell_command(campaign.id, campaign.level, model, task, Path(row['dir']) / 'row.json')
        campaign.event(event='launch', model=model, task=task, lane=lane, row=row['dir'])
        log = (campaign.dir / f"{model}--{task}.log").open('a')
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        self.running[(campaign.id, model, task)] = dict(proc=proc, lane=lane, row=row, campaign=campaign)
        self.launched += 1
        print(json.dumps({'event': 'launch', 'campaign': campaign.id, 'model': model, 'task': task,
                          'lane': lane, 'row_port': row['port']}), flush=True)

    def reap(self):
        for key, run in list(self.running.items()):
            rc = run['proc'].poll()
            if rc is None:
                continue
            del self.running[key]
            run['campaign'].event(event='exit', model=key[1], task=key[2], returncode=rc)
            self.retry_at[key] = time.time() + RETRY_SECONDS   # a cell that ended without a result reruns after a pause

    def step(self):
        for lane in self.servers:
            lanes.check_server(lane)
        self.reap()
        if not self.capped():
            for lane in self.lane_names:
                current = self.lane_model.get(lane)
                if self.used(lane) == 0 and not self.pending(current) if current else self.used(lane) == 0:
                    model = self.next_model(lane, self.pending())
                    if model is not None and model != current:
                        self.switch_lane(lane, model)
        for lane in self.lane_names:
            model = self.lane_model.get(lane)
            if model is None:
                continue
            wanted = self.pending(model)
            while wanted and not self.capped() and self.used(lane) < lanes.LANES[lane].slots:
                campaign, m, task = wanted.pop(0)
                self.launch(lane, campaign, m, task)
        live = {(lane, c.level) for lane, model in self.lane_model.items() for c, _, _ in self.pending(model)}
        self.stop_rows(keep=lambda key: self.lane_model.get(key[0]) == key[1] and (key[0], key[2]) in live)

    def capped(self):
        return self.max_cells is not None and self.launched >= self.max_cells

    def finished(self):
        return not self.running and (self.capped() or not self.pending())

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
    specs = [(cid, int(level)) for cid, level in (item.rsplit(':', 1) for item in args.campaign)]
    for _, level in specs:
        if level not in range(6):
            ap.error('restored campaigns support L0-L5')
    import shutil
    for exe in ('ruby', 'go', 'python', 'mvn', 'node', 'cargo'):
        if not shutil.which(exe):
            raise ValueError('missing task runner: ' + exe)
    l0_campaign.ROOT.mkdir(parents=True, exist_ok=True)
    with (l0_campaign.ROOT / 'driver.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        campaigns = [Campaign(cid, level) for cid, level in specs]
        driver = Driver(campaigns, lane_names, models, tasks, args.max_cells)
        lanes.take_hardware(lane_names)
        try:
            with lanes.FleetLocks(lane_names):
                while True:
                    driver.step()
                    if driver.finished():
                        break
                    time.sleep(3)
        finally:
            driver.shutdown()
            print(json.dumps({'event': 'restored', 'state': lanes.restore_hardware()}), flush=True)
        return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
