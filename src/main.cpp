#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <ESP32Servo.h>

#include "config.h"

struct AppConfig {
  String deviceName = DEFAULT_DEVICE_NAME;
  String wifiSsid;
  String wifiPassword;
  String apSsid = DEFAULT_AP_SSID;
  String apPassword = DEFAULT_AP_PASSWORD;
  String adminPassword = DEFAULT_ADMIN_PASSWORD;
  String actuatorType = DEFAULT_ACTUATOR_TYPE;
  int relayPin = DEFAULT_RELAY_PIN;
  bool relayActiveHigh = DEFAULT_RELAY_ACTIVE_HIGH;
  int relayPulseMs = DEFAULT_RELAY_PULSE_MS;
  int servoPin = DEFAULT_SERVO_PIN;
  int servoIdleAngle = DEFAULT_SERVO_IDLE_ANGLE;
  int servoPressAngle = DEFAULT_SERVO_PRESS_ANGLE;
  int servoPulseMs = DEFAULT_SERVO_PULSE_MS;
  bool remoteEnabled = DEFAULT_REMOTE_ENABLED;
  String remoteUrl = DEFAULT_REMOTE_URL;
  String remoteToken = DEFAULT_REMOTE_TOKEN;
  int remotePollMs = DEFAULT_REMOTE_POLL_MS;
};

Preferences prefs;
WebServer server(HTTP_PORT);
Servo powerServo;
AppConfig cfg;
bool servoAttached = false;
int servoCurrentAngle = DEFAULT_SERVO_IDLE_ANGLE;
unsigned long bootMillis = 0;
unsigned long lastRemotePollMs = 0;
String lastRemoteCommandId;
String lastRemoteStatus = "disabled";

static String htmlEscape(const String &s) {
  String out;
  out.reserve(s.length());
  for (char c : s) {
    switch (c) {
      case '&': out += F("&amp;"); break;
      case '<': out += F("&lt;"); break;
      case '>': out += F("&gt;"); break;
      case '"': out += F("&quot;"); break;
      case '\'': out += F("&#39;"); break;
      default: out += c; break;
    }
  }
  return out;
}

static bool isRelayMode() {
  String mode = cfg.actuatorType;
  mode.toLowerCase();
  return mode != "servo";
}

static int relayIdleLevel() {
  return cfg.relayActiveHigh ? LOW : HIGH;
}

static int relayActiveLevel() {
  return cfg.relayActiveHigh ? HIGH : LOW;
}

static bool requireAuth() {
  if (cfg.adminPassword.length() == 0) return true;
  if (server.authenticate("admin", cfg.adminPassword.c_str())) return true;
  server.requestAuthentication(BASIC_AUTH, "laptop-power", "需要登录：用户名 admin");
  return false;
}

static String argOrEmpty(const char *name) {
  return server.hasArg(name) ? server.arg(name) : String();
}

static void loadConfig() {
  prefs.begin("laptop-pwr", true);
  cfg.deviceName = prefs.getString("dev", DEFAULT_DEVICE_NAME);
  cfg.wifiSsid = prefs.getString("ssid", "");
  cfg.wifiPassword = prefs.getString("wpass", "");
  cfg.apSsid = prefs.getString("apssid", DEFAULT_AP_SSID);
  cfg.apPassword = prefs.getString("appass", DEFAULT_AP_PASSWORD);
  cfg.adminPassword = prefs.getString("admin", DEFAULT_ADMIN_PASSWORD);
  cfg.actuatorType = prefs.getString("act", DEFAULT_ACTUATOR_TYPE);
  cfg.relayPin = prefs.getInt("rpin", DEFAULT_RELAY_PIN);
  cfg.relayActiveHigh = prefs.getBool("rhigh", DEFAULT_RELAY_ACTIVE_HIGH);
  cfg.relayPulseMs = prefs.getInt("rms", DEFAULT_RELAY_PULSE_MS);
  cfg.servoPin = prefs.getInt("spin", DEFAULT_SERVO_PIN);
  cfg.servoIdleAngle = prefs.getInt("sidle", DEFAULT_SERVO_IDLE_ANGLE);
  cfg.servoPressAngle = prefs.getInt("spress", DEFAULT_SERVO_PRESS_ANGLE);
  cfg.servoPulseMs = prefs.getInt("sms", DEFAULT_SERVO_PULSE_MS);
  cfg.remoteEnabled = prefs.getBool("ren", DEFAULT_REMOTE_ENABLED);
  cfg.remoteUrl = prefs.getString("rurl", DEFAULT_REMOTE_URL);
  cfg.remoteToken = prefs.getString("rtok", DEFAULT_REMOTE_TOKEN);
  cfg.remotePollMs = prefs.getInt("rpoll", DEFAULT_REMOTE_POLL_MS);
  prefs.end();
}

static void saveConfig() {
  prefs.begin("laptop-pwr", false);
  prefs.putString("dev", cfg.deviceName);
  prefs.putString("ssid", cfg.wifiSsid);
  prefs.putString("wpass", cfg.wifiPassword);
  prefs.putString("apssid", cfg.apSsid);
  prefs.putString("appass", cfg.apPassword);
  prefs.putString("admin", cfg.adminPassword);
  prefs.putString("act", cfg.actuatorType);
  prefs.putInt("rpin", cfg.relayPin);
  prefs.putBool("rhigh", cfg.relayActiveHigh);
  prefs.putInt("rms", cfg.relayPulseMs);
  prefs.putInt("spin", cfg.servoPin);
  prefs.putInt("sidle", cfg.servoIdleAngle);
  prefs.putInt("spress", cfg.servoPressAngle);
  prefs.putInt("sms", cfg.servoPulseMs);
  prefs.putBool("ren", cfg.remoteEnabled);
  prefs.putString("rurl", cfg.remoteUrl);
  prefs.putString("rtok", cfg.remoteToken);
  prefs.putInt("rpoll", cfg.remotePollMs);
  prefs.end();
}

static void moveServoSmooth(int targetAngle, int stepDelayMs = 15) {
  if (!servoAttached) return;

  targetAngle = constrain(targetAngle, 0, 180);
  servoCurrentAngle = constrain(servoCurrentAngle, 0, 180);
  if (servoCurrentAngle == targetAngle) {
    powerServo.write(targetAngle);
    delay(80);
    return;
  }

  const int step = (targetAngle > servoCurrentAngle) ? 1 : -1;
  while (servoCurrentAngle != targetAngle) {
    servoCurrentAngle += step;
    powerServo.write(servoCurrentAngle);
    delay(stepDelayMs);
  }
  delay(120);  // 给舵机一点到位时间，避免刚写完角度就开始反向
}

static void releaseServoSignal() {
  if (servoAttached) {
    powerServo.detach();
    servoAttached = false;
  }
  // 舵机信号脚不能悬空；释放 PWM 后强制拉低，减少黄线接上后乱动。
  pinMode(cfg.servoPin, OUTPUT);
  digitalWrite(cfg.servoPin, LOW);
}

static void attachServoSignal() {
  // 先给一个确定低电平，避免 attach 前瞬间悬空。
  pinMode(cfg.servoPin, OUTPUT);
  digitalWrite(cfg.servoPin, LOW);
  delay(30);
  powerServo.setPeriodHertz(50);
  powerServo.attach(cfg.servoPin, 500, 2400);
  servoAttached = true;
}

static void setupActuator() {
  if (servoAttached) {
    powerServo.detach();
    servoAttached = false;
  }

  if (isRelayMode()) {
    pinMode(cfg.relayPin, OUTPUT);
    digitalWrite(cfg.relayPin, relayIdleLevel());
  } else {
    attachServoSignal();
    servoCurrentAngle = constrain(cfg.servoIdleAngle, 0, 180);
    powerServo.write(servoCurrentAngle);
    delay(700);  // 上电/重启后先确保回到待机位
    // 机械按压场景不需要持续保持力矩；释放 PWM 可减少舵机空闲抖动/乱动。
    releaseServoSignal();
  }
}

static void pressPowerButton() {
  if (isRelayMode()) {
    digitalWrite(cfg.relayPin, relayActiveLevel());
    delay(constrain(cfg.relayPulseMs, 100, 5000));
    digitalWrite(cfg.relayPin, relayIdleLevel());
  } else {
    if (!servoAttached) {
      attachServoSignal();
    }
    moveServoSmooth(cfg.servoPressAngle, SERVO_STEP_DELAY_MS);
    delay(constrain(cfg.servoPulseMs, 100, 5000));
    moveServoSmooth(cfg.servoIdleAngle, SERVO_STEP_DELAY_MS);


    servoCurrentAngle = constrain(cfg.servoIdleAngle, 0, 180);
    delay(700);
    // 到位后释放 PWM，并把信号脚保持为确定低电平，避免廉价舵机持续寻找位置导致乱抖。
    releaseServoSignal();
  }
}

static String wifiStatusText() {
  switch (WiFi.status()) {
    case WL_CONNECTED: return "connected";
    case WL_NO_SSID_AVAIL: return "no_ssid";
    case WL_CONNECT_FAILED: return "connect_failed";
    case WL_DISCONNECTED: return "disconnected";
    default: return String((int)WiFi.status());
  }
}

static String statusJson() {
  String ip = WiFi.isConnected() ? WiFi.localIP().toString() : String("");
  String json = "{";
  json += "\"device\":\"" + htmlEscape(cfg.deviceName) + "\",";
  json += "\"wifi\":\"" + wifiStatusText() + "\",";
  json += "\"sta_ip\":\"" + ip + "\",";
  json += "\"ap_ip\":\"" + WiFi.softAPIP().toString() + "\",";
  json += "\"actuator\":\"" + cfg.actuatorType + "\",";
  json += "\"remote_enabled\":" + String(cfg.remoteEnabled ? "true" : "false") + ",";
  json += "\"remote_status\":\"" + htmlEscape(lastRemoteStatus) + "\",";
  json += "\"last_remote_command_id\":\"" + htmlEscape(lastRemoteCommandId) + "\",";
  json += "\"uptime_ms\":" + String(millis() - bootMillis);
  json += "}";
  return json;
}

static String pageHeader(const String &title) {
  String h = F("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
               "<meta name='viewport' content='width=device-width,initial-scale=1'>");
  h += "<title>" + htmlEscape(title) + "</title>";
  h += F("<style>body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;background:#0f172a;color:#e5e7eb}"
         "a{color:#93c5fd}.card{background:#111827;border:1px solid #374151;border-radius:14px;padding:18px;margin:14px 0}"
         "button,.btn{background:#2563eb;color:white;border:0;border-radius:10px;padding:12px 18px;font-size:16px;text-decoration:none;display:inline-block;cursor:pointer}"
         ".danger{background:#dc2626}.muted{color:#9ca3af}input,select{width:100%;box-sizing:border-box;margin:6px 0 12px;padding:10px;border-radius:8px;border:1px solid #4b5563;background:#030712;color:#e5e7eb}label{font-weight:600}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:600px){.row{grid-template-columns:1fr}}</style></head><body>");
  h += "<h1>" + htmlEscape(cfg.deviceName) + "</h1>";
  return h;
}

static String pageFooter() {
  return F("<p class='muted'>ESP32 Laptop Power Controller</p></body></html>");
}

static void handleRoot() {
  if (!requireAuth()) return;
  String s = pageHeader("笔记本远程电源控制");
  s += F("<div class='card'><h2>电源键</h2>"
         "<p>点击后会短暂触发执行器，相当于按一下笔记本电源键。请确认接线安全。</p>"
         "<form method='post' action='/api/power/press' onsubmit='return confirm(\"确认触发笔记本电源键？\")'>"
         "<button class='danger' type='submit'>按一下电源键</button></form></div>");
  s += "<div class='card'><h2>状态</h2><pre>WiFi: " + wifiStatusText() + "\nSTA IP: " + (WiFi.isConnected() ? WiFi.localIP().toString() : String("未连接")) + "\nAP IP: " + WiFi.softAPIP().toString() + "\n执行器: " + cfg.actuatorType + "</pre></div>";
  s += F("<div class='card'><a class='btn' href='/config'>配置 WiFi / 执行器</a> <a href='/api/status'>JSON 状态</a></div>");
  s += pageFooter();
  server.send(200, "text/html; charset=utf-8", s);
}

static void handleConfig() {
  if (!requireAuth()) return;
  String s = pageHeader("配置");
  s += F("<form class='card' method='post' action='/config'>");
  s += "<label>设备名 / mDNS 主机名</label><input name='dev' value='" + htmlEscape(cfg.deviceName) + "'>";
  s += "<label>家庭/办公室 WiFi SSID</label><input name='ssid' value='" + htmlEscape(cfg.wifiSsid) + "'>";
  s += F("<label>WiFi 密码（留空表示不修改已有密码）</label><input name='wpass' type='password' placeholder='不修改则留空'>");
  s += "<label>配网 AP 名称</label><input name='apssid' value='" + htmlEscape(cfg.apSsid) + "'>";
  s += F("<label>配网 AP 密码（至少8位，留空不改）</label><input name='appass' type='password' placeholder='不修改则留空'>");
  s += F("<label>Web 管理密码：admin / 新密码（留空不改）</label><input name='admin' type='password' placeholder='不修改则留空'>");
  s += F("<label>执行器类型</label><select name='act'>");
  s += "<option value='relay'" + String(isRelayMode() ? " selected" : "") + ">继电器/光耦短接</option>";
  s += "<option value='servo'" + String(!isRelayMode() ? " selected" : "") + ">舵机机械按压</option></select>";
  s += F("<div class='row'><div><label>继电器 GPIO</label><input name='rpin' type='number' value='"); s += cfg.relayPin; s += F("'></div>");
  s += F("<div><label>继电器有效电平</label><select name='rhigh'>");
  s += "<option value='1'" + String(cfg.relayActiveHigh ? " selected" : "") + ">高电平有效</option>";
  s += "<option value='0'" + String(!cfg.relayActiveHigh ? " selected" : "") + ">低电平有效</option></select></div></div>";
  s += F("<label>继电器脉冲毫秒</label><input name='rms' type='number' min='100' max='5000' value='"); s += cfg.relayPulseMs; s += F("'>");
  s += F("<div class='row'><div><label>舵机 GPIO</label><input name='spin' type='number' value='"); s += cfg.servoPin; s += F("'></div>");
  s += F("<div><label>舵机脉冲毫秒</label><input name='sms' type='number' min='100' max='5000' value='"); s += cfg.servoPulseMs; s += F("'></div></div>");
  s += F("<div class='row'><div><label>舵机待机角度</label><input name='sidle' type='number' min='0' max='180' value='"); s += cfg.servoIdleAngle; s += F("'></div>");
  s += F("<div><label>舵机按下角度</label><input name='spress' type='number' min='0' max='180' value='"); s += cfg.servoPressAngle; s += F("'></div></div>");
  s += F("<hr><h2>服务器主动控制 / 轮询</h2>");
  s += F("<label><input style='width:auto' type='checkbox' name='ren' value='1'");
  if (cfg.remoteEnabled) s += F(" checked");
  s += F("> 启用：ESP32 定时连接服务器获取指令</label>");
  s += "<label>服务器命令 URL</label><input name='rurl' placeholder='http://server:8080/esp32/command?device=laptop' value='" + htmlEscape(cfg.remoteUrl) + "'>";
  s += F("<label>服务器 Token（Authorization: Bearer，留空不改）</label><input name='rtok' type='password' placeholder='不修改则留空'>");
  s += F("<label>轮询间隔毫秒</label><input name='rpoll' type='number' min='1000' max='60000' value='"); s += cfg.remotePollMs; s += F("'>");
  s += F("<button type='submit'>保存并重启</button> <a href='/'>返回</a></form>");
  s += pageFooter();
  server.send(200, "text/html; charset=utf-8", s);
}

static void handleSaveConfig() {
  if (!requireAuth()) return;
  cfg.deviceName = argOrEmpty("dev");
  cfg.wifiSsid = argOrEmpty("ssid");
  if (server.hasArg("wpass") && server.arg("wpass").length() > 0) cfg.wifiPassword = server.arg("wpass");
  cfg.apSsid = argOrEmpty("apssid");
  if (server.hasArg("appass") && server.arg("appass").length() >= 8) cfg.apPassword = server.arg("appass");
  if (server.hasArg("admin") && server.arg("admin").length() >= 8) cfg.adminPassword = server.arg("admin");
  cfg.actuatorType = argOrEmpty("act");
  cfg.relayPin = constrain(server.arg("rpin").toInt(), 0, 39);
  cfg.relayActiveHigh = server.arg("rhigh") == "1";
  cfg.relayPulseMs = constrain(server.arg("rms").toInt(), 100, 5000);
  cfg.servoPin = constrain(server.arg("spin").toInt(), 0, 39);
  cfg.servoIdleAngle = constrain(server.arg("sidle").toInt(), 0, 180);
  cfg.servoPressAngle = constrain(server.arg("spress").toInt(), 0, 180);
  cfg.servoPulseMs = constrain(server.arg("sms").toInt(), 100, 5000);
  cfg.remoteEnabled = server.hasArg("ren") && server.arg("ren") == "1";
  cfg.remoteUrl = argOrEmpty("rurl");
  if (server.hasArg("rtok") && server.arg("rtok").length() > 0) cfg.remoteToken = server.arg("rtok");
  cfg.remotePollMs = constrain(server.arg("rpoll").toInt(), 1000, 60000);
  saveConfig();
  server.send(200, "text/html; charset=utf-8", pageHeader("已保存") + "<div class='card'><p>配置已保存，设备即将重启。</p></div>" + pageFooter());
  delay(700);
  ESP.restart();
}

static void handlePowerPress() {
  if (!requireAuth()) return;
  pressPowerButton();
  if (server.method() == HTTP_POST) {
    server.sendHeader("Location", "/");
    server.send(303, "text/plain", "pressed");
  } else {
    server.send(200, "application/json", "{\"ok\":true}");
  }
}

static void handleStatus() {
  if (!requireAuth()) return;
  server.send(200, "application/json", statusJson());
}

static void handleResetConfig() {
  if (!requireAuth()) return;
  prefs.begin("laptop-pwr", false);
  prefs.clear();
  prefs.end();
  server.send(200, "text/plain; charset=utf-8", "配置已清空，正在重启");
  delay(500);
  ESP.restart();
}

static String extractJsonString(const String &body, const String &key) {
  String marker = "\"" + key + "\"";
  int k = body.indexOf(marker);
  if (k < 0) return "";
  int colon = body.indexOf(':', k + marker.length());
  if (colon < 0) return "";
  int q1 = body.indexOf('"', colon + 1);
  if (q1 < 0) return "";
  int q2 = body.indexOf('"', q1 + 1);
  if (q2 < 0) return "";
  return body.substring(q1 + 1, q2);
}

static void pollRemoteCommand() {
  if (!cfg.remoteEnabled) {
    lastRemoteStatus = "disabled";
    return;
  }
  if (!WiFi.isConnected()) {
    lastRemoteStatus = "wifi_not_connected";
    return;
  }
  if (cfg.remoteUrl.length() == 0) {
    lastRemoteStatus = "missing_url";
    return;
  }
  unsigned long now = millis();
  if (now - lastRemotePollMs < (unsigned long)constrain(cfg.remotePollMs, 1000, 60000)) return;
  lastRemotePollMs = now;

  HTTPClient http;
  http.setTimeout(5000);
  if (!http.begin(cfg.remoteUrl)) {
    lastRemoteStatus = "begin_failed";
    return;
  }
  if (cfg.remoteToken.length() > 0) {
    http.addHeader("Authorization", "Bearer " + cfg.remoteToken);
  }
  http.addHeader("X-Device-Name", cfg.deviceName);

  int code = http.GET();
  if (code <= 0) {
    lastRemoteStatus = "http_error_" + String(code);
    http.end();
    return;
  }
  String body = http.getString();
  body.trim();
  http.end();

  if (code != 200) {
    lastRemoteStatus = "http_status_" + String(code);
    return;
  }
  if (body.length() == 0 || body == "none" || body == "noop" || body == "{}") {
    lastRemoteStatus = "no_command";
    return;
  }

  String command = extractJsonString(body, "command");
  String commandId = extractJsonString(body, "id");
  if (command.length() == 0) command = body;
  command.toLowerCase();

  if (commandId.length() > 0 && commandId == lastRemoteCommandId) {
    lastRemoteStatus = "duplicate_" + commandId;
    return;
  }

  if (command.indexOf("press") >= 0 || command.indexOf("power") >= 0) {
    Serial.printf("Remote command accepted: id=%s body=%s\n", commandId.c_str(), body.c_str());
    pressPowerButton();
    if (commandId.length() > 0) lastRemoteCommandId = commandId;
    lastRemoteStatus = "pressed";
  } else {
    lastRemoteStatus = "unknown_command";
  }
}

static void startWifi() {
  WiFi.mode(WIFI_AP_STA);

  const char *apPass = cfg.apPassword.length() >= 8 ? cfg.apPassword.c_str() : DEFAULT_AP_PASSWORD;
  bool apOk = WiFi.softAP(cfg.apSsid.c_str(), apPass);
  Serial.printf("AP %s: %s IP=%s\n", cfg.apSsid.c_str(), apOk ? "started" : "failed", WiFi.softAPIP().toString().c_str());

  if (cfg.wifiSsid.length() > 0) {
    WiFi.begin(cfg.wifiSsid.c_str(), cfg.wifiPassword.c_str());
    Serial.printf("Connecting STA to %s", cfg.wifiSsid.c_str());
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
      delay(500);
      Serial.print('.');
    }
    Serial.println();
    if (WiFi.isConnected()) {
      Serial.printf("STA connected IP=%s\n", WiFi.localIP().toString().c_str());
      if (MDNS.begin(cfg.deviceName.c_str())) {
        Serial.printf("mDNS: http://%s.local/\n", cfg.deviceName.c_str());
      }
    } else {
      Serial.printf("STA not connected, status=%d\n", WiFi.status());
    }
  } else {
    Serial.println("No STA SSID configured; use setup AP to configure WiFi.");
  }
}

static void setupRoutes() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/config", HTTP_GET, handleConfig);
  server.on("/config", HTTP_POST, handleSaveConfig);
  server.on("/api/power/press", HTTP_GET, handlePowerPress);
  server.on("/api/power/press", HTTP_POST, handlePowerPress);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/reset-config", HTTP_POST, handleResetConfig);
  server.onNotFound([]() {
    server.send(404, "text/plain; charset=utf-8", "Not found");
  });
  server.begin();
  Serial.printf("HTTP server started on port %d\n", HTTP_PORT);
}

void setup() {
  bootMillis = millis();
  Serial.begin(115200);
  delay(200);
  Serial.println("\nESP32 Laptop Power Controller booting...");
  loadConfig();
  setupActuator();
  startWifi();
  setupRoutes();
}

void loop() {
  server.handleClient();
  pollRemoteCommand();
  delay(2);
}
