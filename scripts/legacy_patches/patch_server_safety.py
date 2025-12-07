from pathlib import Path

p = Path('/opt/esp32-power-control/server.py')
s = p.read_text(encoding='utf-8')
backup = p.with_suffix('.py.bak-get-press-disabled')
backup.write_text(s, encoding='utf-8')

if 'from html import escape as html_escape' not in s:
    s = s.replace('from urllib.parse import urlparse, parse_qs\n', 'from urllib.parse import urlparse, parse_qs\nfrom html import escape as html_escape\n', 1)

start = s.index('    def do_GET(self):\n')
end = s.index('\nif __name__ == "__main__":', start)
new_block = r'''    def send_html(self, code, html):
        data = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def press_confirm_page(self, qs):
        device = qs.get("device", ["laptop"])[0]
        token = qs.get("token", [""])[0]
        token_input = ""
        if token:
            token_input = '<input type="hidden" name="token" value="%s">' % html_escape(token)
        page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ESP32 电源控制</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:720px;margin:40px auto;padding:0 18px;line-height:1.6;background:#111;color:#eee}
    .card{border:1px solid #333;border-radius:14px;padding:22px;background:#1b1b1b}
    .warn{color:#ffcc66;font-weight:700}
    button{font-size:22px;padding:16px 28px;border:0;border-radius:12px;background:#d33;color:white;cursor:pointer}
    button:hover{background:#b22}
    code{background:#272727;padding:2px 6px;border-radius:6px}
  </style>
</head>
<body>
  <div class="card">
    <h1>ESP32 电源控制</h1>
    <p class="warn">安全模式：打开这个页面不会触发舵机/坨机。</p>
    <p>只有点击下面按钮，提交 POST 确认后，服务器才会给设备 <code>%s</code> 下发一次 press 命令。</p>
    <form method="POST" action="/press">
      <input type="hidden" name="device" value="%s">
      %s
      <input type="hidden" name="confirm" value="press">
      <button type="submit">确认启动坨机 / 按电源键</button>
    </form>
  </div>
</body>
</html>""" % (html_escape(device), html_escape(device), token_input)
        self.send_html(200, page)

    def queue_press(self, qs):
        global counter
        if not self.token_ok(qs):
            self.send_text(401, "unauthorized")
            return
        if qs.get("confirm", [""])[0] != "press":
            self.send_json(400, {"ok": False, "error": "missing explicit confirm=press"})
            return
        device = qs.get("device", ["laptop"])[0]
        counter += 1
        cmd = {"id": "%s-%d" % (device, counter), "command": "press"}
        # 只保留一个命令：重复点击不会排队多个，只会覆盖成最新命令。
        pending[device] = cmd
        self.send_json(200, {"ok": True, "mode": "single-slot", "device": device, "queued": cmd})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_text(200, "ESP32 power control service OK. Open /press for the guarded web button.\n")
            return

        if parsed.path == "/esp32/command":
            if not self.token_ok(qs):
                self.send_text(401, "unauthorized")
                return
            device = qs.get("device", ["laptop"])[0]
            # 取出即删除，保证同一个命令只会被 ESP32 执行一次。
            cmd = pending.pop(device, None)
            if cmd is None:
                self.send_text(200, "noop")
            else:
                self.send_json(200, cmd)
            return

        if parsed.path == "/press":
            # 安全改动：GET /press 只显示确认页面，不再排队/触发坨机。
            if not self.token_ok(qs):
                self.send_text(401, "unauthorized")
                return
            self.press_confirm_page(qs)
            return

        if parsed.path == "/clear":
            if not self.token_ok(qs):
                self.send_text(401, "unauthorized")
                return
            device = qs.get("device", ["laptop"])[0]
            existed = device in pending
            pending.pop(device, None)
            self.send_json(200, {"ok": True, "device": device, "cleared": existed})
            return

        if parsed.path == "/status":
            if not self.token_ok(qs):
                self.send_text(401, "unauthorized")
                return
            self.send_json(200, {"ok": True, "mode": "single-slot", "pending": pending, "counter": counter})
            return

        self.send_text(404, "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            body_qs = parse_qs(body)
            for key, values in body_qs.items():
                qs.setdefault(key, []).extend(values)

        if parsed.path == "/press":
            self.queue_press(qs)
            return

        self.send_text(404, "not found")
'''
s = s[:start] + new_block + s[end:]
p.write_text(s, encoding='utf-8')
print('patched', p)
print('backup', backup)
