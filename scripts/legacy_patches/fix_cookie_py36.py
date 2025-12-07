from pathlib import Path
p = Path('/opt/esp32-power-control/server.py')
s = p.read_text(encoding='utf-8')
backup = p.with_suffix('.py.bak-cookie-py36')
backup.write_text(s, encoding='utf-8')
old = '''    def make_auth_cookie(self):
        c = cookies.SimpleCookie()
        c[COOKIE_NAME] = WEB_TOKEN
        c[COOKIE_NAME]["path"] = "/"
        c[COOKIE_NAME]["httponly"] = True
        c[COOKIE_NAME]["samesite"] = "Strict"
        c[COOKIE_NAME]["max-age"] = 60 * 60 * 24 * 30
        return c.output(header="").strip()
'''
new = '''    def make_auth_cookie(self):
        # Python 3.6 SimpleCookie 不支持 samesite 属性，手动拼 SameSite，避免请求直接断开。
        c = cookies.SimpleCookie()
        c[COOKIE_NAME] = WEB_TOKEN
        c[COOKIE_NAME]["path"] = "/"
        c[COOKIE_NAME]["httponly"] = True
        c[COOKIE_NAME]["max-age"] = 60 * 60 * 24 * 30
        base = c.output(header="").strip()
        return base + "; SameSite=Strict"
'''
if old not in s:
    raise SystemExit('target block not found')
p.write_text(s.replace(old, new), encoding='utf-8')
print('patched cookie py36')
print('backup', backup)
