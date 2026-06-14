# 传话筒·立绘对话框

forked from [bvzrays/astrbot_plugin_chuanhuatong](https://github.com/bvzrays/astrbot_plugin_chuanhuatong)

将 Bot 的文字回复渲染为立绘对话框。

## 配置说明

所有配置项通过 AstrBot 的 `_conf_schema.json` 定义，在 AstrBot WebUI 的插件配置页面中可视化编辑。

---

### 渲染控制

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_render` | bool | `true` | 拦截纯文本回复并渲染为图片 |
| `render_scope` | string | `"llm_only"` | 渲染范围：`llm_only` = 仅渲染 LLM 回复；`all_text` = 渲染所有纯文本回复 |
| `render_char_threshold` | int | `60` | 渲染字符阈值（0 为不限制），超过阈值则直接发送纯文本或分割渲染 |
| `split_long_text` | bool | `false` | 启用超长文本智能分割渲染（超过阈值时自动分割为多张图片） |
| `merge_split_images` | bool | `true` | 合并分割渲染的图片为一张（需启用 `split_long_text`） |
| `merge_max_images` | int | `5` | 每批最多合并几张图片 |

### 图片质量

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `image_quality` | int | `85` | JPEG 图片质量（1-100） |

### 字体与背景

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `font_path` | string | `""` | Pillow 备用渲染使用的字体文件路径，不填则自动匹配系统字体 |
| `background_dir` | string | `"background"` | 背景图片目录（相对于插件目录） |

### 立绘（角色）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `character_root` | string | `"renwulihui"` | 立绘子目录根路径（相对于插件目录） |
| `default_emotion` | string | `"neutral"` | 未解析出标签时使用的情绪 key |

### 情绪标签提示

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_emotion_prompt` | bool | `true` | 是否在 LLM 请求前补充情绪标签提示语 |
| `emotion_prompt_template` | text | 见下方 | 追加到 system_prompt 的提示，可用 `{tags}` 代表全部标签 |

默认提示模板：
```
请在回答正文中就近插入一个情绪标签，例如 {tags}。标签写在对应句子旁即可，便于渲染立绘。标签仅包含字母、数字或下划线。
```

### WebUI

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `webui_enabled` | bool | `true` | 是否启动文本框拖拽 WebUI |
| `webui_host` | string | `"0.0.0.0"` | WebUI 监听地址，本地使用可设为 `127.0.0.1` |
| `webui_port` | int | `18765` | WebUI 端口，可设为 astrbot 现成端口（6180-6200） |
| `webui_token` | string | `""` | 访问 WebUI 时需要附带的 token。可留空，**服务器用户务必添加** |

### 情绪标签集

`emotion_sets` 定义情绪标签及其对应的立绘文件夹、展示文本与颜色。若不填则使用默认值。

默认值：

| key | folder | label | color | 说明 |
|-----|--------|-------|-------|------|
| `happy` | `happy` | 开心 | `#FFC857` | 开心情绪 |
| `sad` | `sad` | 低落 | `#7DA1FF` | 低落情绪 |
| `shy` | `shy` | 害羞 | `#F9C5D1` | 害羞情绪 |
| `surprise` | `surprise` | 惊讶 | `#F5E960` | 惊讶情绪 |
| `angry` | `angry` | 生气 | `#FF8A8A` | 生气情绪 |

每个情绪项包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 情绪标签（英文/数字），LLM 回复中插入 `&key&` 触发对应情绪 |
| `folder` | string | 对应立绘图片所在文件夹 |
| `label` | string | 界面展示用的中文名 |
| `color` | string | 角标颜色（十六进制） |
| `enabled` | bool | 是否启用该情绪 |

### 人格预设绑定

`persona_preset_bindings` 配置人格（Persona）到布局预设（Preset）的绑定列表。

渲染优先级：**会话预设 > 人格绑定预设 > 全局布局**

每项包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `persona_id` | string | 人格 ID |
| `name` | string | 预设名 |
| `slug` | string | 预设 slug（可选，优先用它精确匹配） |

### 黑白名单

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `whitelist_mode` | bool | `false` | `true` = 白名单模式，`false` = 黑名单模式 |
| `whitelist` | list | `[]` | 会话 ID 列表，格式：`platform:message_type:session_id`，例如 `aiocqhttp:group:123456789` |

- **黑名单模式**（默认）：列表中的群/私聊**禁用**传话筒
- **白名单模式**：仅列表中的群/私聊**启用**传话筒

可通过 `/传话筒 开启` 或 `/传话筒 关闭` 指令管理，也可直接在配置中编辑。

### 权限控制

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `control_permission` | string | `"admin_or_group_admin"` | 控制指令权限：`admin` = 仅框架管理员；`admin_or_group_admin` = 框架管理员或群管理 |

---

## 指令

- `/传话筒 开启` — 在当前会话启用传话筒渲染
- `/传话筒 关闭` — 在当前会话禁用传话筒渲染
- `/人格预设绑定 <人格ID> <预设名>` — 绑定人格到布局预设
- `/人格预设解绑 <人格ID>` — 解绑人格预设

---

## 目录结构

| 目录 | 说明 |
|------|------|
| `background/` | 内置背景图片 |
| `renwulihui/` | 内置立绘（按情绪文件夹组织） |
| `ziti/` | 内置字体文件 |
| `zujian/` | 内置组件图片（名称框、底框等） |
| `webui/` | WebUI 前端文件 |

插件运行时会创建数据目录（`AstrBot/data/plugin_data/astrbot_plugin_chuanhuatong/`），用于存储用户上传的资源、布局预设、会话配置等。
