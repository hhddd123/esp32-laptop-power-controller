import ast
from pathlib import Path

src = Path('/opt/esp32-power-control/server.py').read_text(encoding='utf-8')
ast.parse(src)

required = [
    ('GET /press comment', 'GET /press 只显示确认页面，不再排队/触发坨机。'),
    ('GET /press renders page', 'self.press_confirm_page(qs)'),
    ('POST explicit confirm gate', 'qs.get("confirm", [""])[0] != "press"'),
    ('POST missing-confirm rejects', 'missing explicit confirm=press'),
    ('queue function exists', 'def queue_press(self, qs):'),
]
for name, needle in required:
    ok = needle in src
    print(f'{name}: {ok}')
    if not ok:
        raise SystemExit(2)

marker = 'if parsed.path == "/press":\n            # 安全改动：GET /press 只显示确认页面，不再排队/触发坨机。'
idx = src.index(marker)
block = src[idx:src.index('\n        if parsed.path == "/clear":', idx)]
for forbidden in ['pending[', 'counter +=', 'queue_press', 'command": "press']:
    ok = forbidden not in block
    print(f'GET /press has no {forbidden!r}: {ok}')
    if not ok:
        raise SystemExit(3)
print('offline safety verification passed; no HTTP control endpoint was requested')
