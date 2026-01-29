# Plastic Memories 插件（MVP）

本插件为桌宠聊天接入 Plastic Memories：启动人格、对话前 Recall 注入、对话后写入消息与记忆。

## 目录结构（遵循插件规范）
```
plugins/plastic_memories/
  plugin.json
  main.py
  pm_client.py
  pm_prompt.py
  pm_policy.py
```

## 启用方式
- 插件管理面板中勾选启用
- 或在 `data/settings.json` 中设置：
```json
{ "settings": { "plugins_enabled": { "plastic_memories": true } } }
```

## 插件面板
在插件管理中点击“打开面板”可进行：
- 配置 PM_* 参数
- 测试 /health、ensure_persona、recall

## 日志确认
- 当 Recall 注入成功时，插件日志会出现：`Recall 注入已生效`

## 配置（环境变量优先）
- `PM_BASE_URL`：默认 `http://127.0.0.1:8007`
- `PM_USER_ID`：默认 `local`
- `PM_PERSONA_ID`：默认 `persona_1`
- `PM_TEMPLATE_PATH`：默认 `personas/persona_1`
- `PM_SOURCE_APP`：默认 `tools_live2D`
- `PM_TIMEOUT`：默认 `10`
- `PM_ENABLED`：默认 `true`

配置文件位置：`data/plugins/plastic_memories/config.json`

## Plastic Memories 后端启动
- 进入 Plastic Memories 项目后启动服务（示例）：
  - Windows (PowerShell)：`python -m pm_server`
  - Linux/macOS：`python -m pm_server`
- 服务默认监听 `127.0.0.1:8007`

## 连接验证
- `GET /health`
- 示例：`curl http://127.0.0.1:8007/health`

## 常见错误
- 127.0.0.1 指向错误机器：桌宠和后端不在同一台机器时请改用局域网 IP。
- 端口未开放/被占用：确认 8007 端口监听并放行防火墙。

## 插件调用的 API
- `POST /persona/create_from_template`
- `POST /memory/recall`
- `POST /messages/append`（后端文档为单条，插件先批量，422 后自动切换单条）
- `POST /memory/write`（单条记忆写入）

## 本地规则提炼（MVP）
- “叫我 / 称呼我为 / 我叫 X” → `preferences.user_name`
- “以后用中文 / 默认用中文” → `preferences.language=zh-CN`
- “步骤列表 / 最小可运行 / MVP” → `preferences.response_style`
