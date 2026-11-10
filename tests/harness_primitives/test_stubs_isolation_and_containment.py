"""The real stubs against a hostile workspace: nothing in the repository runs, nothing below ROOT is followed, `..` and FIFOs are
refused. Lifted from the phase-1 prototype (docs/harness-primitives.md section 10), now against the shipped constants."""
import os
import stat
import subprocess

import pytest

from prims_rig import BASH, GROUP, ls, run, sha, write

SHADOWED = ('hashlib', 'base64', 'json', 'zlib', 'os', 'sys', 'subprocess', 'fcntl', 'stat', 'time', 'encodings', 're', 'io', 'codecs',
            'shutil', 'sitecustomize', 'usercustomize')


@pytest.fixture
def hostile(tmp_path):
    """A workspace that shadows the stdlib, plants a `python3` first on PATH and points PYTHONPATH at itself; `outside` is where
    any executed shadow would leave a marker."""
    root, outside, scratch = tmp_path / 'root', tmp_path / 'outside', tmp_path / 'scratch'
    for d in (root, outside, scratch, root / 'bin', root / 'src'):
        d.mkdir(exist_ok=True)
    for name in SHADOWED:
        (root / f'{name}.py').write_text(f"open({str(outside / ('PWNED_' + name))!r}, 'w').write('x')\n")
    for tool in ('python3', 'env', 'bash'):         # every program a primitive's command line or supervisor looks up by name
        planted = root / 'bin' / tool
        planted.write_text(f'#!/bin/sh\ntouch {outside}/PWNED_{tool}\n')
        planted.chmod(0o755)
    (root / 'src' / 'a.py').write_bytes(b'x = 1\r\nprint(\xff)\n')
    (outside / 'secret.txt').write_text('TOP SECRET')
    env = {**os.environ, 'PATH': f'{root / "bin"}:{os.environ["PATH"]}', 'PYTHONPATH': str(root), 'PYTHONSTARTUP': str(root / 'sitecustomize.py')}
    return type('H', (), dict(root=root, outside=outside, scratch=scratch, env=env,
                              pwned=lambda self: sorted(p.name for p in outside.glob('PWNED_*'))))()


def test_the_isolation_control_the_plain_forms_do_run_the_workspaces_code(hostile):
    """Without this the tests below prove nothing: the same hostile tree DOES defeat `python3 -c` and `python3 -I -c` under a planted PATH."""
    subprocess.run([BASH, '-c', 'python3 -c "import hashlib"'], cwd=hostile.root, env=hostile.env, capture_output=True)
    assert 'PWNED_python3' in hostile.pwned()
    for p in hostile.outside.glob('PWNED_*'):
        p.unlink()
    subprocess.run([BASH, '-c', 'python3 -I -c "import hashlib"'], cwd=hostile.root, env=hostile.env, capture_output=True)
    assert 'PWNED_python3' in hostile.pwned()            # -I alone does not stop the planted interpreter: env -i PATH= is required
    for p in hostile.outside.glob('PWNED_*'):
        p.unlink()
    subprocess.run([BASH, '-c', 'env -i PATH=/usr/bin:/bin python3 -I -S -c "import hashlib"'], cwd=hostile.root, env=hostile.env, capture_output=True)
    assert 'PWNED_env' in hostile.pwned()                # and `env` itself, found through the PATH, is the planted one


def test_every_stub_ignores_a_workspace_that_shadows_the_stdlib_and_plants_python3(hostile):
    r, o, s, e = hostile.root, hostile.outside, hostile.scratch, hostile.env
    assert run('read', [r, 'src/a.py', 0, 100, 0], cwd=r, env=e).data == b'x = 1\r\nprint(\xff)\n'
    assert write(r, 'f.txt', b'hi', '-', cwd=r, env=e).header['landed'] == 1 and (r / 'f.txt').read_bytes() == b'hi'
    assert write(r, 'big.bin', b'0123456789', '-', staged=True, cwd=r, env=e).header['err'] == 'FileNotFoundError'
    assert run('put', [r, 'big.bin', GROUP, 0, 1], b'0123456789', cwd=r, env=e).header['ok'] == 1
    assert ls(r, '', 1, cwd=r, env=e).header['ok'] == 1
    assert run('search', [r, 'x', 0, 10, 1 << 20], text='["src/a.py"]', cwd=r, env=e).header['ok'] == 1
    done = run('run', ['start', s, 'tok1', 10, 5, r, 0], cwd=r, env=e, text='echo ran-ok')
    assert done.header['state'] == 'done' and done.data == b'ran-ok\n'
    assert run('rm', [r, 'f.txt', 'f', '*'], cwd=r, env=e).header['ok'] == 1
    assert hostile.pwned() == []


def test_run_gives_the_command_the_users_own_environment_while_the_supervisor_stays_isolated(tmp_path):
    root, scratch = tmp_path / 'r', tmp_path / 's'
    root.mkdir(); scratch.mkdir(); (root / 'tools').mkdir()
    tool = root / 'tools' / 'mytool'
    tool.write_text('#!/bin/sh\necho mytool-ran\n')
    tool.chmod(0o755)
    env = {**os.environ, 'PATH': f'{root / "tools"}:{os.environ["PATH"]}', 'MYVAR': 'kept'}
    done = run('run', ['start', scratch, 't1', 10, 5, root, 0], cwd=root, env=env,
               text='mytool; echo "MYVAR=$MYVAR"; echo "PATH0=${PATH%%:*}"')
    assert done.data.decode().splitlines() == ['mytool-ran', 'MYVAR=kept', f'PATH0={root / "tools"}'] and done.header['exit'] == 0


@pytest.fixture
def tree(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    (root / 'src').mkdir(parents=True); outside.mkdir()
    (root / 'src' / 'a.py').write_bytes(b'x = 1\r\n')
    (outside / 'secret.txt').write_text('TOP SECRET')
    (root / 'link.txt').symlink_to(outside / 'secret.txt')
    (root / 'linkdir').symlink_to(outside)
    (root / 'inlink.py').symlink_to('src/a.py')
    os.mkfifo(root / 'fifo')
    return type('T', (), dict(root=root, outside=outside))()


@pytest.mark.parametrize('rel,errno', [('link.txt', 40), ('linkdir/secret.txt', 20), ('inlink.py', 40), ('../x', 22), ('src/../src/a.py', 22), ('nope', 2)])
def test_read_never_follows_a_link_below_root_and_refuses_dotdot(tree, rel, errno):
    done = run('read', [tree.root, rel, 0, 100, 0], cwd=tree.root)
    assert done.header['ok'] == 0 and done.header['errno'] == errno, done.header
    assert (tree.outside / 'secret.txt').read_text() == 'TOP SECRET'


def test_read_refuses_a_directory_and_a_fifo_without_blocking_and_reports_the_files_identity(tree):
    assert run('read', [tree.root, 'src', 0, 10, 0], cwd=tree.root).header['err'] == 'notfile'
    assert run('read', [tree.root, 'fifo', 0, 10, 0], cwd=tree.root).header['err'] == 'notfile'
    done = run('read', [tree.root, 'src/a.py', 3, 3, 0], cwd=tree.root)
    assert done.data == b' 1\r' and done.header['fsha'] == sha(b'x = 1\r\n') and done.header['size'] == 7 == done.header['fsize']
    assert run('read', [tree.root, 'src/a.py', 0, 0, 0], cwd=tree.root).data == b''         # LEN=0: identity only


@pytest.mark.parametrize('rel,errno', [('link.txt', 40), ('linkdir/new.txt', 20)])
def test_write_never_goes_through_a_link_and_leaves_the_outside_untouched(tree, rel, errno):
    done = write(tree.root, rel, b'PWN', '*', cwd=tree.root)
    assert done.header['ok'] == 0 and done.header['errno'] == errno
    assert sorted(p.name for p in tree.outside.iterdir()) == ['secret.txt'] and (tree.outside / 'secret.txt').read_text() == 'TOP SECRET'


def test_ls_records_a_final_symlink_without_following_it_and_refuses_one_in_the_path(tree):
    for rel, kind in (('link.txt', 'l'), ('linkdir', 'l'), ('inlink.py', 'l')):
        records = ls(tree.root, rel, cwd=tree.root).records
        assert len(records) == 1 and records[0][0] == kind and records[0][5], records
    assert ls(tree.root, 'linkdir/secret.txt', cwd=tree.root).header['ok'] == 0


def test_rm_tree_removes_a_link_below_it_and_never_what_it_points_to_and_refuses_a_link_as_the_target(tree, tmp_path):
    scratch = tmp_path / 'scratch'
    (scratch / '.ctx-run-aaa' / 'sub').mkdir(parents=True)
    (scratch / '.ctx-run-aaa' / 'sub' / 'f').write_text('1')
    (scratch / '.ctx-run-aaa' / 'lnk').symlink_to(tree.outside)
    assert run('rm', [scratch, '.ctx-run-aaa', 't', '*'], cwd=tree.root).header['removed'] == 1
    assert not (scratch / '.ctx-run-aaa').exists() and (tree.outside / 'secret.txt').exists()
    assert run('rm', [tree.root, 'linkdir', 't', '*'], cwd=tree.root).header['ok'] == 0
    assert (tree.outside / 'secret.txt').exists()
    (tree.root / 'top.txt').write_text('t')
    assert run('rm', [tree.root, 'top.txt', 'f', sha(b'wrong')], cwd=tree.root).header['err'] == 'stale' and (tree.root / 'top.txt').exists()
    assert run('rm', [tree.root, 'top.txt', 'f', sha(b't')], cwd=tree.root).header['ok'] == 1 and not (tree.root / 'top.txt').exists()


def test_search_reads_only_the_files_cria_named_and_reports_a_refused_one(tree):
    (tree.root / 'a.py').write_text('def foo():\n    return 12\n# TODO fix 99\n')
    done = run('search', [tree.root, r'TODO|\d{2}$', 0, 100, 1 << 20], text='["a.py","link.txt","missing.py"]', cwd=tree.root)
    assert done.records == [['m', 'a.py', 2, '    return 12'], ['m', 'a.py', 3, '# TODO fix 99'], ['!', 'link.txt', 40], ['!', 'missing.py', 2]]
