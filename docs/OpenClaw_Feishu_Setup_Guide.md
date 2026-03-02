# OpenClaw + 飞书 + Moonshot(Kimi) 完整配置指南

> 记录日期：2026-02-18
> 环境：Windows 10，Node.js，OpenClaw CLI

---

## 一、概览

本文档记录将 **OpenClaw AI Gateway** 与 **飞书（Lark）** 和 **Moonshot/Kimi** 大模型对接的完整流程，
最终实现在飞书中与 Kimi 模型对话的 AI 机器人。

**架构链路：**

```
飞书用户 → 飞书开放平台(WebSocket长连接) → OpenClaw Gateway → Moonshot API(kimi-k2.5) → 回复
```

---

## 二、前置条件

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10+ |
| Node.js | 已安装并加入 PATH |
| OpenClaw | 已通过 npm 全局安装 |
| 飞书开发者账号 | 需要创建企业自建应用 |
| Moonshot API Key | 从 [Moonshot 平台](https://platform.moonshot.cn/) 获取 |

---

## 三、Moonshot 模型配置

### 3.1 获取 API Key

1. 访问 [Moonshot 开放平台](https://platform.moonshot.cn/)
2. 创建 API Key，格式类似 `sk-xxxxxxxxxxxxxxxx`

### 3.2 配置 openclaw.json

配置文件路径：`C:\Users\<用户名>\.openclaw\openclaw.json`

在 `models.providers` 中添加 Moonshot 提供商：

```json
"models": {
    "providers": {
        "moonshot": {
            "baseUrl": "https://api.moonshot.cn/v1",
            "api": "openai-completions",
            "apiKey": "sk-你的API密钥",
            "authHeader": true,
            "models": {
                "kimi-k2.5": {
                    "name": "kimi-k2.5",
                    "contextWindow": 131072,
                    "maxOutput": 8192
                }
            }
        }
    }
}
```

**关键参数说明：**

| 参数 | 值 | 说明 |
|------|----|------|
| `baseUrl` | `https://api.moonshot.cn/v1` | Moonshot API 地址 |
| `api` | `openai-completions` | 兼容 OpenAI Chat Completions 格式，**不是** `openai-chat` 或 `openai-responses` |
| `authHeader` | `true` | 使用 Bearer Token 认证 |

### 3.3 设置默认模型

在 `openclaw.json` 顶层设置默认 Agent 使用 Kimi 模型：

```json
"agents": {
    "defaults": {
        "model": {
            "primary": "moonshot/kimi-k2.5"
        }
    }
}
```

### 3.4 Agent 级别配置

路径：`C:\Users\<用户名>\.openclaw\agents\main\agent\`

**auth-profiles.json** — 添加 Moonshot 认证：

```json
{
    "moonshot:default": {
        "type": "api_key",
        "provider": "moonshot",
        "key": "sk-你的API密钥"
    }
}
```

**auth.json** — 添加 Moonshot 密钥：

```json
{
    "moonshot": {
        "type": "api_key",
        "key": "sk-你的API密钥"
    }
}
```

**models.json** — 指定 Agent 主模型：

```json
{
    "primary": "moonshot/kimi-k2.5"
}
```

---

## 三附、让 OpenClaw 走 Claude (Anthropic)

若希望飞书机器人使用 **Claude** 而非 Moonshot，按以下配置即可。

### 1. 获取 Anthropic API Key

在 [Anthropic 控制台](https://console.anthropic.com/) 创建 API Key。

### 2. 在 openclaw.json 中添加 Anthropic 提供商

在 `models.providers` 中增加 `anthropic`（与 `moonshot` 并列）：

```json
"anthropic": {
    "api": "anthropic",
    "apiKey": "sk-ant-你的Anthropic密钥",
    "authHeader": true,
    "models": {
        "claude-sonnet-4-20250514": {
            "name": "claude-sonnet-4-20250514",
            "contextWindow": 200000,
            "maxOutput": 8192
        }
    }
}
```

文档中已注明：Anthropic 使用 `"api": "anthropic"`（不是 `openai-completions`）。

### 3. 默认模型改为 Claude

在 `openclaw.json` 的 `agents.defaults.model` 中：

```json
"agents": {
    "defaults": {
        "model": {
            "primary": "anthropic/claude-sonnet-4-20250514"
        }
    }
}
```

可按需换成 `claude-3-5-sonnet-20241022`、`claude-3-opus` 等 Anthropic 支持的模型名。

### 4. Agent 级认证与模型

路径：`C:\Users\<用户名>\.openclaw\agents\main\agent\`

**auth-profiles.json** 增加：

```json
"anthropic:default": {
    "type": "api_key",
    "provider": "anthropic",
    "key": "sk-ant-你的Anthropic密钥"
}
```

**auth.json** 增加：

```json
"anthropic": {
    "type": "api_key",
    "key": "sk-ant-你的Anthropic密钥"
}
```

**models.json** 改为：

```json
{
    "primary": "anthropic/claude-sonnet-4-20250514"
}
```

保存后重启 Gateway（`openclaw gateway stop` 再 `openclaw gateway start`），飞书对话即走 Claude。

---

## 四、飞书应用配置

### 4.1 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 创建**企业自建应用**
3. 记录以下信息：
   - **App ID**：例如 `cli_a9f23f624b649ceb`
   - **App Secret**：例如 `F4aHJepltjOioMCyDW0zWfvDwKrpdHeQ`

### 4.2 配置事件订阅

1. 进入应用 → **事件订阅**
2. **订阅方式选择「长连接」**（非 HTTP 推送）
3. 添加以下事件：

| 事件 | 说明 |
|------|------|
| `im.message.receive_v1` | **必须** — 接收用户消息 |
| `im.chat.member.bot.added_v1` | 机器人被加入群聊 |
| `im.chat.member.bot.deleted_v1` | 机器人被移出群聊 |
| `im.message.reaction.created_v1` | 消息被添加表情回复 |
| `im.message.reaction.deleted_v1` | 消息表情回复被删除 |

### 4.3 配置加密策略

进入应用 → **事件与回调** → **加密策略**：

1. **开启** Encrypt Key
2. 记录 **Verification Token** 和 **Encrypt Key**

### 4.4 配置权限

确保应用已开启以下权限（权限管理页面）：

| 权限 | 说明 |
|------|------|
| `im:message` | 获取与发送单聊、群组消息 |
| `im:message:send` | 以应用身份发送消息 |
| `im:resource` | 获取消息中的资源文件 |
| `im:chat` | 获取群组信息 |

### 4.5 发布应用

1. 进入 **版本管理与发布**
2. 创建新版本
3. 提交审核 / 发布上线
4. 确保应用状态为 **已启用**

> ⚠️ **每次修改权限、事件订阅或加密策略后，都需要创建新版本并发布，改动才会生效。**

---

## 五、OpenClaw 飞书通道配置

### 5.1 配置 openclaw.json 中的飞书通道

在 `openclaw.json` 的 `channels` 部分添加：

```json
"channels": {
    "feishu": {
        "appId": "cli_你的AppID",
        "appSecret": "你的AppSecret",
        "verificationToken": "你的VerificationToken",
        "encryptKey": "你的EncryptKey",
        "enabled": true
    }
}
```

**注意：** 飞书插件是 OpenClaw **内置**功能，**不需要**在 `plugins.entries` 中额外注册。

### 5.2 完整 openclaw.json 示例结构

```json
{
    "gateway": {
        "port": 18789,
        "host": "127.0.0.1"
    },
    "auth": {
        "mode": "token",
        "tokens": ["你的gateway-token"]
    },
    "agents": {
        "defaults": {
            "model": {
                "primary": "moonshot/kimi-k2.5"
            }
        }
    },
    "models": {
        "providers": {
            "moonshot": {
                "baseUrl": "https://api.moonshot.cn/v1",
                "api": "openai-completions",
                "apiKey": "sk-你的API密钥",
                "authHeader": true,
                "models": {
                    "kimi-k2.5": {
                        "name": "kimi-k2.5",
                        "contextWindow": 131072,
                        "maxOutput": 8192
                    }
                }
            }
        }
    },
    "channels": {
        "feishu": {
            "appId": "cli_你的AppID",
            "appSecret": "你的AppSecret",
            "verificationToken": "你的VerificationToken",
            "encryptKey": "你的EncryptKey",
            "enabled": true
        }
    },
    "commands": {
        "restart": true
    }
}
```

---

## 六、启动与验证

### 6.1 启动 Gateway

```powershell
openclaw gateway start
```

成功启动后日志应包含：
```
[feishu] connected — WebSocket 长连接已建立
gateway listening on 127.0.0.1:18789
```

### 6.2 常用管理命令

```powershell
# 检查配置健康度
openclaw doctor

# 停止 gateway
openclaw gateway stop

# 查看当前配置
openclaw config get

# 批准飞书用户（首次发消息时需要）
openclaw pairing approve feishu <PAIRING_CODE>
```

### 6.3 Dashboard 访问

浏览器打开（需带 token 参数）：

```
http://127.0.0.1:18789/?token=你的gateway-token
```

在 Dashboard 中可以直接与模型对话，验证 Moonshot API 是否正常工作。

---

## 七、用户配对（Pairing）机制

OpenClaw 采用 **配对审批** 安全机制：

1. 新用户第一次给机器人发消息时，会收到一条提示：
   ```
   OpenClaw: access not configured.
   Your Feishu user id: ou_xxxxxx
   Pairing code: XXXXXXXX
   Ask the bot owner to approve with:
   openclaw pairing approve feishu XXXXXXXX
   ```

2. 管理员在终端执行批准命令：
   ```powershell
   openclaw pairing approve feishu XXXXXXXX
   ```

3. 批准后用户即可正常使用机器人。

> 这是正常的安全流程，不是配置错误。每个新用户首次使用都需要管理员批准。

---

## 八、常见问题排查

### Q1：飞书发消息没有任何反应

**排查步骤：**

1. 确认 Gateway 正在运行：`openclaw gateway start`
2. 确认飞书应用已发布最新版本
3. 确认事件订阅方式是 **长连接**（不是 HTTP 推送）
4. 确认已订阅 `im.message.receive_v1` 事件
5. **确保没有其他进程占用飞书 WebSocket 连接**（一个 App ID 同时只能有一个 WebSocket 连接）

```powershell
# 查找所有 node 进程
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Select-Object ProcessId, CommandLine |
  Format-List
```

如有多余进程，使用 `Stop-Process -Id <PID> -Force` 终止。

### Q2：Dashboard 提示 "unauthorized: gateway token missing"

在 URL 中添加 token 参数：
```
http://127.0.0.1:18789/?token=你的gateway-token
```

### Q3：模型没有回复 / 报 "No API key found"

确保以下三个位置都配置了 API Key：

1. `openclaw.json` → `models.providers.moonshot.apiKey`
2. `agents/main/agent/auth-profiles.json` → `moonshot:default`
3. `agents/main/agent/auth.json` → `moonshot`

并确认 `models.json` 中 `primary` 设为 `"moonshot/kimi-k2.5"`。

### Q4：Gateway 启动失败 "lock timeout"

说明有旧进程残留：

```powershell
# 查找并终止残留进程
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
  Where-Object { $_.CommandLine -match 'openclaw' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 重新启动
openclaw gateway start
```

### Q5：`api` 格式选哪个？

| 提供商 | `api` 值 |
|--------|----------|
| Moonshot/Kimi | `openai-completions` |
| OpenAI | `openai-completions` |
| Anthropic | `anthropic` |
| MiniMax | `openai-completions` |

> `openai-chat` 和 `openai-responses` 对 Moonshot 均不兼容，必须使用 `openai-completions`。

---

## 九、飞书独立测试脚本（调试用）

当需要独立验证飞书 WebSocket 是否能收到消息时，可使用以下脚本：

```bash
npm install @larksuiteoapi/node-sdk
```

创建 `test_feishu_ws.mjs`：

```javascript
import lark from "@larksuiteoapi/node-sdk";

const APP_ID = "cli_你的AppID";
const APP_SECRET = "你的AppSecret";
const VERIFICATION_TOKEN = "你的VerificationToken";
const ENCRYPT_KEY = "你的EncryptKey";

const eventDispatcher = new lark.EventDispatcher({
  verificationToken: VERIFICATION_TOKEN,
  encryptKey: ENCRYPT_KEY,
}).register({
  "im.message.receive_v1": async (data) => {
    console.log("=== RECEIVED MESSAGE ===");
    console.log(JSON.stringify(data, null, 2));
    console.log("========================");
  },
});

const wsClient = new lark.WSClient({
  appId: APP_ID,
  appSecret: APP_SECRET,
  loggerLevel: lark.LoggerLevel.DEBUG,
});

wsClient.start({ eventDispatcher });

setInterval(() => {
  console.log(`[heartbeat] ${new Date().toISOString()} - still waiting...`);
}, 30000);

console.log("Test started. Send a message to the bot!");
```

运行：

```bash
node test_feishu_ws.mjs
```

> ⚠️ **测试完毕后务必关闭此脚本**，否则会与 OpenClaw Gateway 抢占 WebSocket 连接。

---

## 十、关键文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| 主配置 | `~/.openclaw/openclaw.json` | Gateway、模型、通道全局配置 |
| Agent 认证 | `~/.openclaw/agents/main/agent/auth-profiles.json` | API Key 认证配置 |
| Agent 认证 | `~/.openclaw/agents/main/agent/auth.json` | 备用认证配置 |
| Agent 模型 | `~/.openclaw/agents/main/agent/models.json` | Agent 级模型设置 |
| 测试脚本 | `项目根目录/test_feishu_ws.mjs` | 飞书 WebSocket 独立测试 |

---

## 十一、配置踩坑总结

| 坑点 | 正确做法 |
|------|----------|
| `api` 设为 `openai-chat` | 改为 `openai-completions` |
| 模型名写成 `kimi-2.5` | 正确名称是 `kimi-k2.5`（有 k） |
| 飞书事件用 HTTP 推送 | 改为**长连接** |
| 多个进程抢 WebSocket | 确保只有一个进程连接飞书 |
| 没配 Verification Token | `openclaw.json` 的 `channels.feishu` 中必须填写 |
| 没开启 Encrypt Key | 飞书控制台开启后同步到配置文件 |
| 忘记发布新版本 | 飞书每次改动后都要创建新版本并发布 |
| 新用户无法对话 | 正常现象，需管理员执行 `pairing approve` |
