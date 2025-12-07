#pragma once

// 出厂默认值。运行后可在 Web 配置页修改，配置会保存到 NVS。

#define DEFAULT_DEVICE_NAME "laptop-power-esp32"
#define DEFAULT_AP_SSID "LaptopPower-Setup"
#define DEFAULT_AP_PASSWORD "configure123"  // 至少 8 位；首次配网后请在配置页修改

// Web 管理口令。用户名固定 admin，密码可在配置页修改。
#define DEFAULT_ADMIN_PASSWORD "admin123456"

// 执行器类型：relay 或 servo。
// 当前硬件方向：坨机 = 机械按压，因此默认使用 servo 模式。
#define DEFAULT_ACTUATOR_TYPE "servo"

// 继电器/光耦短接笔记本电源键：保留为备用方案，默认不启用。
#define DEFAULT_RELAY_PIN 26
#define DEFAULT_RELAY_ACTIVE_HIGH true
#define DEFAULT_RELAY_PULSE_MS 700

// 舵机机械按压笔记本电源键。
// 需要根据实际机械结构在 Web 配置页微调角度，避免长期顶住电源键。
// 默认待机 30°，按压 125°，平滑转动并保持 900ms 后回弹。
#define DEFAULT_SERVO_PIN 17
#define DEFAULT_SERVO_IDLE_ANGLE 30
#define DEFAULT_SERVO_PRESS_ANGLE 125
#define DEFAULT_SERVO_PULSE_MS 900

#define SERVO_STEP_DELAY_MS 12

#define HTTP_PORT 80

// 服务器主动控制默认值。清空 NVS 后会自动启用这些默认配置。可在配网 Web 页面修改。
#define DEFAULT_REMOTE_ENABLED true
#define DEFAULT_REMOTE_URL "http://your-server-ip:8080/esp32/command?device=laptop"
#define DEFAULT_REMOTE_TOKEN "YOUR_STRONG_RANDOM_SECRET_TOKEN"
#define DEFAULT_REMOTE_POLL_MS 3000
