"""Frozen task-macro calibration from native OOF logits; not fresh evaluation.

Only held-out TRAIN-task predictions determine temperatures. No model inference,
DEV/EVAL use, semantic relabeling, best-seed selection or deployment authority.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from suite.training_admit import LABEL_ORDER
from suite.training_prepare import sha
from suite.training_run import validate_bundle, write_json

TEMPERATURES = (.25, .5, 1, 2, 4, 8)
CONFIDENCE_CUTS = (.5, .6, .7, .8, .9, .95, .975, .99)


def probability(logits, temperature):
    if len(logits) != 2 or not math.isfinite(temperature) or temperature <= 0 or not all(math.isfinite(x) for x in logits):
        raise ValueError('invalid native binary logits/temperature')
    values = [x / temperature for x in logits]
    if not all(math.isfinite(value) for value in values):
        raise ValueError('unrepresentable native scaled logits')
    high = max(values)
    exps = [math.exp(x - high) for x in values]
    total = sum(exps)
    return [x / total for x in exps]


def nll(row, temperature):
    probability(row['logits'], temperature)  # Validate before arithmetic.
    values = [x / temperature for x in row['logits']]
    high = max(values)
    return high + math.log(sum(math.exp(x - high) for x in values)) - values[row['label_id']]


def task_macro_nll(rows, temperature):
    groups = defaultdict(list)
    for row in rows:
        groups[row['task']].append(nll(row, temperature))
    if not groups:
        raise ValueError('no calibration tasks')
    return sum(sum(values) / len(values) for values in groups.values()) / len(groups)


def choose_temperature(rows):
    return min(TEMPERATURES, key=lambda t: (task_macro_nll(rows, t), abs(t - 1), t))


def reliability(decisions):
    bins = []
    for index in range(10):
        selected = [(confidence, wrong) for confidence, wrong in decisions
                    if min(int(confidence * 10), 9) == index]
        bins.append({'lower': index / 10, 'upper': (index + 1) / 10, 'count': len(selected),
                     'mean_confidence': sum(c for c, _ in selected) / len(selected) if selected else None,
                     'agreement_with_reviewed_target': 1 - sum(w for _, w in selected) / len(selected) if selected else None})
    return bins


def summarize(rows, temperature):
    confusion = [[0, 0], [0, 0]]
    decisions = []
    brier = []
    for row in rows:
        probabilities = probability(row['logits'], temperature)
        predicted = max(range(2), key=probabilities.__getitem__)
        target = row['label_id']
        if type(target) is not int or target not in (0, 1):
            raise ValueError('invalid reviewed target')
        confusion[target][predicted] += 1
        decisions.append((max(probabilities), predicted != target))
        brier.append((probabilities[1] - target) ** 2)
    curves = {}
    for cut in CONFIDENCE_CUTS:
        kept = [wrong for confidence, wrong in decisions if confidence >= cut]
        curves[str(cut)] = {'covered': len(kept), 'total': len(rows),
                            'coverage': len(kept) / len(rows),
                            'disagreements_with_reviewed_target': sum(kept),
                            'risk': sum(kept) / len(kept) if kept else None}
    per_task = {}
    for task in sorted({r['task'] for r in rows}):
        group = [r for r in rows if r['task'] == task]
        task_decisions, task_brier = [], []
        for row in group:
            probabilities = probability(row['logits'], temperature)
            predicted = max(range(2), key=probabilities.__getitem__)
            task_decisions.append((max(probabilities), predicted != row['label_id']))
            task_brier.append((probabilities[1] - row['label_id']) ** 2)
        task_curves = {}
        for cut in CONFIDENCE_CUTS:
            kept = [wrong for confidence, wrong in task_decisions if confidence >= cut]
            task_curves[str(cut)] = {'covered': len(kept), 'coverage': len(kept) / len(group),
                                     'risk': sum(kept) / len(kept) if kept else None}
        per_task[task] = {'count': len(group), 'nll': task_macro_nll(group, temperature),
                          'brier': sum(task_brier) / len(group), 'reliability': reliability(task_decisions),
                          'risk_coverage': task_curves}
    macro_curves = {}
    for cut in CONFIDENCE_CUTS:
        values = [v['risk_coverage'][str(cut)] for v in per_task.values()]
        risks = [v['risk'] for v in values if v['risk'] is not None]
        macro_curves[str(cut)] = {'mean_task_coverage': sum(v['coverage'] for v in values) / len(values),
                                 'supported_tasks': len(risks),
                                 'mean_supported_task_risk': sum(risks) / len(risks) if risks else None}
    macro_reliability = []
    for index in range(10):
        supported = [values['reliability'][index] for values in per_task.values()
                     if values['reliability'][index]['count']]
        macro_reliability.append({'lower': index / 10, 'upper': (index + 1) / 10,
                    'supported_tasks': len(supported),
                    'mean_confidence': sum(v['mean_confidence'] for v in supported) / len(supported) if supported else None,
                    'agreement_with_reviewed_target': sum(v['agreement_with_reviewed_target'] for v in supported) / len(supported) if supported else None})
    return {'count': len(rows), 'task_groups': len(per_task),
            'confusion_reviewed_target_by_prediction': confusion,
            'task_macro_nll': task_macro_nll(rows, temperature),
            'pooled_brier': sum(brier) / len(brier),
            'task_macro_brier': sum(v['brier'] for v in per_task.values()) / len(per_task),
            'pooled_reliability': reliability(decisions), 'task_macro_reliability': macro_reliability,
            'risk_coverage': curves, 'task_macro_risk_coverage': macro_curves, 'per_task': per_task}


def calibrate(root, run_path, recipe_path, output):
    recipe, rows, strata, jobs = validate_bundle(root, recipe_path)
    run = json.loads((run_path / 'run.json').read_bytes())
    complete = json.loads((run_path / 'completed.json').read_bytes())
    if run['recipe_sha256'] != sha(recipe_path.read_bytes()) or run['jobs'] != jobs or complete['fits_completed'] != len(jobs):
        raise ValueError('calibration requires complete unchanged primary fits')
    grouped = defaultdict(list)
    calls = []
    for job in jobs:
        if job['calibration_task'] is None:
            continue
        folder = run_path / job['name']
        done = json.loads((folder / 'completed.json').read_bytes())
        raw = (folder / 'calibration-logits.json').read_bytes()
        if done['fit'] != job or done['calibration_logits_sha256'] != sha(raw):
            raise ValueError('native calibration result changed')
        predictions = json.loads(raw)
        if len(predictions) != len(job['predict_ids']) or {r['id'] for r in predictions} != set(job['predict_ids']):
            raise ValueError('native calibration coverage differs')
        for prediction in predictions:
            id = prediction['id']
            source = rows[id]
            if (id in job['train_ids'] or prediction['label_id'] != source['label_id']
                    or prediction['family'] != source['family']
                    or prediction['task'] != strata['real'][id]['task']):
                raise ValueError('native prediction/held-out source differs')
            probability(prediction['logits'], 1)
            grouped[(job['arm'], job['seed'], prediction['family'])].append(prediction)
            calls.append({'fit': job['name'], 'native_result_sha256': sha(raw),
                          'input': {'model_text': source['model_text'], 'input_sha256': source['input_sha256'],
                                    'family': source['family'], 'native_attention_mask': 'ones for the whole native encoding'},
                          'output': prediction, 'reasoning': None,
                          'model_identity': 'Bound fit/pretrained/trainer/seed; fold weights were not serialized',
                          'not_fresh_or_human_gold': True})
    reports = []
    for (arm, seed, family), predictions in grouped.items():
        expected = {id for id in strata['real'] if rows[id]['family'] == family}
        if {r['id'] for r in predictions} != expected:
            raise ValueError('incomplete OOF family coverage')
        temperature = choose_temperature(predictions)
        reports.append({'arm': arm, 'seed': seed, 'family': family, 'label_order': LABEL_ORDER[family],
                        'temperature': temperature, 'fitted_on': 'TRAIN_TASK_OOF_NOT_UNBIASED_EVALUATION',
                        'summary': summarize(predictions, temperature)})
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (output / 'native-oof-calls.jsonl').open('w') as stream:
        for call in calls:
            stream.write(json.dumps(call, ensure_ascii=False, allow_nan=False) + '\n')
    (output / 'native-oof-calls.jsonl').chmod(0o600)
    write_json(output / 'calibration.json', {'recipe_sha256': sha(recipe_path.read_bytes()),
               'metric_code_sha256': sha(Path(__file__).read_bytes()), 'reports': reports,
               'native_oof_calls': len(calls), 'fresh_cases': 0, 'deployment_threshold': None,
               'limits': 'Calibration fitted on only three known TRAIN tasks, provisional assistant targets. No fresh benchmark, human gold, diagnostic scores, or deployment permission.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'run', 'recipe', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    calibrate(args.root, args.run, args.recipe, args.output)


if __name__ == '__main__':
    main()
