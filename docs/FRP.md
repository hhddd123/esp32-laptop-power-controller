# frp 内网穿透方案

目标：ESP32 在内网提供 HTTP 服务，但外网通过你的服务器访问。

关键点：标准 ESP32 通常不能直接运行 frpc。frp 客户端应运行在同一个内网里的旁路设备上，例如：

- OpenWrt 路由器
- NAS
- 树莓派
- 一台常开的内网小主机
- 其它 Linux/Windows 设备

该设备能访问 ESP32 的局域网 IP，然后通过 frpc 把服务器端口转发到 ESP32。

## 网络结构

```text
手机/外网浏览器
   |
   v
公网服务器 frps
   |
   v
内网旁路设备 frpc
   |
   v
ESP32 Web 服务 http://ESP32_IP:80
```

## frps 服务端示例

服务器 `/etc/frp/frps.toml` 示例：

```toml
bindPort = 7000

auth.method = "token"
auth.token = "CHANGE_ME_STRONG_TOKEN"

# 如果用 vhost HTTP 反代，可启用：
vhostHTTPPort = 8080
```

启动方式取决于你的服务器安装方式。建议用 systemd 管理 frps。

## frpc 客户端：TCP 端口转发示例

内网设备 `/etc/frp/frpc.toml`：

```toml
serverAddr = "你的服务器IP或域名"
serverPort = 7000

auth.method = "token"
auth.token = "CHANGE_ME_STRONG_TOKEN"

[[proxies]]
name = "esp32-laptop-power"
type = "tcp"
localIP = "ESP32的内网IP"
localPort = 80
remotePort = 18080
```

访问：

```text
http://你的服务器IP:18080/
```

## frpc 客户端：HTTP 域名转发示例

如果服务器有域名并开启了 vhostHTTPPort：

```toml
serverAddr = "你的服务器IP或域名"
serverPort = 7000

auth.method = "token"
auth.token = "CHANGE_ME_STRONG_TOKEN"

[[proxies]]
name = "esp32-laptop-power-http"
type = "http"
localIP = "ESP32的内网IP"
localPort = 80
customDomains = ["power.example.com"]
```

访问：

```text
http://power.example.com:8080/
```

如果前面再接 Nginx/Caddy，建议由 Nginx/Caddy 提供 HTTPS 和额外鉴权。

## ESP32 IP 固定建议

为了 frpc 稳定转发，建议二选一：

1. 在路由器 DHCP 里给 ESP32 MAC 绑定固定 IP。
2. 后续在固件里增加静态 IP 配置。

当前固件会在串口输出 STA IP，也可尝试 mDNS：

```text
http://laptop-power-esp32.local/
```

但 frpc 配置里更建议写固定内网 IP。

## 安全建议

- 不要裸奔暴露默认密码。
- 修改 ESP32 Web 管理密码。
- 修改 frp token。
- 优先只把服务暴露给自己：服务器防火墙限制来源 IP，或套一层 VPN/反代 Basic Auth/HTTPS。
- 电源键接口属于高风险控制接口，避免放在公共互联网无保护访问。
