# 🔍 无限画布 v2.5.8 — 外部代码审查报告（修复后更新）

> **审查日期：** 2026-06-20（初次） → **2026-06-21（修复后更新）**  
> **审查者：** Claude Code（6 个并行 Agent + 人工通读验证）  
> **修复执行：** 11 个 Bug 在 v2.5.8 中已修复（5 CRITICAL + 6 HIGH），见 `项目.MD` §14  
> **参照基准：** `项目.MD`（开发者自述技术文档，93 分自评）

---

## 目录

1. [与项目.MD 自评的对比](#与项目md-自评的对比)
2. [总体评分（外部视角）](#总体评分外部视角)
3. [项目.MD 未记录的真正新发现](#项目md-未记录的真正新发现)
4. [项目.MD 已记录但需关注的问题](#项目md-已记录但需关注的问题)
5. [项目.MD 中的设计决策（非问题）](#项目md-中的设计决策非问题)
6. [Bug 详细分析](#bug-详细分析)
7. [安全加固建议](#安全加固建议)
8. [性能深化建议](#性能深化建议)
9. [各模块补充评估](#各模块补充评估)
10. [优化路线图](#优化路线图)
11. [最终结论](#最终结论)

---

## 🟢 v2.5.8 已修复项（11/11 完成）

以下 11 个审查发现的 CRITICAL + HIGH Bug 已在 v2.5.8 中全部修复（详见 `项目.MD` §14 + §16.9~§16.12）：

| # | Bug | 级别 | 修复文件 | 改动 | 项目.MD 记录 |
|---|-----|:---:|------|------|:---:|
| B1 | runState 三元反向 | 🔴 | canvas-core.js + canvas-store.js | 2字符（`!`删除+分支交换） | §16.9 |
| B2 | JsonStore 缓存竞态 | 🔴 | json_store.py | +threading.Lock (4处) | §14 |
| B3 | 试用计数器竞态 | 🔴 | agent_routes.py | 内联写盘+deadlock-free | §16.10 |
| B4 | 占位符检测永假 | 🔴 | agent_routes.py | 3字符 `is None`→`not` | §14 |
| B5 | ComfyUI 超时 | 🔴 | generation.py | for→while+实际耗时 | §14 |
| B6 | 画布先清后取 | 🔴 | canvas-core.js | 清空移到fetch成功后 | §14 |
| B7 | Lightbox 内存泄漏 | 🔴 | canvas-renderer-lightbox.js | overlay.remove合并 | §16.11 |
| B8 | 视频硬编码.mp4 | 🔴 | openai.py | Content-Type检测 | §14 |
| B9 | HTML缓存永不过期 | 🔴 | main.py | mtime检查 | §14 |
| B10 | build_url双前缀 | 🔴 | openai+apimart+modelscope+volcengine | regex统一 | §14 |
| S1 | 密码经URL传输 | 🔴 | agents.html + agent_routes.py | FormData替代 | §16.12 |

**验证结果：** Python compileall PASS / 143 tests (2 pre-existing) / all JS syntax PASS / URL matrix 10/10 PASS / 3 JS版本号bump

---

## 与项目.MD 自评的对比

`项目.MD` 是一份**极其详尽**的技术文档，包含设计理念、架构说明、安全加固清单、已知性能债务、已修复 BUG 模式（§16）、测试覆盖和开发约定。这是该项目最大的资产之一。

### 评分对比（v2.5.8 修复后）

| 维度 | 项目.MD 自评 | 审查初评 | **修复后** | 说明 |
|------|:---:|:---:|:---:|------|
| 功能完整性 | 88 | 88 | **88** | 不变 |
| 架构清晰度 | 91 | 88 | **88** | 不变（agent_routes 拆分 + 图片解析统一属 P2 优化） |
| 安全性 | 92 | 85 | **87** | +2 — S1 密码经URL已修复；WS免认证/静态文件公开/在线更新无签名仍存 |
| 稳定性 | 92 | 82 | **90** | +8 — 5 CRITICAL bug 全部修复（runState/缓存竞态/计数器竞态/占位符防御/ComfyUI超时） |
| 性能 | 86 | 80 | **82** | +2 — B5+B9 修复附带性能改善；同步I/O+无连接池仍存 |
| 代码质量 | 91 | 85 | **87** | +2 — B4+B8+B10 消除3处逻辑缺陷；前端 inline JS/CSS 仍存 |
| 前端体验 | 90 | 82 | **86** | +4 — B1+B6+B7 修复（runState不再丢失/加载不空白/lightbox不泄漏） |
| 测试覆盖 | 73 | 75 | **75** | 不变 |
| 国际化 | 89 | 85 | **85** | 不变 |
| 可维护性 | 91 | 82 | **84** | +2 — 4个新BUG模式入§16，JS版本号更新 |
| **综合** | **93** | **83** | **87** | **+4** — 11个CRITICAL+HIGH全部修复，差距从-10缩小到-6 |

### 差距根因分析（v2.5.8 修复后）

初评 10 分差距 → 修复后 6 分差距。剩余差距来自：

1. **审计视角差异（~3 分）**：WS免认证、静态文件公开、在线更新无签名是项目"局域网免密"设计理念的一部分，外部审查标准仍会扣分。密码经URL（S1）已修复，此项差距已缩小。

2. **前端工程化（~2 分）**：inline JS/CSS、全局变量、无 CSP — 这些是 iframe 架构的技术选择，非 Bug。外部审查按生产标准会扣分。

3. **P2 优化未执行（~1 分）**：agent_routes 拆分、图片解析统一、Provider 共享 httpx client、目录索引缓存 — 已在优化路线图中但属阶段 1-2。

---

## 总体评分（外部视角）

| 维度 | 评分 | 评级 | 说明 |
|------|:---:|:---:|------|
| **后端架构** | 88/100 | A- | Provider 多态协议 + 自包含目录设计是王牌；agent_routes 过胖，图片解析重复 |
| **后端安全性** | 85/100 | B+ | SSRF/路径穿越/AES-GCM 加固全面；WS认证/静态文件/在线更新/密码经URL 4项扣分 |
| **后端代码质量** | 85/100 | B+ | 异常体系统一、注释详尽、命名规范；同步I/O阻塞+4处重复解析是主要债务 |
| **后端性能** | 80/100 | B | 异步架构+增量渲染方向正确；同步I/O+无连接池+O(n)扫描是瓶颈 |
| **前端架构** | 70/100 | B- | CanvasStore 数据层设计好；全局污染+prototype扩展+无模块化+Store订阅未启用 |
| **前端安全性** | 65/100 | C+ | i18n postMessage origin 校验正确；密码经URL+innerHTML遍布+无CSP |
| **前端代码质量** | 60/100 | C | 内联 JS/CSS/事件是 iframe 架构代价；无 strict mode 和 linter |
| **前端性能** | 72/100 | B- | 增量渲染已生效；全量重建+无事件委托+每帧getComputedStyle 仍存 |
| **无障碍** | 15/100 | F | 0 个 aria-* / 0 个 label for / 对比度不达标——桌面端非重点但有提升空间 |
| **测试覆盖** | 75/100 | B+ | 143 用例 94% 精确断言；Provider/Agent/WS 集成测试可扩充 |
| **文档（项目.MD）** | 95/100 | A+ | 极其详尽——设计理念/架构/安全/性能/测试/故障排查/版本历史/AI编程规则全覆盖 |
| **综合** | **83/100** | **B+** | 比项目.MD 自评低 10 分，主因是 10 个未记录的 Bug + 前端工程化差异 |

---

## 项目.MD 未记录的真正新发现 → 🟢 v2.5.8 全部修复

以下发现审查时**不在 `项目.MD` §16 中**，现已全部修复并收录入 §16.9~§16.12。

### 🔴 CRITICAL（5 个——需要紧急修复）

#### ✅ B1. `runState` 始终重置为 `'idle'` —— 数据丢失 &nbsp; `v2.5.8已修复`
**文件:** [static/js/canvas-core.js:105-109](static/js/canvas-core.js#L105-L109) + [canvas-store.js:81](static/js/canvas-store.js#L81)

```js
// loadFromServer() 中
runState: node.runState && node.runState !== 'idle' ? 'idle' : (node.runState || 'idle'),
//                         ↑ 三元方向反了！当条件为 true（状态非 idle）时，结果却是 'idle'
```

如果服务器存储了 `runState: 'running'` 或 `'error'`，条件 `node.runState !== 'idle'` 为 `true`，三元返回 `'idle'`。**所有画布加载时节点的运行状态永久丢失。** 正确写法：`node.runState && node.runState !== 'idle' ? node.runState : 'idle'`。

> 此 Bug 与 §16.1 的 `this` 绑定丢失属于同类模式——条件逻辑反向。但未被 §16 记录。

---

#### ✅ B2. JsonStore 缓存竞态条件 &nbsp; `v2.5.8已修复`
**文件:** [server/storage/json_store.py:40-94](server/storage/json_store.py#L40-L94)

`_cache` dict 被以下操作并发修改而**无任何同步原语**：
- `read()`（同步）在线程池中执行（经 `async_read` → `run_in_executor`）
- `write()`（异步）在主事件循环中执行

故障模式：`KeyError`（并发 del）、脏数据（write 失效后被并发 read 重填旧值）、迭代中修改崩溃。

> §16 未记录。项目.MD 只提到 JsonStore 的 TTL 缓存和原子写入，未意识到线程池 + asyncio 混合操作的缓存竞态。

---

#### ✅ B3. 试用计数器非原子读-改-写 &nbsp; `v2.5.8已修复`
**文件:** [server/routes/agent_routes.py:789-797](server/routes/agent_routes.py#L789-L797)

```python
trial["used"] = trial.get("used", 0) + 1          # 读-改
async def _save_trial():
    a2 = _load_agent(agent_id, fingerprint=fp)      # 重新从磁盘读（读到旧值）
    a2["_trial"] = trial
    await _save_agent(a2)                           # 写覆盖
asyncio.create_task(_save_trial())
```

两个并发 Agent 运行：都读到 `used=0` → 都递增到 1 → 都保存。最终 `used=1` 而非 2。**试用次数限制被绕过。**

> §15 描述了试用机制的"次数强制递增"，但未识别 fire-and-forget + 读-改-写分离造成的竞态。

---

#### ✅ B4. 占位符检测条件永远不会触发 &nbsp; `v2.5.8已修复`
**文件:** [server/routes/agent_routes.py:226-230](server/routes/agent_routes.py#L226-L230)

```python
if agent.get("system_prompt") == "[Encrypted]" and agent.get("skills") is None:
```

`_protect_agent_dict()` 将 `skills` 设为 `[]`（空列表），但此处检测 `is None`，条件**永远为 `False`**。误剥离 `_enc` 后覆盖占位符数据的防御完全失效——这是 v2.5.2 引入的 AAD 防篡改保护的**配套防御**被绕过。

---

#### ✅ B5. ComfyUI 轮询实际超时 ~25 分钟（预期 5 分钟） &nbsp; `v2.5.8已修复`
**文件:** [server/routes/generation.py:144-145](server/routes/generation.py#L144-L145)

```python
async with httpx.AsyncClient(timeout=5) as cli:   # HTTP 超时 5s
    for i in range(300):                           # 300 次
        await asyncio.sleep(1)                     # 等待 1s
```

ComfyUI 无响应时每次 HTTP 调用耗时完整 5 秒（不是 1 秒），总等待 = 300 × 5s = 1500s（25分钟）。进度公式 `i / 300 * 75` 因此完全不准确。

---

### ✅ HIGH（5 个——v2.5.8 全部修复）

| # | 文件:行号 | 描述 | 对应项目.MD |
|---|-----------|------|:---:|
| B6 | [canvas-core.js:90-94](static/js/canvas-core.js#L90-L94) | `load()` 在 fetch 前清空 nodes/connections/groups → 网络失败=空白画布 | ❌ 未记录 |
| B7 | [canvas-renderer-lightbox.js:130,167](static/js/canvas-renderer-lightbox.js#L130-L167) | `overlay.remove` 被赋值两次，第二次覆盖第一次 → 拖拽监听器永不释放，内存泄漏 | ❌ 未记录 |
| B8 | [openai.py:504](server/providers/openai.py#L504) | 视频下载硬编码 `.mp4` → 部分平台返回 `.webm` 导致 MIME 不匹配 | ❌ 未记录 |
| B9 | [main.py:85-90](server/main.py#L85-L90) | HTML 缓存 `hasattr(index, "_cached_html")` 永不过期 → 修改 index.html 不生效 | ❌ 未记录 |
| B10 | [openai.py:65-71](server/providers/openai.py#L65-L71) | `build_url` 对含嵌套路径的自定义 Base URL 可能产生双 `/v1` 前缀（同模式：apimart/modelscope/volcengine） | ❌ 未记录 |

### 🟠 MEDIUM（8 个）

| # | 文件:行号 | 描述 | 对应项目.MD |
|---|-----------|------|:---:|
| B11 | [canvas-renderer-groups.js:107](static/js/canvas-renderer-groups.js#L107) | 组 resize 只改 DOM 不同步 Store → auto-save 时存错误值 | ❌ 未记录 |
| B12 | [canvas-renderer-nodes.js:94](static/js/canvas-renderer-nodes.js#L94) | `node.h` 被 `offsetHeight` 覆盖 → 用户手动调整高度丢失 | ❌ 未记录 |
| B13 | [canvas-renderer-nodes.js:205](static/js/canvas-renderer-nodes.js#L205) | WH 输入框 `.nextElementSibling.nextElementSibling` 脆弱的 DOM 遍历 | ❌ 未记录 |
| B14 | [canvas-renderer-core.js:123](static/js/canvas-renderer-core.js#L123) | `\|\|` 替代 `??` → `fieldId=0` 被错误转换为 `''` | ❌ 未记录 |
| B15 | [openai.py:287](server/providers/openai.py#L287) | `(data.get("choices") or [{}])[0]` → choices 空列表时返回空 dict 静默吞错 | ❌ 未记录 |
| B16 | [apimart.py:151](server/providers/apimart.py#L151) | `task_id=""` → 轮询 URL 为 `/v1/tasks/`，浪费 4 分钟才超时 | ❌ 未记录 |
| B17 | [websocket/manager.py:34](server/websocket/manager.py#L34) | 心跳任务 `done()` 检查 ↔ `create_task` 间存在 TOCTOU 窗口 → 可能重复创建 | ❌ 未记录 |
| B18 | [api.js:69](static/js/api.js#L69) | JSON 解析失败静默返回 `{}` → 调试极其困难 | ❌ 未记录 |

### 🟡 LOW（6 个）

| # | 文件:行号 | 描述 |
|---|-----------|------|
| B19 | [canvas-viewport.js:15](static/js/canvas-viewport.js#L15) | `zoomFit` 只调 `_renderTransform` 不触发 renderAll/renderLinks |
| B20 | [ui-icon.js:52](static/js/ui-icon.js#L52) / [ui-nav-btn.js:44](static/js/ui-nav-btn.js#L44) | `customElements.define` 未 try/catch → 重复加载崩溃 |
| B21 | [json_store.py:64](server/storage/json_store.py#L64) | 缓存过期只删除条目，不主动刷新值 |
| B22 | [base.py:286](server/providers/base.py#L286) | `data["data"]` 为字符串时 `items[0]` 取到单个字符 |
| B23 | [canvas-renderer-links.js](static/js/canvas-renderer-links.js) | 无增量更新路径，每次全量重建连线 |
| B24 | [tokens.css:42,63](static/css/tokens.css#L42) | `--shadow` 在 `:root` 和 `html.dark` 中重复定义，暗色模式第一个声明是死代码 |

---

## 项目.MD 已记录但需关注的问题

以下问题在项目.MD 中被标记为**已知残余风险**或**已知性能债务**，外部审查确认它们仍然存在，建议提升处理优先级：

| 原记录位置 | 问题 | 外部审查建议 |
|-----------|------|-------------|
| §7 已知残余风险 | Gemini API Key 在 URL 中 → 日志暴露 | Google 原生协议限制，**短期无解**。建议在日志模块添加 Key 脱敏 filter |
| §7 已知残余风险 | `platforms.html` p.id 在 onclick 中未转义 | 当前硬编码数据安全。**若未来动态加载平台数据则成为 XSS 向量** |
| §8 已知性能债务 | 首次渲染全量 DOM 重建 | 拖拽已优化为增量。**新建/删除节点仍需全量重建**——中等画布（50+节点）用户可感知 |
| §8 已知性能债务 | 布局颠簸（appendChild+offsetHeight 在循环中） | 仅首次渲染。**对大画布（200+节点）首次加载有明显卡顿** |

---

## 项目.MD 中的设计决策（非问题）

以下我在初版报告中标记为"问题"的事项，经项目.MD 确认是**有意识的设计决策**，不应作为 bug 或缺陷报告：

| 原标记 | 实际设计意图 | 依据 |
|--------|------------|------|
| S1: WebSocket 无认证 | **局域网免密设计**——本机 `127.0.0.1` 免密，局域网设备输入预设密码 | 项目.MD "设计理念" + §10 |
| S2: 静态文件免认证 | **目录即数据 + 局域网协作**——画布文件需公开让其他设备直接加载图片/视频 | 项目.MD §11 "`/canvases/` 已加入鉴权白名单（公开访问）" |
| ~~S3: 密码经 URL~~ | **v2.5.8 已修复**——改为 FormData body 传输，API 契约已更新 | 项目.MD §16.12 |
| 前端全局变量 | **iframe 架构约束**——各页面通过 `window.*` 和 postMessage 跨 iframe 通信 | 项目.MD 架构图（index.html → 7 个 iframe 子页面） |
| 前端无 bundler | **零配置启动理念**——内嵌 Python 运行时，`.bat` 一键启动，不依赖 Node.js/npm | 项目.MD "设计理念" |
| `_temp_key` 机制 | **测试连接流程**——用户临时输入 Key 验证 API 可用性，验证后写入 .env | 项目.MD §5.3 "Provider 安全规则" |
| localStorage 明文 Key | **局域网信任模型**——面向家庭/小团队局域网，非公网 SaaS | 项目.MD "局域网多端协作" |
| 机器指纹 UUID 回退 | **极端情况兜底**——VM/容器无硬件信息时至少能运行（虽会损失跨重启加密数据） | 推测为设计取舍 |

**对于以上设计决策，外部审查的建议不是"改变设计"，而是：**

1. **密码经 URL**：改为请求体 (`FormData` 或 JSON body)。不改变导入流程，只改变传输方式。一行改动消除 Server Log / Browser History / Referer 三条泄露路径。
2. **WS/静态文件免认证**：如果未来需要公网部署，增加可选 token 认证开关。当前局域网场景下风险可控。
3. **机器指纹 UUID 回退**：添加 `logging.warning("Fingerprint fallback to random UUID — encrypted agent data will not survive restart")` 显式警告。

---

## Bug 详细分析

### 重点：runState Bug 的完整追踪

这是本次审查发现的**影响最大的单一 Bug**。以下是完整追踪：

```javascript
// canvas-core.js, loadFromServer():
CanvasStore.prototype.loadFromServer = function(canvasData) {
    this.nodes = (canvasData.nodes || []).map(function(node) {
        return Object.assign({}, node, {
            // BUG: 此表达式永远返回 'idle'
            runState: node.runState && node.runState !== 'idle'
                ? 'idle'                       // ← true 分支 → 'idle'
                : (node.runState || 'idle'),   // ← false 分支 → node.runState || 'idle'
            // 当 node.runState = 'running': 条件 true → 结果 'idle' ❌
            // 当 node.runState = 'error':   条件 true → 结果 'idle' ❌
            // 当 node.runState = 'idle':    条件 false → 结果 'idle' ✓
            // 当 node.runState = undefined: 条件 false → 结果 'idle' ✓
        });
    });
};
```

**影响范围**：画布管线执行中的节点（生成中/失败），刷新页面后状态徽章消失。对依赖 `runState` 判断节点执行状态的管线逻辑（`canvas-pipeline.js`）有直接影响。

**修复**：删除条件中的 `!`：
```javascript
runState: node.runState && node.runState !== 'idle' ? node.runState : 'idle',
```

---

### 重点：JsonStore 缓存竞态的技术分析

```
Timeline (两个并发请求):
─────────────────────────────────────────────────────────────
请求A (async write)              请求B (sync read via executor)
─────────────────────────────────────────────────────────────
write(): lock acquired
write(): tmp file written
write(): os.replace() done
write(): self._cache.pop(path)   ← 删除缓存条目
write(): lock released
                                  read(): 检查缓存 → 未命中
                                  read(): open() + json.load() → 读到新数据 ✓
                                  read(): self._cache[path] = (new_data, ...) ← 写入缓存
─────────────────────────────────────────────────────────────
✅ 此场景安全 — 写后读会拿到新数据

─────────────────────────────────────────────────────────────
请求C (sync read)                 请求D (async write)
─────────────────────────────────────────────────────────────
read(): 检查缓存 → 命中！
read(): return cached_data
                                  write(): lock acquired
                                  write(): tmp file + os.replace()
                                  write(): self._cache.pop(path)
read(): (已返回旧数据) ← ⚠️ 脏读
                                  write(): lock released
─────────────────────────────────────────────────────────────
❌ 此场景不安全 — C 返回了已被 D 覆盖的过期数据
```

**修复方案**（最小改动）：
```python
import threading

class JsonStore:
    def __init__(self):
        self._cache_lock = threading.Lock()
        ...

    def read(self, path, default=None):
        with self._cache_lock:
            cached = self._cache.get(path)
            if cached is not None:
                data, expiry = cached
                if time.time() < expiry:
                    return data
                del self._cache[path]
        # ... read from disk ...
        with self._cache_lock:
            self._cache[path] = (data, time.time() + _CACHE_TTL)
        return data
```

---

## 安全加固建议

以下建议**不影响**项目的"局域网免密"设计理念，是在当前架构上的增量加固：

| # | 优先级 | 位置 | 建议 | 影响设计理念？ |
|---|:---:|------|------|:---:|
| S-new1 | 🟠 | [agents.html:755](static/agents.html#L755) | 密码从 URL query string 改为 `FormData` body | **否** — 只改变传输方式 |
| S-new2 | 🟠 | [update.py:83-206](server/routes/update.py#L83-L206) | 在线更新添加 `sha256` 校验（GitHub Release `SHA256SUMS`） | **否** — 增加安全性 |
| S-new3 | 🟠 | [providers_cfg.py:106-139](server/routes/providers_cfg.py#L106-L139) | 收紧 `_ALLOWED_KEY_SUFFIXES` 白名单到精确键名 | **否** — 自定义 Provider 仍可通过已知前缀添加 |
| S-new4 | 🟡 | [app.py:128](server/app.py#L128) | RateLimitMiddleware `_clients` 添加 `maxsize=5000` 上限 | **否** |
| S-new5 | 🟡 | [logging_config.py](server/logging_config.py) | 添加 API Key 脱敏 filter（regex: `sk-[a-zA-Z0-9]+` → `sk-***`） | **否** — 保护 Gemini Key 日志暴露 |

---

## 性能深化建议

项目.MD §8 已列出已完成的性能优化和已知债务。以下是**未记录**的补充建议：

| # | 优先级 | 位置 | 问题 | 建议 | 预期收益 |
|---|:---:|------|------|------|------|
| P-new1 | 🔴 | Provider 层全部 8 个文件 | 每个 API 调用新建 `httpx.AsyncClient()` → 无连接复用/DNS缓存 | 在 `BaseProvider` 中添加模块级共享 client（或使用 `httpx.AsyncClient` 的 `limits` 和 `keepalive`） | 减少每次 AI API 调用的 TCP+TLS 握手延迟 (~50-200ms) |
| P-new2 | 🔴 | canvas_service + agent_routes | `_find_canvas_dir` / `_find_agent_dir` 每次 O(n) 扫描全目录+解析 JSON | 添加内存 `{id→dir_name}` 索引字典，监听目录变化时刷新 | 100+画布时加载从 ~500ms → ~1ms |
| P-new3 | 🟠 | [websocket/manager.py:75](server/websocket/manager.py#L75) | `broadcast()` 顺序发送 → 多客户端时延迟累积 | 使用 `asyncio.gather(*[ws.send_text(p) for ws in active])` | 10 客户端时广播从 ~100ms → ~10ms |
| P-new4 | 🟡 | [canvas-renderer-core.js:49](static/js/canvas-renderer-core.js#L49) | `getComputedStyle()` 每帧调用 | 缓存 CSS 变量值，仅主题切换时刷新 | 减少每次渲染的强制样式重计算 |

---

## 各模块补充评估

项目.MD 已给出完整的项目结构。以下**仅补充**外部审查视角下与自评有显著差异或遗漏的观察：

### Provider 层

| 文件 | 行数 | 项目.MD 未提及的亮点或问题 |
|------|------|------|
| `deepseek.py` | 50 | **架构最佳证明** — 50 行完成 DeepSeek 接入（继承 OpenAIProvider）。这是 Provider 多态协议设计好坏的试金石 |
| `openai.py` | 528 | build_url 的双 `/v1` 问题 + 视频硬编码 `.mp4` + `(choices or [{}])[0]` 静默吞错 — 三项均未在项目.MD 记录 |
| `gemini.py` | 287 | Key 在 URL 中已标记为协议限制。**额外发现**：`fetch_models` 中 `?key=` 同样暴露在日志 |
| `volcengine.py` | 259 | AK/SK 拼接为 Bearer 非标准 HMAC 签名 — 需确认火山方舟 API 实际接受此格式 |

### 前端 JS

| 文件 | 项目.MD 未提及的发现 |
|------|------|
| `canvas-store.js` | **设计最好**。O(1) 索引+脏标记+订阅者全部实现但 `subscribe()` 从未被调用——渲染器绕过 Store 直接读 `_dirty` |
| `canvas-renderer-lightbox.js` | `overlay.remove` 被覆盖两次——**内存泄漏**，项目.MD §16.1 记录过 destroy 泄漏但此处的 remove 覆盖未记录 |
| `i18n.js` | `_tt()` 180+ 映射硬编码是已知的技术债务，建议迁移到 locale JSON 的 `_ttMap` 字段 |

### 补充测试建议（在现有 143 用例基础上）

| 新增测试 | 覆盖范围 | 优先度 |
|------|------|:---:|
| Provider mock 集成测试 | Mock httpx → 验证 openai/apimart/gemini/volcengine 的响应解析正确性 | 🟠 |
| Agent 引擎集成测试 | ReAct 循环 + 工具调用 + 加密解密 | 🟠 |
| WebSocket 功能测试 | 连接/断开/心跳超时/broadcast/board.synced API | 🟠 |
| 并发写入安全测试 | 乐观锁 ConflictError + KeyedLockManager 序列化 | 🟡 |
| 前端 E2E | Playwright — 画布核心操作（创建节点/连线/拖拽/保存） | 🟡 |

---

## 优化路线图

### ✅ 阶段 0：已完成（v2.5.8，6/6 项）— CRITICAL Bug 修复

| # | 类别 | 位置 | 动作 | 状态 |
|---|------|------|------|:---:|
| 1 | Bug | [canvas-core.js:105](static/js/canvas-core.js#L105) | 修复 runState 三元反向 — 删掉 `!` | ✅ |
| 2 | Bug | [json_store.py:40-94](server/storage/json_store.py#L40) | 缓存加 `threading.Lock` | ✅ |
| 3 | Bug | [agent_routes.py:789-797](server/routes/agent_routes.py#L789) | 试用计数器原子化（deadlock-free 内联写盘） | ✅ |
| 4 | Bug | [agent_routes.py:228](server/routes/agent_routes.py#L228) | `is None` → `not` | ✅ |
| 5 | Bug | [generation.py:144-145](server/routes/generation.py#L144) | ComfyUI 超时计算修正 | ✅ |
| 6 | 安全 | [agents.html:755](static/agents.html#L755) | 密码从 URL → FormData body | ✅ |

### 阶段 1：高优（1-2 周，8 项）

| # | 类别 | 动作 |
|---|------|------|
| 7-8 | Bug | 修复 B6（画布清空） + B7（lightbox 泄漏） |
| 9-10 | Bug | 修复 B8（硬编码 .mp4） + B9（HTML 缓存） + B10（build_url 双前缀） |
| 11 | 性能 | Provider 共享 httpx.AsyncClient |
| 12 | 性能 | `_find_canvas_dir` / `_find_agent_dir` 内存索引 |
| 13 | 安全 | 在线更新添加 sha256 校验 |
| 14 | 安全 | 收紧 .env 写入键名白名单 |

### 阶段 2：中期（1-2 月，10 项）

| # | 类别 | 动作 |
|---|------|------|
| 15 | 质量 | agent_routes 拆分 → `services/agent_service.py` + `services/agent_protection.py` |
| 16 | 质量 | 统一 4 处图片 URL 解析 → `services/image_service.py: resolve_image_url()` |
| 17 | 质量 | 提取 `esc()`/`escJs()`/`showToast()` → `static/js/utils.js` |
| 18 | 质量 | 所有 JS 添加 `'use strict'` |
| 19 | 架构 | 打通 CanvasStore 订阅系统 → 渲染器通过 subscribe 响应变更 |
| 20 | 性能 | 渲染器事件委托替代每节点闭包 |
| 21 | 性能 | `getComputedStyle` 缓存 + `broadcast()` 并行化 |
| 22 | 安全 | RateLimitMiddleware 有界 LRU + 日志 Key 脱敏 |
| 23 | 测试 | Provider mock 测试 + Agent 集成测试 + WebSocket 测试 |
| 24 | 基础设施 | 优雅关闭 (SIGTERM handler) |

### 阶段 3：长期（2-3 月，8 项—前端重构）

| # | 类别 | 动作 |
|---|------|------|
| 25 | 前端架构 | 引入 ES modules + Vite → 消除全局命名空间 |
| 26 | 前端架构 | 拆分 CanvasEngine God Object |
| 27 | 前端质量 | 内联 JS → 外部文件；内联 style → CSS class |
| 28 | 前端质量 | 内联 onclick → addEventListener |
| 29 | 无障碍 | 添加 aria-* + label for |
| 30 | 无障碍 | `--muted` 对比度提升至 4.5:1 |
| 31 | i18n | `_tt()` 映射外部化到 locale JSON |
| 32 | 测试 | 前端 E2E (Playwright) |

---

## 最终结论（v2.5.8 更新）

### 一句话

> **初评 83/100（B+）→ 11 项修复后 87/100（A-）。5 个 CRITICAL + 6 个 HIGH 全部修复，项目.MD 差距从 -10 缩小到 -6。**

### 修复成果（v2.5.8）

- **11/11 CRITICAL+HIGH Bug 已修复**，0 回归
- **4 个新 BUG 模式入 §16**（§16.9~§16.12），防止复发
- **1 个 API 安全问题消除**（密码不再经 URL 传输）
- **3 个 JS 版本号更新**（canvas-core v15, canvas-store v3, lightbox v3）

### 三个最大的剩余风险

1. **优雅关闭缺失**——SIGTERM 后后台 AI 生成任务状态丢失，对于收费 API 调用可能造成费用浪费。**属阶段 1 高优项。**
2. **在线更新无签名验证**——GitHub raw URL 直接下载 Python 源文件写盘。**属阶段 1 高优项。**
3. **前端工程债务**——3500+ 行内联 JS、150+ 内联事件、无 CSP——在 iframe+局域网架构下是可接受的技术选择，但移交新开发者时会成为瓶颈。**属阶段 3。**

### 底线

**v2.5.8 已在局域网场景下达到生产可用标准。执行阶段 1（4 项，预计 1-2 周）后可达到 90 分。前端重构（阶段 3）在"仅桌面端+局域网"场景下不是阻塞项。**

---

## 附录：统计总表（v2.5.8 更新）

| 类别 | CRITICAL | HIGH | MEDIUM | LOW | 合计 | 已修复 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **项目.MD 未记录的 Bug** | ~~5~~ 0 | ~~5~~ 0 | 8 | 6 | **14** | 10/24 |
| **项目.MD 已记录的已知问题** | 0 | 0 | 2 | 2 | 4 | 0 |
| **设计决策（非问题）** | 0 | 0 | ~~6~~ 5 | 3 | **8** | S3→已修复 |
| **安全加固建议** | 0 | 0 | ~~4~~ 3 | 2 | **5** | S-new1→已修复 |
| **性能深化建议** | 0 | 2 | 1 | 1 | 4 | 0 |
| **测试补充建议** | 0 | 0 | 3 | 2 | 5 | 0 |
| **无障碍问题** | 2 | 3 | 2 | 0 | 7 | 0 |

> 总计 59 项：v2.5.8 已修复 11 项（5C+6H）+ 1 项设计决策消除 + 1 项安全建议消除 = **13 项已关闭**，剩余 46 项

---

*报告版本：v4 — 审查 v3 + v2.5.8 修复后更新（11 项 CRITICAL+HIGH 已关闭）*
*审查日期：2026-06-20（初版）→ 2026-06-21（修复后更新）*
