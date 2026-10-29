"""Private pipes for worker prompts; raw authorization output is never logged."""
import codecs
import os
import subprocess
import threading

from .paths import data_dir, private_environment, worker_command
from .prompt_protocol import PromptProtocol
from .tooling import FLAGS


class Task:
    def __init__(self, emit):
        self.emit = emit
        self.process = None
        self.cancelled = False
        self.lock = threading.Lock()

    def start(self, action, *args, udid=None, account=None):
        self.action = action
        threading.Thread(target=self._run, args=(action, args, udid, account), daemon=True).start()

    def submit(self, value):
        if '\n' in value or '\r' in value:
            raise ValueError('single_line_input_required')
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError('worker_ended')
            self.process.stdin.write((value + '\n').encode('utf-8'))
            self.process.stdin.flush()

    def cancel(self):
        self.cancelled = True
        process = self.process
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=FLAGS)

    def _run(self, action, args, udid, account):
        try:
            if self.cancelled:
                self.emit('cancelled', action)
                return
            self.process = subprocess.Popen(worker_command(action, *args), cwd=data_dir(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0, env=private_environment(), creationflags=FLAGS)
            if self.cancelled:
                self.cancel()
            protocol = PromptProtocol()
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while chunk := os.read(self.process.stdout.fileno(), 4096):
                for name, detail in protocol.feed(decoder.decode(chunk)):
                    if name == 'udid' and udid is not None:
                        self.submit(udid)
                        udid = None
                    elif name == 'account' and account is not None:
                        self.submit(account)
                        account = None
                    elif name == 'retry':
                        self.submit('')
                        self.emit(name, None)
                    else:
                        self.emit(name, detail)
            code = self.process.wait()
            self.emit('cancelled' if self.cancelled else 'done', {'action': action, 'code': code})
        except (OSError, RuntimeError, ValueError):
            self.cancel()
            self.emit('error_code', 'worker_unavailable')
            self.emit('done', {'action': action, 'code': 1})
        finally:
            udid = account = None
            if self.process:
                for stream in (self.process.stdin, self.process.stdout):
                    if stream and not stream.closed:
                        stream.close()
