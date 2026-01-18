# 插件系统

本程序可以从 `plugins/` 目录加载外部插件。

每个插件放在独立文件夹中，并且必须包含 `plugin.json` 清单文件。

最小结构：

```
plugins/
  my_plugin/
    plugin.json
    main.py
```

清单字段（`plugin.json`）：

```
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "description": "What this plugin does.",
  "entry": "main.py"
}
```

入口模块（`main.py`）：

你可以暴露以下任意一种：

- `PLUGIN`：包含钩子方法的对象
- `create_plugin(context)`：返回包含钩子方法的对象
- `Plugin`：类，使用 `Plugin(context)` 实例化
- 模块级钩子函数（兜底）

可用钩子方法（均为可选）：

- `on_load(context)`
- `on_unload()`
- `on_app_start()`
- `on_app_ready()`
- `on_settings(settings_dict)`
- `on_state(state_dict)`
- `on_tick(state_dict, now_ts)`
- `on_user_message(text)`
- `on_ai_reply(text)`
- `on_passive_message(text)`
- `should_block_passive(reason)` 或 `on_should_block_passive(reason)`
- `get_panel(parent)` 或 `open_panel(parent)`

钩子说明：

- `on_load(context)`: 插件加载完成后触发，只调用一次。适合初始化资源。
- `on_unload()`: 插件卸载或程序退出时触发。适合释放资源。
- `on_app_start()`: 插件管理器完成加载后触发。
- `on_app_ready()`: 主窗口与桥接就绪后触发。
- `on_settings(settings_dict)`: 设置更新时触发。
- `on_state(state_dict)`: 每次状态刷新时触发（包含状态、空闲时间、窗口标题等）。
- `on_tick(state_dict, now_ts)`: 每个主循环 tick 触发，`now_ts` 为时间戳。
- `on_user_message(text)`: 用户发送消息时触发。
- `on_ai_reply(text)`: AI 回复产生时触发。
- `on_passive_message(text)`: 被动对话消息产生时触发。
- `should_block_passive(reason)`/`on_should_block_passive(reason)`: 返回 True 可阻断被动提示，例如插件需要使用气泡时。
- `get_panel(parent)`/`open_panel(parent)`: 返回或打开插件管理面板（PySide6 组件）。

`context` 字段：

- `context.plugin_id`
- `context.plugin_dir`
- `context.base_dir`
- `context.data_dir`
- `context.settings`（AppSettings 实例）
- `context.bridge`（BackendBridge 实例）
- `context.block_passive(seconds)`：短时间阻断被动提示，避免插件气泡被打断。
- `context.add_texts(path, items)`：向文本库追加被动语句（如 `passive.random`），供气泡系统使用。

数据文件：

使用 `context.get_data_path(...)` 将插件数据存放在
`data/plugins/<plugin_id>/...`。

日志规范：

- 使用 `context.info(...)` / `context.warn(...)` / `context.error(...)` 输出日志。
- 日志会写入 `data/plugins/<plugin_id>/plugin.log`，并在插件管理面板底部显示。

注意事项：

- 插件与主程序同进程运行。钩子内请保持快速，重任务建议使用后台线程。
- 请自行捕获异常；错误会显示在插件管理面板中。
