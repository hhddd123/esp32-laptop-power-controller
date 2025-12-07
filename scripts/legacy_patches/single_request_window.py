from pathlib import Path
p = Path('/opt/esp32-power-control/server.py')
s = p.read_text(encoding='utf-8')
backup = p.with_suffix('.py.bak-single-request-window')
backup.write_text(s, encoding='utf-8')

s = s.replace('# 单命令槽：每个 device 最多只保留一个待执行命令；新的确认点击会覆盖旧命令，不排队。', '# 单请求窗口：每个 device 同时最多只允许一个未执行/未过期请求；新点击不会覆盖旧请求。')
s = s.replace('安全模式：打开页面不会触发坨机；必须登录 Web Token，并在下面输入坨机 Token 后点击按钮，才会下发一次命令。', '安全模式：打开页面不会触发坨机；必须登录 Web Token，并在下面输入坨机 Token 后点击按钮，才会创建一个待执行请求。每个设备同时只能有一个请求窗口。')
s = s.replace('只有点击按钮才会下发一次命令。', '只有点击按钮才会创建一个待执行请求。')

old = '''        counter += 1
        cmd = {"id": "%s-%d" % (device, counter), "command": "press", "expires_at": t + COMMAND_TTL_SECONDS}
        pending[device] = cmd
        last_press_at[device] = t
        print("AUDIT press_queued ip=%s device=%s id=%s" % (self.client_ip(), device, cmd["id"]), flush=True)
        self.press_page(device=device, message="已排队一次按键命令。")
'''
new = '''        existing = pending.get(device)
        if existing is not None:
            if existing.get("expires_at", 0) >= t:
                self.send_json(409, {"ok": False, "error": "request already pending", "device": device})
                return
            pending.pop(device, None)
        counter += 1
        cmd = {"id": "%s-%d" % (device, counter), "command": "press", "expires_at": t + COMMAND_TTL_SECONDS}
        pending[device] = cmd
        last_press_at[device] = t
        print("AUDIT press_request_created ip=%s device=%s id=%s" % (self.client_ip(), device, cmd["id"]), flush=True)
        self.press_page(device=device, message="已创建一个待执行请求。ESP32 取走或 45 秒过期前，不会再创建第二个请求。")
'''
if old not in s:
    raise SystemExit('queue block not found')
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('patched single request window')
print('backup', backup)
