"""Portable assets and per-Windows-user state; never use the working folder."""
import os
from pathlib import Path
import sys

ASSETS = Path(__file__).resolve().parent / 'assets'


def data_dir():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        base = str(Path.home() / 'AppData' / 'Local')
    result = Path(base) / 'LumaPocketInstaller'
    result.mkdir(parents=True, exist_ok=True)
    return result


def worker_command(*args):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--worker', *args]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / 'launcher.py'), '--worker', *args]


def private_environment():
    env = os.environ.copy()
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_HOST', 'GH_DEBUG', 'GH_FORCE_TTY'):
        env.pop(key, None)
    tools = data_dir() / 'tools'
    env['PATH'] = os.pathsep.join((str(tools / 'gh' / 'bin'), str(tools / 'git' / 'usr' / 'bin'),
                                   str(tools / 'git' / 'cmd'), env.get('PATH', '')))
    env.update(GH_CONFIG_DIR=str(data_dir() / 'gh-empty'), GODEBUG='http2client=0',
               PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', GH_NO_UPDATE_NOTIFIER='1',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(data_dir() / 'git-empty-config'))
    return env
