#!/usr/bin/env python3
"""Restored-fleet campaign basics: the roster, the role sampling a row applies, and which cells still lack a result.

A campaign is an id and an engagement level. Its cells are every (model, task) of the roster at that level; a cell
is finished once a result row carrying the campaign id exists for it, and a cell without one runs (again).
"""
from __future__ import annotations
import json
import re
import sys
import tomllib
from pathlib import Path

try:
    from .battery_status import TASKS
    from . import results_store as _rs
except ImportError:
    from battery_status import TASKS
    import results_store as _rs

SUITE = Path(__file__).resolve().parent
ROOT = Path.home()/'.cria/suite/_campaigns'
CONFIG = Path.home()/'.config/llama-fleet/models.toml'
ROLES = CONFIG.with_name('roles.json')
LAUNCHER = Path.home()/'.local/bin/llama-fleet'
MODELS = ('gemma4_12b','ornith1.5_9b','bonsai2','nemotron-elastic','ling3.0_tiny',
          'phi4','k2_horizon_7b','qwen3.8_9b_distill')
RESULTS = SUITE/'results/results.jsonl'


def campaign_dir(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',name):
        raise ValueError('campaign id must be a safe single directory name')
    return ROOT/name


def role_sampling(model):
    """The model's canonical four-role sampling."""
    return json.loads(ROLES.read_text())[model]


def context(model):
    """The model's served context window."""
    merged = tomllib.loads(CONFIG.read_text())
    return {**merged.get('defaults',{}),**merged['models'][model]}['ctx']


def read_rows():
    return _rs.read_rows(RESULTS) if RESULTS.exists() else []


def has_result(row):
    """A row is a cell's result unless the run aborted, died in the harness, or lost its workspace."""
    return not (row.get('aborted') or row.get('workspace_lost') or row.get('terminal') == 'harness-error')


def cells(campaign_id, level, rows):
    """Each roster cell as (model, task, state): 'done' (judged), 'awaiting-usefulness' or 'pending' (no result)."""
    out=[]
    for model in MODELS:
        for task in TASKS:
            found=[r for r in rows if r.get('campaign_id') == campaign_id and r.get('level') == level
                   and (r.get('model'),r.get('task')) == (model,task) and has_result(r)]
            state='pending' if not found else 'done' if any(isinstance(r.get('usefulness_percent'),int) for r in found) \
                else 'awaiting-usefulness'
            out.append((model,task,state))
    return out


def cell_command(campaign_id, level, model, task, lane_row=None):
    command = [sys.executable,str(SUITE/'battery_run.py'),'--level',str(level),'--model',model,
               '--task',task,'--restored-fleet','--campaign-id',campaign_id]
    return command + ['--lane-row', str(lane_row)] if lane_row else command
