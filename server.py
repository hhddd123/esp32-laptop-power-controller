#!/usr/bin/env python3
import json
import os
import time
import secrets
from http import cookies
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
from html import escape as html_escape

ESP_TOKEN = os.environ.get("ESP32_POWER_TOKEN", "")
WEB_TOKEN = os.environ.get("ESP32_POWER_WEB_TOKEN", "")
HOST = os.environ.get("ESP32_POWER_HOST", "0.0.0.0")
PORT = int(os.environ.get("ESP32_POWER_PORT", "8080"))
DEVICE_ALLOWLIST = set(filter(None, os.environ.get("ESP32_POWER_DEVICES", "laptop").split(",")))
COMMAND_TTL_SECONDS = int(os.environ.get("ESP32_POWER_COMMAND_TTL", "45"))
PRESS_COOLDOWN_SECONDS = int(os.environ.get("ESP32_POWER_PRESS_COOLDOWN", "10"))
COOKIE_NAME = "esp32_power_auth"

# 单请求窗口：每个 device 同时最多只允许一个未执行/未过期请求；新点击不会覆盖旧请求。
pending = {}
counter = 0
last_press_at = {}
failed_auth = {}


def now():
    return time.time()


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def safe_compare(a, b):
    return bool(a) and bool(b) and secrets.compare_digest(a, b)


def valid_device(device):
    if device not in DEVICE_ALLOWLIST:
        return False
    if not (1 <= len(device) <= 32):
        return False
    return all(ch.isalnum() or ch in "_-" for ch in device)


class Handler(BaseHTTPRequestHandler):
    server_version = "ESP32PowerControl/secure"

    def log_message(self, fmt, *args):
        # 脱敏日志：不记录 query string、Authorization、Cookie、body，避免 token 进入 journalctl。
        path = urlparse(getattr(self, "path", "")).path or "-"
        print("%s - - [%s] %s %s" % (self.client_address[0], self.log_date_time_string(), self.command, path), flush=True)

    def common_headers(self, content_type, extra=None):
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if content_type.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)

    def send_text(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.common_headers("text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, obj):
        data = to_json(obj)
        self.send_response(code)
        self.common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, code, html, extra=None):
        data = html.encode("utf-8")
        self.send_response(code)
        self.common_headers("text/html; charset=utf-8", extra=extra)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, set_cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def client_ip(self):
        return self.client_address[0]

    def rate_limit_auth_failure(self):
        ip = self.client_ip()
        t = now()
        bucket = [x for x in failed_auth.get(ip, []) if t - x < 60]
        bucket.append(t)
        failed_auth[ip] = bucket
        return len(bucket) <= 8

    def esp_auth_ok(self):
        auth = self.headers.get("Authorization", "")
        return safe_compare(auth, "Bearer " + ESP_TOKEN)

    def web_auth_ok(self, qs=None):
        # 便捷方案：首次 GET /press?token=<WEB_TOKEN> 只种 HttpOnly cookie 并重定向去掉 URL token；之后只点按钮。
        raw_cookie = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw_cookie)
        except cookies.CookieError:
            pass
        morsel = jar.get(COOKIE_NAME)
        if morsel and safe_compare(morsel.value, WEB_TOKEN):
            return True
        return False

    def make_auth_cookie(self):
        c = cookies.SimpleCookie()
        c[COOKIE_NAME] = WEB_TOKEN
        c[COOKIE_NAME]["path"] = "/"
        c[COOKIE_NAME]["httponly"] = True
        c[COOKIE_NAME]["samesite"] = "Strict"
        c[COOKIE_NAME]["max-age"] = 60 * 60 * 24 * 30
        return c.output(header="").strip()

    def parse_body_qs(self, max_len=4096):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > max_len:
            return None
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        return parse_qs(body)

    def press_page(self, device="laptop", message=""):
        if not valid_device(device):
            device = "laptop"
        msg = ""
        if message:
            msg = '<p class="msg">%s</p>' % html_escape(message)
        page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ESP32 电源控制</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:720px;margin:40px auto;padding:0 18px;line-height:1.6;background:#111;color:#eee}
    .card{border:1px solid #333;border-radius:14px;padding:22px;background:#1b1b1b}
    .warn{color:#ffcc66;font-weight:700}.ok{color:#8f8}.msg{color:#9cf}
    button{font-size:22px;padding:16px 28px;border:0;border-radius:12px;background:#d33;color:white;cursor:pointer}
    button:hover{background:#b22} code{background:#272727;padding:2px 6px;border-radius:6px}
  </style>
</head>
<body>
  <div class="card">
    <h1>ESP32 电源控制</h1>
    <p class="warn">安全模式：打开页面不会触发坨机；只有点击按钮才会创建一个待执行请求。</p>
    %s
    <p>目标设备：<code>%s</code></p>
    <form method="POST" action="/press" autocomplete="off">
      <input type="hidden" name="device" value="%s">
      <input type="hidden" name="confirm" value="press">
      <button type="submit">启动坨机 / 按一次电源键</button>
    </form>
    <p>提示：首次使用可打开一次带 token 的登录链接；服务器会立刻重定向去掉 URL token，并用 HttpOnly Cookie 记住登录。</p>
  </div>
</body>
</html>""" % (msg, html_escape(device), html_escape(device))
        self.send_html(200, page)

    def login_page(self):
        page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ESP32 登录</title><style>body{font-family:system-ui;max-width:620px;margin:40px auto;padding:0 18px;background:#111;color:#eee;line-height:1.6}.card{border:1px solid #333;border-radius:14px;padding:22px;background:#1b1b1b}input{font-size:18px;padding:12px;width:90%%}button{font-size:18px;padding:12px 20px;margin-top:12px}</style></head><body><div class="card"><h1>ESP32 电源控制登录</h1><p>请输入 Web Token。不会放进 URL。</p><form method="POST" action="/login" autocomplete="off"><input name="token" type="password" autofocus><br><button type="submit">登录</button></form></div></body></html>"""
        self.send_html(200, page)

    def queue_press(self, qs):
        global counter
        if not self.web_auth_ok():
            self.rate_limit_auth_failure()
            self.send_text(401, "unauthorized")
            return
        if qs.get("confirm", [""])[0] != "press":
            self.send_json(400, {"ok": False, "error": "missing explicit confirm=press"})
            return
        device = qs.get("device", ["laptop"])[0]
        if not valid_device(device):
            self.send_json(400, {"ok": False, "error": "invalid device"})
            return
        t = now()
        if t - last_press_at.get(device, 0) < PRESS_COOLDOWN_SECONDS:
            self.send_json(429, {"ok": False, "error": "cooldown"})
            return
        existing = pending.get(device)
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

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            self.send_text(200, "ESP32 power control service OK. Open /press for web control.\n")
            return

        if parsed.path == "/esp32/command":
            if not self.esp_auth_ok():
                self.rate_limit_auth_failure()
                self.send_text(401, "unauthorized")
                return
            device = qs.get("device", ["laptop"])[0]
            if not valid_device(device):
                self.send_text(400, "invalid device")
                return
            cmd = pending.pop(device, None)
            if cmd is None:
                self.send_text(200, "noop")
            elif cmd.get("expires_at", 0) < now():
                self.send_text(200, "noop")
            else:
                safe_cmd = {"id": cmd["id"], "command": cmd["command"]}
                self.send_json(200, safe_cmd)
            return

        if parsed.path == "/press":
            # 便捷登录：GET 带 token 只设置 cookie 并重定向，不触发、不排队、不把 token 留在页面/表单里。
            token = qs.get("token", [""])[0]
            device = qs.get("device", ["laptop"])[0]
            if token:
                if safe_compare(token, WEB_TOKEN):
                    loc = "/press?" + urlencode({"device": device})
                    self.redirect(loc, set_cookie=self.make_auth_cookie())
                else:
                    self.rate_limit_auth_failure()
                    self.send_text(401, "unauthorized")
                return
            if not self.web_auth_ok():
                self.login_page()
                return
            self.press_page(device=device)
            return

        if parsed.path == "/status":
            if not self.web_auth_ok():
                self.send_text(401, "unauthorized")
                return
            self.send_json(200, {"ok": True, "mode": "single-slot", "pending_devices": list(pending.keys()), "counter": counter})
            return

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_text(404, "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = self.parse_body_qs()
        if qs is None:
            self.send_text(413, "request too large")
            return

        if parsed.path == "/login":
            token = qs.get("token", [""])[0]
            if safe_compare(token, WEB_TOKEN):
                self.redirect("/press", set_cookie=self.make_auth_cookie())
            else:
                self.rate_limit_auth_failure()
                self.send_text(401, "unauthorized")
            return

        if parsed.path == "/press":
            self.queue_press(qs)
            return

        if parsed.path == "/clear":
            if not self.web_auth_ok():
                self.send_text(401, "unauthorized")
                return
            device = qs.get("device", ["laptop"])[0]
            if not valid_device(device):
                self.send_json(400, {"ok": False, "error": "invalid device"})
                return
            existed = device in pending
            pending.pop(device, None)
            self.send_json(200, {"ok": True, "device": device, "cleared": existed})
            return

        self.send_text(404, "not found")

    def do_HEAD(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    if not ESP_TOKEN:
        raise SystemExit("ESP32_POWER_TOKEN is required")
    if not WEB_TOKEN:
        raise SystemExit("ESP32_POWER_WEB_TOKEN is required")
    print("ESP32 power control service listening on %s:%d" % (HOST, PORT), flush=True)
    HTTPServer((HOST, PORT), Handler).serve_forever()
