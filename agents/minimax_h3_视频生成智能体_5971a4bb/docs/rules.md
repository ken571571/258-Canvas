# MiniMax H3 走秀视频固定规则

> 基于官方 skill `h3-prompt-writing/references/base-en.txt`（I2VA + FL2VA 模式）提炼，官方完整文件位于 skills/h3-prompt-writing/references/base-en.txt。

## 输出纪律

- 只输出 1 段 **H3 格式的英文提示词**。
- 禁止输出：风格分析、标题、编号、解释文字、任何其它非提示词内容。
- 自动检测图片数量：1 张 → I2VA 模式；2 张 → FL2VA 模式。

## 模式一：I2VA（单图首帧）

### 输出模板骨架（对齐指令后有且仅有一个空行，三个字段连续无空行）
```
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, ...
overall_soundscape: ...
non_diegetic_music: ...
```

### integrated_multimodal_description 结构
- 单镜头 `[Shot 1]`，开头 `Live-action, cinematic,` + 从 Picture 1 继承的锚点。
- 动作路径：first-frame anchor → action onset → continuous development → result or reaction。
- 一致性声明：`preserving her appearance, clothing, colors, and the scene layout`。
- 镜头运动用官方表达（Motion Type + Amplitude + Speed）。
- **转身角度硬约束**：身体转动不超过 45 度，禁止 180 度转身、禁止展示完整背面（单图只有正面信息，大幅度转身会导致 H3 脑补背面、衣服失真）。

## 模式二：FL2VA（首尾帧）

### 输出模板骨架
```
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the S.SS-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, ...
overall_soundscape: ...
non_diegetic_music: ...
```

### integrated_multimodal_description 结构
- 单镜头 `[Shot 1]`，开头 `Live-action, cinematic,` + 从 Picture 1 继承的锚点。
- 动作路径：first-frame state → observable intermediate changes → progressively narrowing differences → last-frame state（settling into Picture 2）。
- 用户输入含"缓慢/慢慢/slow"时，转身必须带 `slowly`。

## 三个核心字段（两种模式共用）

### integrated_multimodal_description
- 单镜头，动作具体可执行（步数/角度/速度/面料动态/头发动态）。
- 人物、服装、场景、光线保持一致。

### overall_soundscape
- 1-4 句英文，环境音+动作音（脚步声/面料摩擦/衣摆飘动/场景音）。
- 不含对话、唱歌、背景音乐。
- 完全静音写 `N/A`。

### non_diegetic_music
- 1-3 句英文，乐器+速度+节奏+动态变化。
- **严禁**抽象情绪词（cinematic / beautiful / emotional / elegant / subdued / sophisticated / moody / atmospheric / ambient / melancholic / introspective / dreamy / haunting / epic 等），只写可听的声音元素。
- 无音乐写 `N/A`。

## I2VA 走秀动作库（用户未指定动作时随机选择）

> **硬约束**：I2VA 只有正面图，所有动作身体转动角度不超过 45 度，禁止 180 度转身、禁止展示完整背面。用户输入大幅度转身时自动优化为小角度动作。

1. 自然走秀定格：向前走 2-3 步 → 定点站立 → 微调重心 → 面料垂坠定格。
2. 走秀+回头 pose：向前走几步 → 回头看镜头（仅头部）→ 自信 pose → 衣摆飘动。
3. 优雅定点微转：站立 → 向一侧微转（≤45度）展示侧面线条 → 头发轻摆 → 回正。
4. T 台自信迈步：大步向前走 → 手臂自然摆动 → 面料随步伐飘动 → 近处定格。
5. 衣摆轻摆展示：身体小角度左右轻摆（≤45度）→ 衣摆袖子飘动展开 → 停止展示垂坠感。
6. 正面 pose 变化：站立 → 手插兜/叉腰/轻触衣领 → 微调姿态 → 展示正面细节。
7. 镜头推进细节：模特站立或微摆 → 镜头缓慢推进（push in）→ 展示面料纹理/刺绣/图案。
8. 微风动态展示：模特站立 → 微风吹动头发衣摆 → 面料飘动 → 定格。

选择原则：优先匹配服装风格；每次生成选择不同动作，避免重复。

## 用户输入动作优化规则

- 解析核心动作（走/转身/pose/回头/旋转/定格）。
- 补充专业细节：步数、步幅、方向、转身角度/速度/方向、面料动态、最终状态。
- **I2VA 转身角度限制**：I2VA 模式下转身角度不超过 45 度（slight turn / subtle rotation），禁止写 180 degrees；用户输入大幅度转身时自动优化为小角度。FL2VA 模式下可写 180 degrees。
- 确保动作在指定时长内可完成。
- 动作与服装风格匹配。
- 转化为英文专业描述写入 integrated_multimodal_description。

## 默认参数（用户未指定时）

| 参数 | 默认值 |
|---|---|
| 时长 | 简单动作 8 秒；3 段以上复杂动作 10 秒；用户输入指定时长优先 |
| 风格 | 根据服装自动匹配 |
| 动作 | I2VA：从动作库随机选；FL2VA：自然走秀转身 |
| 镜头 | 静态或微幅缓慢推进 |
| 背景音乐 | 根据风格匹配 |

## 风格匹配表

| 服装风格 | 视频风格 | 背景音乐倾向 |
|---|---|---|
| 高级礼服 / 晚装 | 高级时尚大片 | 电子氛围 / 极简合成器 |
| 极简都市 / 职业 | 极简写实 | 钢琴 / 氛围电子 |
| 街头潮流 | 街头时尚 | 节奏电子 / hip-hop beat |
| 休闲度假 | 自然生活感 | 原声吉他 / 轻节奏 |
| 波西米亚 | 自然飘逸 | 世界音乐 / 轻氛围 |
| 运动 / 活力 | 动感活力 | 节拍电子 / 运动节奏 |

## 一致性规则（必须检查）

- **镜头运动一致**：不能同时写 `static shot` 和 `push in` / `track` / `pan`，二选一。
- **音效一致**：不能同时写 `bare feet` 和 `high heels`；看不到鞋履时写 `footsteps`。
- **参考图引用**：必须用 `Picture 1` / `Picture 2`，不用 `tail frame` / `last frame` / `final frame`。
- **人物/服装/场景一致**：首尾帧之间保持一致。
- **I2VA 转身角度**：不超过 45 度，禁止 180 度转身和完整背面展示。

## 用词规范

- 用具体可执行的动词 + 名词。
- 除官方要求的 `Live-action, cinematic` 开头外，杜绝空泛形容词。
- 只描述图片真实可见的信息，看不到的标"无法确认"，禁止脑补。
- 输出英文。
