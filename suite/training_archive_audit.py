"""Offline capture AVAILABILITY census, not a labeler, scorer, trainer or inference client.

Read exact source-owned capture coordinates; never derive family/gold from filenames or
English. Output contains only metadata/hashes, no prompts, public prose or reasoning.
The caller must review producer/prompt/revision bindings separately. SQLite is disposable
investigation scratch; the JSON summary is suitable for a small repository audit artifact.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
import stat
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone

from suite.model_names import canonical_name
from suite.report_labels import TASK_LANGUAGES
from cria import generation


class FrozenReadError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def read_frozen(path: Path, cutoff_ns: int) -> bytes:
    """Whole regular file only; reject links, post-cutoff or concurrent replacement/growth."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise FrozenReadError('symlink_or_nonregular')
        if before.st_mtime_ns > cutoff_ns or before.st_ctime_ns > cutoff_ns:
            raise FrozenReadError('after_cutoff')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if _identity(os.fstat(fd)) != _identity(before):
                raise FrozenReadError('changed_before_read')
            chunks = []
            while data := os.read(fd, 1024 * 1024):
                chunks.append(data)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if _identity(before) != _identity(after) or _identity(before) != _identity(path.lstat()):
            raise FrozenReadError('changed_during_read')
        data = b''.join(chunks)
        if len(data) != before.st_size:
            raise FrozenReadError('incomplete_read')
        return data
    except OSError as e:
        raise FrozenReadError('io_error') from e


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def input_digest(body):
    """Exact structured context+tools identity, not near-duplicate semantic equivalence."""
    return digest({k: body[k] for k in ('messages', 'tools') if k in body})


def capture_metadata(obj):
    if not isinstance(obj, dict) or not all(k in obj for k in ('seq', 'session', 'turn', 'phase', 'iso', 'body')):
        return None
    body = obj['body']
    if (not isinstance(obj['seq'], int) or isinstance(obj['seq'], bool)
            or not isinstance(obj['iso'], str)
            or obj['session'] is not None and not isinstance(obj['session'], str)
            or obj['phase'] is not None and not isinstance(obj['phase'], str)
            or not isinstance(body, dict) or not isinstance(body.get('messages'), list)
            or not all(isinstance(m, dict) for m in body['messages'])
            or body.get('model') is not None and not isinstance(body['model'], str)):
        return None
    texts = [m.get('content') for m in body['messages'] if isinstance(m, dict) and isinstance(m.get('content'), str)]
    return {'seq': obj['seq'], 'session': obj['session'], 'turn': obj['turn'], 'iso': obj['iso'],
            'phase': obj['phase'], 'wire_model': body.get('model'), 'input_sha256': input_digest(body),
            'body_sha256': digest(body), 'messages': len(body['messages']),
            'message_text_utf8_bytes': sum(len(s.encode()) for s in texts),
            'stats': obj.get('stats') or {}}


def public_response_metadata(obj):
    if not isinstance(obj, dict):
        return {'has_public_answer': False, 'invalid_response_object': True}
    choices = obj.get('choices', [])
    if (not isinstance(choices, list) or not all(isinstance(c, dict) for c in choices)
            or any(c.get('message') is not None and not isinstance(c['message'], dict) for c in choices)):
        return {'has_public_answer': False, 'invalid_response_shape': True, 'generation_incomplete': None}
    msgs = [c.get('message') or {} for c in choices]
    usage = obj.get('usage') if isinstance(obj.get('usage'), dict) else {}
    return {'has_public_answer': any(bool(m.get('content')) or bool(m.get('tool_calls')) for m in msgs),
            'has_reasoning_channel': any(bool(m.get('reasoning_content') or m.get('reasoning')) for m in msgs),
            'generation_incomplete': generation.incomplete(obj), 'has_error': bool(obj.get('error')),
            'native_prompt_tokens': usage.get('prompt_tokens'),
            'finish_reasons': [c.get('finish_reason') for c in choices]}


def resolve_runs(rows):
    ids = sorted({r.get('run_id') for r in rows if isinstance(r.get('run_id'), str)})
    cells = {(canonical_name(r.get('model') or 'UNKNOWN'), r.get('task') or 'UNKNOWN', r.get('harness') or 'UNKNOWN') for r in rows}
    if len(cells) != 1:
        return {'join_status': 'ambiguous' if cells else 'unjoined', 'model': 'UNKNOWN', 'task': 'UNKNOWN', 'language': 'UNKNOWN', 'harness': 'UNKNOWN', 'run_ids': ids, 'revision': 'UNKNOWN'}
    model, task, harness = next(iter(cells))
    revisions = {r.get('revision') for r in rows if r.get('revision')}
    return {'join_status': 'unique_cell' if len(ids) == 1 else 'same_cell_multiple_runs', 'model': model, 'task': task,
            'language': TASK_LANGUAGES.get(task, 'UNKNOWN'), 'harness': harness, 'run_ids': ids,
            'revision': next(iter(revisions)) if len(revisions) == 1 else 'UNKNOWN'}


def artifact_kind(name):
    # Physical producer suffix categories ONLY, not task semantics, label gold or inference proof.
    for suffix, kind in (('.response.json', 'response_json'), ('.prompt.txt', 'rendered_prompt'),
                         ('.reasoning.txt', 'reasoning_sidecar'), ('.reasoning.partial.txt', 'partial_reasoning'),
                         ('.npy', 'native_array'), ('.jsonl', 'jsonl'), ('.json', 'other_json')):
        if name.endswith(suffix):
            return kind
    return 'other'


def scan(calls: Path, results: Path, archives: Path, output: Path, db_path: Path, cutoff_ns: int):
    failures = collections.Counter()
    data = read_frozen(results, cutoff_ns)
    result_sha = hashlib.sha256(data).hexdigest()
    rows = []
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if isinstance(r, dict) and all(r.get(k) is None or isinstance(r[k], str) for k in ('run_id', 'model', 'task', 'harness', 'revision', 'archive')):
                rows.append(r)
            else:
                failures['malformed_result_row'] += 1
        except (ValueError, UnicodeError):
            failures['invalid_result_line'] += 1
    by_dir = collections.defaultdict(list)
    by_request = collections.defaultdict(list)
    for r in rows:
        dirs = r.get('capture_dirs') or ([r['capture_dir']] if r.get('capture_dir') else [])
        if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
            failures['invalid_capture_dirs_shape'] += 1
            dirs = []
        for d in dirs:
            by_dir[str(Path(d))].append(r)
        snapshot = r.get('capture_snapshot') or {}
        entries = snapshot.get('entries', []) if isinstance(snapshot, dict) else None
        if not isinstance(entries, list):
            failures['invalid_snapshot_shape'] += 1
            entries = []
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get('request'), str):
                by_request[str(Path(entry['request']))].append((entry.get('sha256'), r))
    db = sqlite3.connect(db_path)
    db.execute('create table files(path text primary key, size integer, mtime_ns integer, ctime_ns integer, kind text)')
    db.execute('create table captures(path text primary key, directory text, session text, seq integer, turn text, iso text, phase text, wire_model text, request_sha text, input_sha text, body_sha text, response_sha text, paired_public integer, incomplete integer, prompt_tokens integer, message_bytes integer, meta text)')
    physical = collections.Counter(); sizes = collections.Counter(); errors=[]
    for parent, dirs, names in os.walk(calls, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(parent)/d).is_symlink())
        for name in sorted(names):
            p=Path(parent)/name
            try:
                s=p.lstat()
            except OSError:
                failures['stat_error']+=1; continue
            if not stat.S_ISREG(s.st_mode):
                failures['symlink_or_nonregular']+=1; continue
            if s.st_mtime_ns>cutoff_ns or s.st_ctime_ns>cutoff_ns:
                failures['after_cutoff_physical']+=1;continue
            kind=artifact_kind(name);physical[kind]+=1;sizes[kind]+=s.st_size
            db.execute('insert into files values(?,?,?,?,?)',(str(p),s.st_size,s.st_mtime_ns,s.st_ctime_ns,kind))
            if p.suffix!='.json' or name.endswith(('.response.json','.receive.json')) or name.startswith('inbound-'):
                continue
            try:
                raw=read_frozen(p,cutoff_ns);obj=json.loads(raw);m=capture_metadata(obj)
                if m is None:
                    if isinstance(obj, dict) and all(k in obj for k in ('seq','session','turn','phase','iso','body')):
                        failures['malformed_capture_object']+=1
                    continue
            except (FrozenReadError,ValueError,UnicodeError) as e:
                failures[getattr(e,'reason','invalid_json')]+=1; continue
            reqsha=hashlib.sha256(raw).hexdigest();rp=p.with_name(p.stem+'.response.json');reply={};rsha=None
            if rp.exists():
                try:
                    b=read_frozen(rp,cutoff_ns);reply=public_response_metadata(json.loads(b));rsha=hashlib.sha256(b).hexdigest()
                    if reply.get('invalid_response_shape') or reply.get('invalid_response_object'):failures['malformed_response_object']+=1
                except (FrozenReadError,ValueError,UnicodeError) as e:
                    failures['response_'+getattr(e,'reason','invalid_json')]+=1
            direct=[r for h,r in by_request.get(str(p),[]) if h==reqsha]
            join=resolve_runs(direct or by_dir.get(str(p.parent),[]));join['join_basis']='snapshot_request_sha256' if direct else ('declared_capture_directory' if join['join_status']!='unjoined' else 'none')
            meta={**m,**join,'response':reply,'rendered_prompt_physical_presence_only':p.with_name(p.stem+'.prompt.txt').is_file(),
                  'reasoning_sidecar_physical_presence_only':p.with_name(p.stem+'.reasoning.txt').is_file()}
            paired=bool(reply.get('has_public_answer') and not reply.get('generation_incomplete') and not reply.get('has_error'))
            pt=reply.get('native_prompt_tokens');pt=pt if isinstance(pt,int) and not isinstance(pt,bool) and pt>=0 else None
            db.execute('insert into captures values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (str(p),str(p.parent),str(m['session']),m['seq'],str(m['turn']),m['iso'],m['phase'],str(m['wire_model']),reqsha,m['input_sha256'],m['body_sha256'],rsha,int(paired),int(bool(reply.get('generation_incomplete'))),pt,m['message_text_utf8_bytes'],json.dumps(meta,ensure_ascii=False)))
        db.commit()
    # A file can change AFTER its own read while the rest of the tree is scanned.
    # Revalidate the observed inventory; never publish a growing/replaced file as frozen.
    changed=set()
    for path,size,mtime,ctime,kind in list(db.execute('select path,size,mtime_ns,ctime_ns,kind from files')):
        try:
            now=Path(path).lstat()
            stable=stat.S_ISREG(now.st_mode) and (now.st_size,now.st_mtime_ns,now.st_ctime_ns)==(size,mtime,ctime)
        except OSError:
            stable=False
        if not stable:
            changed.add(path);physical[kind]-=1;sizes[kind]-=size;failures['changed_after_inventory']+=1
            db.execute('delete from files where path=?',(path,))
    for path,meta in list(db.execute('select path,meta from captures')):
        if path in changed:
            db.execute('delete from captures where path=?',(path,));continue
        response=str(Path(path).with_name(Path(path).stem+'.response.json'))
        if response in changed:
            m=json.loads(meta);m['response']={'frozen_state':'changed_after_read'}
            db.execute('update captures set response_sha=null,paired_public=0,prompt_tokens=null,meta=? where path=?',(json.dumps(m),path))
    db.commit()
    archive_stats=collections.Counter();result_cells=collections.Counter()
    for r in rows:
        join=resolve_runs([r]);result_cells[(join['model'],join['language'],join['task'],join['harness'])]+=1
        a=Path(r['archive']) if r.get('archive') else None
        archive_stats['rows_with_archive_path' if a else 'rows_without_archive_path']+=1
        if a:archive_stats['archive_exists' if a.is_dir() else 'archive_missing']+=1;archive_stats['workspace_exists' if (a/'workspace').is_dir() else 'workspace_missing']+=1
    archive_stats['actual_top_level_archive_directories']=sum(p.is_dir() and not p.name.startswith('_') for p in archives.iterdir())
    matrix=collections.defaultdict(lambda:collections.Counter());examples={};phases=collections.Counter();wiremodels=collections.Counter();groups=collections.Counter()
    for p,phase,paired,prompt_tokens,nbytes,rawmeta in db.execute('select path,phase,paired_public,prompt_tokens,message_bytes,meta from captures'):
        m=json.loads(rawmeta);key=(phase or 'UNKNOWN',m['model'],m['language'],m['task'],m['harness'],m['join_status']);v=matrix[key];v['requests']+=1;v['paired_public_candidates']+=paired;v['native_prompt_tokens_present']+=int(prompt_tokens is not None);v['max_native_prompt_tokens']=max(v['max_native_prompt_tokens'],prompt_tokens or 0);v['max_full_string_message_utf8_bytes']=max(v['max_full_string_message_utf8_bytes'],nbytes);phases[phase or 'UNKNOWN']+=1;wiremodels[m['wire_model'] or 'UNKNOWN']+=1;groups[m['join_status']]+=1
        if paired and key not in examples:examples[key]={'request':str(p),'request_sha256':m and db.execute('select request_sha from captures where path=?',(p,)).fetchone()[0],'run_ids':m['run_ids'],'revision':m['revision']}
    count=lambda sql:db.execute(sql).fetchone()[0]
    summary={'schema':'training-archive-availability-audit-v1','cutoff_utc':datetime.fromtimestamp(cutoff_ns/1e9,timezone.utc).isoformat(),'cutoff_ns':cutoff_ns,'completed_utc':datetime.now(timezone.utc).isoformat(),'results_source':{'path':str(results),'sha256':result_sha,'bytes':len(data),'rows':len(rows)},'physical_files_by_kind':dict(physical),'physical_bytes_by_kind':dict(sizes),'excluded_or_invalid':dict(failures),'request_records':count('select count(*) from captures'),'distinct_stored_coordinates':count('select count(*) from (select session,seq,iso,turn from captures group by session,seq,iso,turn)'),'distinct_request_sha256':count('select count(distinct request_sha) from captures'),'distinct_full_context_tools_sha256':count('select count(distinct input_sha) from captures'),'paired_public_candidates':count('select sum(paired_public) from captures'),'distinct_capture_directories':count('select count(distinct directory) from captures'),'distinct_session_ids':count('select count(distinct session) from captures'),'request_records_with_response_json':count('select count(*) from captures where response_sha is not null'),'generation_incomplete':count('select sum(incomplete) from captures'),'join_status_request_counts':dict(groups),'native_requested_wire_models':dict(wiremodels),'phases':dict(phases),'archives':dict(archive_stats),'result_cells':[{'model':k[0],'language':k[1],'task':k[2],'harness':k[3],'result_rows':v} for k,v in sorted(result_cells.items())],'phase_cell_matrix':[{'phase':k[0],'model':k[1],'language':k[2],'task':k[3],'harness':k[4],'join_status':k[5],**v,'representative_reference':examples.get(k)} for k,v in sorted(matrix.items())],
              'limits':['Availability metadata, not behavioral prevalence or gold labels. No verdict parser duplicated; labels NOT extracted.','Public answer existence and generation completeness do not establish a correct label, native finish proof, safety or trainability.','Stored coordinates are not authenticated distinct network dispatches; synthetic/replay/copy provenance may be unknown.','Directory join is weaker than exact snapshot SHA join; multi-run ambiguity is retained.','Requested wire model is distinct from suite coder identity; no inference about actual teacher weights.','Full string-message bytes exclude structured non-string contents; native usage prompt_tokens are not future raw-candidate NLI token lengths.','Human language, secret/PII redaction, near-duplicate semantic groups and question correctness are UNASSESSED.']}
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calls',type=Path,required=True);p.add_argument('--results',type=Path,required=True);p.add_argument('--archives',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--database',type=Path,required=True);p.add_argument('--cutoff-ns',type=int);a=p.parse_args()
    if a.database.exists() or a.output.exists():p.error('Use NEW output/database paths; never overwrite a prior frozen audit.')
    scan(a.calls,a.results,a.archives,a.output,a.database,a.cutoff_ns or time.time_ns())

if __name__=='__main__':main()
