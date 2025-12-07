# ESP32 主动连接服务器控制

这个方案不需要 frp，也不需要 ESP32 暴露在公网。ESP32 连上家里 WiFi 后，会定时主动访问你的服务器命令接口；服务器返回按键命令时，ESP32 就执行一次坨机/SG90 按电源键动作。

## 工作模式

```text
手机/网页/机器人 -> 你的服务器
                       ↑
ESP32 每隔几秒 GET 命令接口
                       ↓
服务器返回 press 命令 -> ESP32 按一下电源键
```

ESP32 不是被公网访问，而是主动连出去，因此能穿过大多数家庭 NAT。

## ESP32 配置

连接 ESP32 热点：

```text
WiFi: LaptopPower-Setup
密码: configure123
网页: http://192.168.4.1/
登录: admin / admin123456
```

进入“配置 WiFi / 执行器”，设置：

```text
家庭 WiFi SSID/密码
执行器：舵机机械按压
舵机 GPIO：17
待机角度：30
按下角度：120
```

然后在“服务器主动控制 / 轮询”里设置：

```text
启用：勾选
服务器命令 URL：http://你的服务器:端口/esp32/command?device=laptop
服务器 Token：自定义强 token
轮询间隔毫秒：3000
```

保存后 ESP32 会重启并连接家庭 WiFi。连上后会每隔 3 秒访问一次命令 URL。

## 服务器返回协议

没有命令时，服务器返回任意一种：

```text
noop
none
{}
```

有命令时，返回 JSON：

```json
{"id":"cmd-001","command":"press"}
```

字段说明：

- `command`: 包含 `press` 或 `power` 就会触发一次按键。
- `id`: 命令 ID。ESP32 会记住最后执行过的 ID，避免同一个命令重复执行。

如果你每次都希望执行，必须换新的 id。

## HTTP 鉴权

如果配置了 Token，ESP32 请求服务器时会带：

```http
Authorization: Bearer 你的token
X-Device-Name: laptop-power-esp32
```

服务器应该校验 Authorization，避免别人伪造命令。

## Python Flask 示例

```python
from flask import Flask, request, jsonify

app = Flask(__name__)
TOKEN = "CHANGE_ME_LONG_RANDOM_TOKEN"
pending = None
counter = 0

@app.get("/esp32/command")
def command():
    global pending
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {TOKEN}":
        return "unauthorized", 401
    if pending is None:
        return "noop"
    cmd = pending
    pending = None
    return jsonify(cmd)

@app.post("/press")
def press():
    global pending, counter
    counter += 1
    pending = {"id": f"cmd-{counter}", "command": "press"}
    return jsonify({"ok": True, "queued": pending})

app.run(host="0.0.0.0", port=8080)
```

启动：

```bash
pip install flask
python server.py
```

手机或其它地方触发：

```bash
curl -X POST http://你的服务器:8080/press
```

ESP32 下一次轮询 `/esp32/command` 时就会收到命令并按一下电源键。

## 安全建议

- Token 必须使用长随机字符串。
- 服务器的 `/press` 接口也要加鉴权，不要裸露给公网。
- 更推荐把控制页面放在 HTTPS 后面，或者只允许 VPN/白名单 IP 访问。
- 远程电源控制是高风险动作，后续可加二次确认、命令过期时间、日志审计。
