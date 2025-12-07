from pathlib import Path
p = Path('/opt/esp32-power-control/server.py')
s = p.read_text(encoding='utf-8')
backup = p.with_suffix('.py.bak-dual-token-press')
backup.write_text(s, encoding='utf-8')

old_form = '''    <form method=\"POST\" action=\"/press\" autocomplete=\"off\">
      <input type=\"hidden\" name=\"device\" value=\"%s\">
      <input type=\"hidden\" name=\"confirm\" value=\"press\">
      <button type=\"submit\">启动坨机 / 按一次电源键</button>
    </form>
'''
new_form = '''    <form method=\"POST\" action=\"/press\" autocomplete=\"off\">
      <input type=\"hidden\" name=\"device\" value=\"%s\">
      <label>坨机 Token（二次确认）</label><br>
      <input name=\"actuator_token\" type=\"password\" placeholder=\"输入和坨机/ESP32 一起规定的 token\" required style=\"font-size:18px;padding:12px;width:92%%;max-width:520px;margin:8px 0 14px;border-radius:8px;border:1px solid #444;background:#222;color:#eee\"><br>
      <input type=\"hidden\" name=\"confirm\" value=\"press\">
      <button type=\"submit\">启动坨机 / 按一次电源键</button>
    </form>
'''
if old_form not in s:
    raise SystemExit('form block not found')
s = s.replace(old_form, new_form, 1)

old_check = '''        if qs.get("confirm", [""])[0] != "press":
            self.send_json(400, {"ok": False, "error": "missing explicit confirm=press"})
            return
        device = qs.get("device", ["laptop"])[0]
'''
new_check = '''        if qs.get("confirm", [""])[0] != "press":
            self.send_json(400, {"ok": False, "error": "missing explicit confirm=press"})
            return
        actuator_token = qs.get("actuator_token", [""])[0]
        if not safe_compare(actuator_token, ESP_TOKEN):
            self.rate_limit_auth_failure()
            self.send_json(403, {"ok": False, "error": "bad actuator token"})
            return
        device = qs.get("device", ["laptop"])[0]
'''
if old_check not in s:
    raise SystemExit('confirm block not found')
s = s.replace(old_check, new_check, 1)

# Make user-facing text explicit.
s = s.replace('安全模式：打开页面不会触发坨机；只有点击按钮才会下发一次命令。', '安全模式：打开页面不会触发坨机；必须登录 Web Token，并在下面输入坨机 Token 后点击按钮，才会下发一次命令。')

p.write_text(s, encoding='utf-8')
print('patched dual-token press')
print('backup', backup)
