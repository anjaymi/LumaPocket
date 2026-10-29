"""Recognize pinned SideSign prompts without logging their contents."""
import re
import json


class PromptProtocol:
    _patterns = (
        ('structured', re.compile(r'LP_EVENT ([^\r\n]+)(?=[\r\n])')),
        ('phase', re.compile(r'Signing phase: ([a-z_]+)(?=[\r\n])')),
        ('udid', re.compile(r'iPhone / iPad UDID \(from Apple Devices/iTunes\):\s*')),
        ('account', re.compile(r'Apple Account email:\s*')),
        ('password', re.compile(r'Enter password for [^\s:@\r\n]+@[^\s:\r\n]+:\s*')),
        ('method', re.compile(r'Select option \[1-\d+\]:\s*')),
        ('retry', re.compile(r"Press \[Enter\] to retry code entry, or 'c' to cancel:\s*")),
        ('device_code', re.compile(r'Enter 6-digit verification code from your Apple device [^\r\n]*:\s*')),
        ('sms_code', re.compile(r'Enter 6-digit code sent via SMS to [^\r\n]*:\s*')),
        ('voice_code', re.compile(r'Enter 6-digit code from voice call to [^\r\n]*:\s*')),
        ('authorized', re.compile(r'Authorized state saved locally with encryption\.')),
        ('cloud', re.compile(r'Waiting for the first verified cloud signature before enabling daily checks\.\.\.')),
        ('enabled', re.compile(r'Daily expiry checks enabled')),
        ('preparing_device', re.compile(r'Preparing isolated V3 device authentication\.\.\.')),
        ('websocket_unsupported', re.compile(r'WebSockets not supported by libcurl')),
        ('apple_root_untrusted', re.compile(r'schannel:\s*SEC_E_UNTRUSTED_ROOT')),
        ('error', re.compile(r'Signing helper stopped:\s*([a-z0-9_]+)(?=[\r\n])')),
    )

    def __init__(self):
        self._buffer = ''

    def feed(self, text):
        self._buffer += text
        events = []
        while True:
            found = []
            for name, pattern in self._patterns:
                match = pattern.search(self._buffer)
                if match:
                    found.append((match.start(), name, match))
            if not found:
                self._buffer = self._buffer[-16384:]
                break
            _, name, match = min(found, key=lambda item: item[0])
            prefix = self._buffer[:match.start()]
            self._buffer = self._buffer[match.end():]
            detail = None
            if name == 'method':
                labels = {
                    'Apple Devices': 'Apple 受信任设备',
                    'Text Message (SMS)': '短信',
                    'Phone Call': '电话语音',
                }
                choices = re.findall(
                    r'\[(\d+)\]\s+(Apple Devices|Text Message \(SMS\)|Phone Call)',
                    prefix,
                )
                detail = [(number, labels[label]) for number, label in choices]
            elif name in ('error', 'phase'):
                detail = match.group(1)
            if name == 'structured':
                try:
                    event = json.loads(match.group(1))
                    events.append((event['name'], event.get('detail')))
                except (ValueError, KeyError, TypeError):
                    pass
            else:
                events.append((name, detail))
        return events
