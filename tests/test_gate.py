import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'reuse-gate'
gate = SimpleNamespace(**runpy.run_path(str(MODULE)))
GLOBALS = gate.hook.__globals__
ID = 'a' * 32


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('REUSE_GATE', raising=False)
    return tmp_path


def payload(project, name='tools/new.py', tool='Write'):
    return {'cwd': str(project), 'tool_name': tool, 'tool_input': {
        'notebook_path' if tool == 'NotebookEdit' else 'file_path': name}}


def record(project, **changes):
    value = {'version': 1, 'created_at': time.time(), 'keywords': 'small tool',
             'candidates': [{'fullName': 'org/tool'}], 'decision': 'adopt',
             'reason': 'MIT and maintained; fits the task'}
    value.update(changes)
    gate.save(project / '.reuse-gate/records' / (ID + '.json'), value)
    return value


def test_deny_json_contract(project):
    result = subprocess.run([sys.executable, str(MODULE), 'hook'],
                            input=json.dumps(payload(project)), capture_output=True, text=True)
    assert result.returncode == 0
    output = json.loads(result.stdout)['hookSpecificOutput']
    assert output == {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                      'permissionDecisionReason': gate.DENY}


def test_allow_after_record(project):
    record(project)
    assert gate.hook(payload(project)) is None


def test_undecided_does_not_clear(project):
    record(project, decision=None)
    assert gate.hook(payload(project)) == gate.DENY


@pytest.mark.parametrize('name', ['tests/test_new.py', 'src/__tests__/new.ts', 'docs/new.py',
    'notes.md', 'scripts/readme.md', 'scripts/options.json', 'tools/a.yaml', 'a.toml',
    'config.ini', '.env.local', 'vite.config.ts', 'src/test_thing.py', 'src/foo.spec.ts',
    'src/foo.test.js', 'conftest.py', 'Dockerfile', 'Makefile', 'image.png'])
def test_exemptions(project, name):
    assert gate.hook(payload(project, name)) is None


@pytest.mark.parametrize('name', ['main.py', 'main.js', 'main.ts', 'main.sh', 'main.gd',
    'main.lua', 'scripts/runner', 'tools/runner', 'bin/runner', 'addons/runner'])
def test_new_code_and_tool_paths(project, name):
    assert gate.hook(payload(project, name)) == gate.DENY


@pytest.mark.parametrize('tool,name', [('Write', 'main.py'), ('MultiEdit', 'main.py'),
                                      ('NotebookEdit', 'new.ipynb')])
def test_existing_and_new(project, tool, name):
    assert gate.hook(payload(project, name, tool)) == gate.DENY
    (project / name).write_text('existing')
    assert gate.hook(payload(project, name, tool)) is None


def test_absolute_path_and_nested_cwd(project):
    nested = project / 'src'
    nested.mkdir()
    data = payload(nested, str(project / 'scripts/a.py'))
    record(project)
    assert gate.hook(data) is None


def test_custom_glob(project):
    gate.save(project / '.reuse-gate/config.json', {'exempt_globs': ['generated/*']})
    assert gate.hook(payload(project, 'generated/a.py')) is None
    assert gate.hook(payload(project, 'src/a.py')) == gate.DENY


def test_ttl_and_future(project):
    gate.save(project / '.reuse-gate/config.json', {'ttl_seconds': 10})
    record(project, created_at=time.time() - 11)
    assert gate.hook(payload(project)) == gate.DENY
    record(project, created_at=time.time() - 5)
    assert gate.hook(payload(project)) is None
    record(project, created_at=time.time() + 10)
    assert gate.hook(payload(project)) == gate.DENY


def test_escape_logs_every_call(project, monkeypatch):
    monkeypatch.setenv('REUSE_GATE', 'off')
    for _ in range(2):
        assert gate.hook(payload(project)) is None
    logs = (project / '.reuse-gate/bypass.jsonl').read_text().splitlines()
    assert len(logs) == 2
    assert all(json.loads(line)['event'] == 'bypass' for line in logs)


def test_corrupt_records_ignored(project):
    record(project)
    (project / '.reuse-gate/records' / (ID + '.json')).write_text('{')
    assert gate.hook(payload(project)) == gate.DENY


@pytest.mark.parametrize('reason,valid', [('org/tool: incompatible language', True),
    ('does not fit', False), ('org/tool:', False), ('org/tool: fine\nmore', False)])
def test_build_requires_named_reason(project, reason, valid):
    value = record(project, decision='build', reason=reason)
    assert gate.check_record(value, 86400) == valid


def test_build_requires_top_three(project):
    value = record(project, decision='build', candidates=[{'fullName': f'org/tool{i}'} for i in range(4)],
                   reason='org/tool0: wrong language; org/tool1: unmaintained; org/tool2: no licence')
    assert gate.check_record(value, 86400)
    value['reason'] = 'org/tool0: wrong language'
    assert not gate.check_record(value, 86400)


def test_zero_candidates(project):
    value = record(project, candidates=[], decision='build', reason='No candidates: task needs a custom adapter')
    assert gate.check_record(value, 86400)
    value['reason'] = 'No candidates:'
    assert not gate.check_record(value, 86400)


def test_search_and_decide(project, capsys):
    candidates = [{'fullName': 'org/tool', 'license': {'key': 'mit'}, 'pushedAt': '2026-10-28',
                   'stargazersCount': 10, 'description': 'candidate'}]
    with patch.dict(GLOBALS, {}), patch('subprocess.run') as run:
        run.return_value = SimpleNamespace(stdout=json.dumps(candidates))
        assert gate.main(['search', 'small tool']) == 0
        assert run.call_args.args[0] == ['gh', 'search', 'repos', 'small tool', '--sort', 'stars',
            '--limit', '10', '--json', 'fullName,stargazersCount,license,pushedAt,description']
    output = json.loads(capsys.readouterr().out)
    assert output['candidates'] == candidates
    assert gate.hook(payload(project)) == gate.DENY
    assert gate.main(['decide', output['record'], 'build', 'org/tool: wrong runtime']) == 0
    assert gate.hook(payload(project)) is None


def test_failed_search_saves_nothing(project):
    with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, ['gh'])):
        assert gate.main(['search', 'small tool']) == 1
    assert not (project / '.reuse-gate/records').exists()


def test_decide_rejects_traversal(project):
    assert gate.main(['decide', '../elsewhere', 'adopt', 'fits']) == 1


def test_invalid_hook_fails_closed(project, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{}'))
    assert gate.main(['hook']) == 0  # unrelated/missing tool is a no-op
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{'))
    assert gate.main(['hook']) == 0
    assert json.loads(capsys.readouterr().out)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_bad_config_fails_closed(project, monkeypatch, capsys):
    gate.save(project / '.reuse-gate/config.json', {'ttl_seconds': -1})
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload(project))))
    assert gate.main(['hook']) == 0
    assert json.loads(capsys.readouterr().out)['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_allow_leaves_permissions_untouched(project):
    result = subprocess.run([sys.executable, str(MODULE), 'hook'],
        input=json.dumps(payload(project, 'README.md')), capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == ''
