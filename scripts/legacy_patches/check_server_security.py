from pathlib import Path

src = Path('/opt/esp32-power-control/server.py').read_text(encoding='utf-8')
env = Path('/etc/esp32-power-control.env').read_text(encoding='utf-8')

def present(label, needle, expected=True):
    found = needle in src
    ok = (found == expected)
    print(f'{label}: {ok} (found={found}, expected={expected})')

print('---CODE_SECURITY_MARKERS---')
present('token required at startup', 'if not TOKEN:')
present('GET /press renders page only', 'self.press_confirm_page(qs)')
present('POST /press explicit confirm required', 'missing explicit confirm=press')
present('command single-slot enqueue exists', 'pending[device] = cmd')
present('ESP32 command pop-once exists', 'pending.pop(device, None)')
present('old POST delegates to GET removed', 'self.do_GET()', expected=False)
print('---ENV_NONSECRET---')
for line in env.splitlines():
    if line.startswith('ESP32_POWER_TOKEN='):
        value = line.split('=', 1)[1]
        print(f'ESP32_POWER_TOKEN=<redacted len={len(value)}>')
    elif line.startswith(('ESP32_POWER_HOST=', 'ESP32_POWER_PORT=')):
        print(line)
