"""Authorized offline two-head experiment; never imported by the production service.

ML dependencies are lazy and belong in the isolated experiment environment. Full
native inputs only; frozen archive diagnostics are NOT a fresh benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import resource
import time

from suite.training_admit import LABEL_ORDER, load_jsonl, model_text
from suite.training_prepare import sha

ARMS = ('real_only', 'real_plus_11_reviewed_standalone_synthetic')


def validate_authorization(auth, recipe_sha, gpu_uuid):
    if (auth.get('training_authorized') is not True or auth.get('recipe_sha256') != recipe_sha
            or auth.get('gpu_uuid') != gpu_uuid):
        raise ValueError('training authorization does not match recipe/device')


def fit_specs(seeds, folds, real_ids, synthetic_ids):
    real, synthetic = set(real_ids), set(synthetic_ids)
    if real & synthetic:
        raise ValueError('real/synthetic identity collision')
    jobs = []
    held = set()
    for fold in folds['folds']:
        train, calibration = set(fold['real_training_ids']), set(fold['real_calibration_ids'])
        if train & calibration or train | calibration != real or held & calibration:
            raise ValueError('invalid fold exclusion/coverage')
        if set(fold['mixed_arm_synthetic_training_ids']) != synthetic:
            raise ValueError('invalid fold synthetic identities')
        held.update(calibration)
    if held != real:
        raise ValueError('incomplete fold calibration coverage')
    for arm in ARMS:
        extra = synthetic if arm == ARMS[1] else set()
        for seed in seeds:
            for n, fold in enumerate(folds['folds']):
                jobs.append({'name': f'{arm}-seed{seed}-fold{n}', 'arm': arm, 'seed': seed,
                             'calibration_task': fold['calibration_task'],
                             'train_ids': sorted(set(fold['real_training_ids']) | extra),
                             'predict_ids': sorted(fold['real_calibration_ids'])})
            jobs.append({'name': f'{arm}-seed{seed}-final', 'arm': arm, 'seed': seed,
                         'calibration_task': None, 'train_ids': sorted(real | extra), 'predict_ids': []})
    return jobs


def loss_weights(ids, real_metadata):
    real = [i for i in ids if i in real_metadata]
    counts = Counter((real_metadata[i]['task'], real_metadata[i]['family']) for i in real)
    if not real:
        raise ValueError('no real training inputs')
    return {i: len(real) / (len(counts) * counts[(real_metadata[i]['task'], real_metadata[i]['family'])])
            if i in real_metadata else 1.0 for i in ids}


def accumulated_batches(ids, size):
    if size <= 0:
        raise ValueError('invalid accumulation size')
    return [ids[start:start + size] for start in range(0, len(ids), size)]


def learning_rate_factor(step, total):
    warmup = math.ceil(0.1 * total)
    return step / warmup if step < warmup else max(0.0, (total - step) / (total - warmup))


def write_json(path, value):
    """Atomic owned output: a partial receipt must not look complete."""
    temp = path.with_suffix(path.suffix + '.pending')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.chmod(0o600)
    temp.replace(path)


def optimizer_groups(torch, model, settings):
    groups = {}
    norm_ids = {id(p) for module in model.modules() if isinstance(module, torch.nn.LayerNorm)
                for p in module.parameters(recurse=False)}
    for name, parameter in model.named_parameters():
        lr = settings['heads_lr'] if name.startswith('heads.') else settings['encoder_lr']
        decay = 0 if name.endswith('.bias') or id(parameter) in norm_ids else settings['weight_decay']
        groups.setdefault((lr, decay), []).append(parameter)
    return [{'params': parameters, 'lr': lr, 'weight_decay': decay}
            for (lr, decay), parameters in groups.items()]


def loading_receipt(info):
    """Native Transformers loading facts contain unordered sets in v5."""
    return {key: sorted(value) if isinstance(value, set) else value for key, value in info.items()}


def make_model(torch, encoder):
    class Joint(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = encoder
            self.heads = torch.nn.ModuleDict({family: torch.nn.Linear(encoder.config.hidden_size, 2)
                                              for family in LABEL_ORDER})

        def forward(self, ids, mask, family):
            hidden = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state.float()
            valid = mask.unsqueeze(-1).float()
            pooled = (hidden * valid).sum(1) / valid.sum(1)
            return self.heads[family](pooled)
    return Joint()


def validate_bundle(root, recipe_path):
    recipe = json.loads(recipe_path.read_bytes())
    card = json.loads((recipe_path.parent / 'qualification.json').read_bytes())
    for name, digest in card['repository_contract_sha256'].items():
        if sha((recipe_path.parent / name).read_bytes()) != digest:
            raise ValueError(f'changed contract: {name}')
    for name, digest in card['local_artifacts_sha256'].items():
        if sha(Path(name).read_bytes()) != digest:
            raise ValueError(f'changed qualified input: {name}')
    prepared = root / 'prepared-ettin68-final'
    for name, digest in recipe['cohort_file_sha256'].items():
        if sha((prepared / name).read_bytes()) != digest:
            raise ValueError(f'changed admitted export: {name}')
    real, synthetic = load_jsonl(prepared / 'train-real.jsonl'), load_jsonl(prepared / 'train-synthetic.jsonl')
    if set(real) & set(synthetic):
        raise ValueError('source identity collision')
    strata = json.loads((root / 'training-strata-final.json').read_bytes())
    folds = json.loads((root / 'calibration-folds-admitted-final.json').read_bytes())
    if set(strata['real']) != set(real) or set(strata['synthetic']) != set(synthetic):
        raise ValueError('stratum/source identities differ')
    for fold in folds['folds']:
        if any(strata['real'][i]['task'] == fold['calibration_task'] for i in fold['real_training_ids']):
            raise ValueError('held task reaches shared encoder')
        if any(strata['real'][i]['task'] != fold['calibration_task'] for i in fold['real_calibration_ids']):
            raise ValueError('calibration task differs')
    jobs = fit_specs(recipe['seeds'], folds, real, synthetic)
    return recipe, {**real, **synthetic}, strata, jobs


def run(args):
    root, recipe_path = Path(args.root), Path(args.recipe)
    recipe, rows, strata, jobs = validate_bundle(root, recipe_path)
    auth = json.loads(Path(args.authorization).read_bytes())
    validate_authorization(auth, sha(recipe_path.read_bytes()), args.gpu_uuid)
    if os.environ.get('CUDA_VISIBLE_DEVICES') != args.gpu_uuid:
        raise ValueError('exact authorized GPU UUID must be the only visible device')
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    import torch
    from transformers import AutoModel
    from tokenizers import Tokenizer
    from safetensors.torch import save_file
    if torch.__version__ != '2.8.0+cu128':
        raise ValueError('unexpected Torch build')
    if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != 'NVIDIA GeForce RTX 3090':
        raise ValueError('wrong device')
    if not torch.cuda.is_bf16_supported():
        raise ValueError('frozen BF16 arm unsupported')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    preflight = json.loads((root / 'execution/gpu-preflight.json').read_bytes())
    checkpoint = Path(preflight['checkpoint'])
    digest = hashlib.sha256()
    with checkpoint.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    if digest.hexdigest() != recipe['published_checkpoint_sha256']:
        raise ValueError('pretrained checkpoint changed')
    snapshot = checkpoint.parent
    for name, digest in recipe['metadata_sha256'].items():
        if sha((snapshot / name).read_bytes()) != digest:
            raise ValueError(f'checkpoint metadata changed: {name}')
    tokenizer = Tokenizer.from_file(str(snapshot / 'tokenizer.json'))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    measured = {m['id']: m for m in json.loads((root / 'native-fit-ettin68.json').read_bytes())['measurements']}
    encoded = {}
    for id, row in rows.items():
        if row['model_text'] != model_text(row) or row['label_id'] != LABEL_ORDER[row['family']].index(row['label']):
            raise ValueError('input/label adapter differs')
        ids = tokenizer.encode(row['model_text']).ids
        if len(ids) != measured[id]['tokens_with_native_special_tokens'] or len(ids) > recipe['native_limit']:
            raise ValueError('native complete tokenization changed or NO_FIT')
        encoded[id] = ids
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_json(output / 'run.json', {'recipe_sha256': sha(recipe_path.read_bytes()),
               'trainer_sha256': sha(Path(__file__).read_bytes()), 'authorization': auth,
               'jobs': jobs, 'status': 'RUNNING', 'fresh_evaluation_cases': 0,
               'deployment_authorized': False})

    def event(kind, **fields):
        entry = {'event': kind, 'at_ns': time.time_ns(), **fields}
        with (output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(entry, allow_nan=False) + '\n')
            stream.flush()
        if kind == 'optimizer_step' and not (output / 'first-optimizer-step.json').exists():
            write_json(output / 'first-optimizer-step.json', entry)
        print(json.dumps(entry, allow_nan=False), flush=True)

    def input_tensor(id):
        ids = torch.tensor([encoded[id]], dtype=torch.long, device='cuda')
        return ids, torch.ones_like(ids)

    def predict(model, ids):
        model.eval()
        predictions = []
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
            for id in ids:
                row = rows[id]
                x, mask = input_tensor(id)
                logits = model(x, mask, row['family']).float()[0]
                if not torch.isfinite(logits).all():
                    raise ValueError('nonfinite calibration logits')
                predictions.append({'id': id, 'family': row['family'], 'label_id': row['label_id'],
                                    'task': strata['real'][id]['task'], 'logits': logits.cpu().tolist()})
        return predictions

    def fit(job):
        started = time.monotonic()
        folder = output / job['name']
        folder.mkdir(mode=0o700)
        random.seed(job['seed'])
        torch.manual_seed(job['seed'])
        torch.cuda.manual_seed_all(job['seed'])
        torch.cuda.reset_peak_memory_stats()
        encoder, loading = AutoModel.from_pretrained(str(snapshot), local_files_only=True,
                                  trust_remote_code=False, weights_only=True,
                                  attn_implementation='eager', output_loading_info=True)
        if (loading.get('missing_keys') or loading.get('mismatched_keys') or loading.get('error_msgs')
                or any(not k.startswith(('head.', 'decoder.')) for k in loading.get('unexpected_keys', []))):
            raise ValueError(f'encoder checkpoint mismatch: {loading}')
        if encoder.config.hidden_size != 512 or sum(p.numel() for p in encoder.parameters()) != 68144640:
            raise ValueError('encoder differs from shape proof')
        encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        torch.manual_seed(job['seed'])
        model = make_model(torch, encoder).to('cuda')
        optimizer = torch.optim.AdamW(optimizer_groups(torch, model, recipe['optimizer']),
                                     betas=tuple(recipe['optimizer']['betas']), eps=recipe['optimizer']['epsilon'])
        total = recipe['epoch_count'] * math.ceil(len(job['train_ids']) / 16)
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: learning_rate_factor(step, total))
        rng = random.Random(job['seed'])
        weights = loss_weights(job['train_ids'], strata['real'])
        step = 0
        event('fit_started', fit=job['name'], training_examples=len(job['train_ids']),
              calibration_examples=len(job['predict_ids']), encoder_load=loading_receipt(loading))
        for epoch in range(recipe['epoch_count']):
            model.train()
            ids = sorted(job['train_ids'])
            rng.shuffle(ids)
            epoch_loss = 0.0
            for batch in accumulated_batches(ids, 16):
                optimizer.zero_grad(set_to_none=True)
                batch_loss = 0.0
                for id in batch:
                    row = rows[id]
                    x, mask = input_tensor(id)
                    with torch.autocast('cuda', dtype=torch.bfloat16):
                        logits = model(x, mask, row['family'])
                        target = torch.tensor([row['label_id']], device='cuda')
                        loss = torch.nn.functional.cross_entropy(logits, target) * weights[id] / len(batch)
                    if not torch.isfinite(loss):
                        raise ValueError('nonfinite training loss')
                    loss.backward()
                    batch_loss += loss.detach().item()
                norm = torch.nn.utils.clip_grad_norm_(model.parameters(), recipe['optimizer']['gradient_norm_clip'], error_if_nonfinite=True)
                optimizer.step()
                scheduler.step()
                step += 1
                allocated, reserved = torch.cuda.max_memory_allocated(), torch.cuda.max_memory_reserved()
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                if reserved > 18 * 1024**3 or rss > 16 * 1024**3:
                    raise RuntimeError('frozen resource ceiling exceeded; no truncation or recipe substitution')
                epoch_loss += batch_loss * len(batch)
                event('optimizer_step', fit=job['name'], epoch=epoch + 1, step=step,
                      examples=len(batch), weighted_mean_loss=batch_loss, gradient_norm=float(norm),
                      peak_allocated_bytes=allocated, peak_reserved_bytes=reserved, peak_host_rss_bytes=rss)
            event('epoch_complete', fit=job['name'], epoch=epoch + 1, examples=len(ids),
                  weighted_mean_loss=epoch_loss / len(ids))
        predictions = predict(model, job['predict_ids'])
        write_json(folder / 'calibration-logits.json', predictions)
        artifacts = {}
        if job['calibration_task'] is None:
            state = {name: tensor.detach().to(device='cpu', dtype=torch.float16 if name.startswith('encoder.') else torch.float32).contiguous()
                     for name, tensor in model.state_dict().items()}
            save_file(state, str(folder / 'joint.safetensors'))
            encoder.config.save_pretrained(folder)
            (folder / 'tokenizer.json').write_bytes((snapshot / 'tokenizer.json').read_bytes())
            weight_bytes = (folder / 'joint.safetensors').stat().st_size
            if weight_bytes >= 250000000:
                raise ValueError('entire proposed joint weight artifact exceeds budget')
            artifacts = {'joint_weight_bytes': weight_bytes, 'joint_sha256': sha((folder / 'joint.safetensors').read_bytes()),
                         'NOT_DEPLOYMENT_CERTIFIED': 'CPU operators/parity/RSS/latency and fresh evaluation unvalidated'}
        write_json(folder / 'completed.json', {'fit': job, 'optimizer_steps': step,
                   'elapsed_seconds': time.monotonic() - started, 'artifacts': artifacts,
                   'calibration_logits_sha256': sha((folder / 'calibration-logits.json').read_bytes())})
        event('fit_completed', fit=job['name'], optimizer_steps=step, **artifacts)

    try:
        for job in jobs:
            fit(job)
            torch.cuda.empty_cache()
        write_json(output / 'completed.json', {'fits_completed': len(jobs), 'status': 'FITS_COMPLETE_CALIBRATION_AND_DIAGNOSTIC_REPORT_PENDING',
                   'fresh_evaluation_cases': 0, 'deployment_authorized': False})
    except BaseException as error:
        event('run_failed', error_type=type(error).__name__, message=str(error))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'recipe', 'authorization', 'gpu-uuid', 'output'):
        parser.add_argument('--' + name, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
