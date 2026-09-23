# 牙医数字人 H3 Ref2VA 提示词固定规则

> 基于官方 skill `h3-prompt-writing/references/ref-en.txt`（Ref2VA 全参考模式）提炼，官方完整文件位于 skills/h3-prompt-writing/references/ref-en.txt。

## 输入格式

输入的脚本文本是**自然语言标签格式**，按以下标签提取：
- `【台词】`：最终台词，必须逐字原样使用，不得修改
- `【动作】`：数字人动作描述，翻译为英文
- `【动效】`：画面动效描述，翻译为英文
- `【语气】`：语气风格，指导动作和语音情感
- `【主题】`、`【合规检查】`：仅供参考，不写入提示词

如果输入是JSON格式，按字段名对应提取：script→台词，avatar_action→动作，visual_effect→动效，tone→语气。

## 输出纪律

- **只输出一个 JSON 对象**，包含 prompt、duration、resolution、aspect_ratio、generate_audio 五个字段。
- 禁止输出：风格分析、标题、编号、解释文字、任何其它非 JSON 内容。不要用 markdown 代码块包裹。
- **prompt 字段字符数硬上限：4000 字符**（H3 API prompt 字段限制）。各段必须精简。
- prompt 字段内六段顺序固定：subject_definitions → summary → retention_analysis → detailed_description → overall_soundscape → non_diegetic_music。
- duration 固定 15，resolution 默认 720p，aspect_ratio 固定 9:16，generate_audio 固定 true。

## JSON 输出结构

```json
{
  "prompt": "subject_definitions:\n<Subject 1> ...\n...\nnon_diegetic_music:\nN/A",
  "duration": 15,
  "resolution": "720p",
  "aspect_ratio": "9:16",
  "generate_audio": true
}
```

## 六段输出结构（顺序不可变）

```
subject_definitions:
<Subject 1> ...
<Subject 2> ...
<Audio 1> ...
<Picture 1> ...

summary:
[reference generation + audio reference] ...

retention_analysis:
<Subject 1> ...: fully_preserved - ...
<Subject 2> ...: fully_preserved - ...
<Audio 1>: reference - ...
<Picture 1> ...: fully_preserved - ...

detailed_description:
The target video uses ...
[Shot 1] ...

overall_soundscape:
...

non_diegetic_music:
N/A
```

## subject_definitions 规则

- `<Subject 1>`：牙医主播（来自 Picture 1），人物外观+服装+职业身份。
- `<Subject 2>`：场景（来自 Picture 1），背景、光线、氛围。
- `<Audio 1>`：真人原声音色参考，必须写 `is the voice-timbre reference for <Subject 1> (S1)`。
- `<Picture 1>`：起始帧锚点。
- 标签在所有段落中保持一致含义。

## summary 规则

- 以 `[reference generation + audio reference]` 开头（图片参考生成 + 音频音色参考）。
- 一段英文，描述目标视频核心内容：牙医主播开口讲解、口型同步、场景不变、使用 Audio 1 音色。
- 使用已定义的 `<Subject N>` 和 `<Audio N>` 标签，不引入新标签。

## retention_analysis 规则

- 每个参考标签一行。
- `<Subject 1>`（牙医主播）：`fully_preserved` — 人物外观、服装、身份完全保留。
- `<Subject 2>`（场景）：`fully_preserved` — 场景、光线、背景完全保留，全程静止不变。
- `<Audio 1>`（音色参考）：`reference` — 只参考音色和说话风格，不复制原音频信号。
- `<Picture 1>`（起始帧）：`fully_preserved` — 起始帧构图完全保留。
- 格式：`<Subject N> (appears in [Shot 1]): fully_preserved - ...`

## detailed_description 规则（核心，受 4000 字符总上限约束）

- `[Shot 1]` 前用 1-2 句建立整体风格。
- 单镜头 `[Shot 1]`，15秒，不切换镜头。

**必须包含的核心要素：**
1. **场景静止声明**：明确写 `the background remains completely static and unchanged throughout the entire video`。
2. **人物动作**：具体的手势、表情、头部动作，与台词同步。
3. **口型同步**：明确写 `lip movements synchronized with the dialogue`。
4. **台词**：中文台词原样放入 `<d>[Chinese] 台词内容</d>`。
5. **音色引用**：说话处写 `using the voice timbre referenced from <Audio 1>`。
6. **说话人标注**：`<Subject 1> (S1)`。
7. **画面动效**：描述画面中出现的动效元素（位置、形式、时机），不遮挡面部。
8. **镜头运动**：静态 static 或微幅缓慢推进 subtle slow push in，二选一，保持一致。
9. **参考标签插入**：在主体首次出现和关键位置插入 `<Subject 1>`、`<Subject 2>`、`<Audio 1>` 标签。

**台词格式：**
```
<Subject 1> (S1) speaks with [tone] expression, using the voice timbre referenced from <Audio 1>, with lip movements synchronized to the dialogue: <d>[Chinese] 中文台词内容</d>
```

**动作描述要求：**
- 用具体可执行的动词+名词（raises right hand, nods gently, smiles, points to the side）。
- 杜绝空泛形容词（natural movement, appropriate gesture）。
- 动作与台词内容匹配。
- 表情与语气匹配。

## overall_soundscape 规则

- 1-2 句英文，环境音（安静室内、轻微空调声）。
- 不含对话、唱歌、背景音乐。
- 对话已在 detailed_description 中通过 `<d>` 标签定义。

## non_diegetic_music 规则

- 数字人讲解视频默认 `N/A`（无背景音乐）。
- 如需要，1-3 句英文，乐器+速度+节奏+动态变化。
- **严禁**抽象情绪词（cinematic / beautiful / emotional / elegant / subdued / sophisticated / moody / atmospheric / ambient / melancholic / introspective / dreamy / haunting / epic 等）。

## 核心硬约束

0. **台词原样使用（最高优先级）**：输入脚本的 `script` 字段是最终台词，必须逐字原样放入 `<d>[Chinese]...</d>`，不得修改、删减、增写、重写或意译。所有 `<d>` 标签内容拼接起来必须等于原始 script。**绝对禁止自己创作新台词**。
1. **场景保持不变**：必须明确写 background remains completely static，retention_analysis 中 Subject 2 为 fully_preserved。
2. **口型同步**：必须写 lip movements synchronized with the dialogue。
3. **音色参考**：必须定义 `<Audio 1>` 为 voice-timbre reference，说话处引用 Audio 1。
4. **台词中文**：`<d>[Chinese]...</d>` 内必须是中文原文，不翻译。
5. **说话人标注**：必须用 `<Subject 1> (S1)`。
6. **单镜头**：`[Shot 1]`，15秒，不切换。
7. **总字符 ≤ 4000**。
8. **镜头运动一致**：不能同时 static 和 push in。

## 牙医数字人动作库

> 所有动作为上半身/手部动作，配合讲解，不涉及走动。

1. **专业讲解型**：端正，右手抬起做解释手势，手指轻捏表示细节，点头强调重点，表情认真。
2. **亲切科普型**：微笑看向镜头，双手自然张开，说到关键点时抬手指示，身体微微前倾，表情温暖。
3. **提醒警示型**：表情严肃，右手抬起做"注意"手势，皱眉强调，摇头表示否定，点头表示肯定。
4. **鼓励安抚型**：微笑点头，右手轻拍胸口表示理解，抬手做"没问题"手势，表情温暖。
5. **关切问答型**：微微歪头表示倾听，皱眉表示关切，右手抬起做"让我解释"手势，说完后微笑点头。
6. **指示展示型**：右手向画面一侧指示（配合动效出现），头部随手势轻微转动，眼神跟随手势然后回到镜头。

## 一致性规则

- 人物/服装/场景/光线一致。
- 场景完全静止（background remains completely static）。
- 镜头运动一致（不能同时 static 和 push in）。
- 音色参考一致（Audio 1 只 reference，不 fully_copy）。

## 默认参数

| 参数 | 默认值 |
|---|---|
| 时长 | 15 秒（H3 最大） |
| 模式 | Ref2VA（全参考） |
| 任务类型 | [reference generation + audio reference] |
| 分辨率 | adaptive（由输入图决定，竖屏 9:16） |
| 镜头 | 单镜头 [Shot 1]，静态或微幅推进 |
| 背景音乐 | N/A |
| 模型 | MiniMax-H3 |

## 用词规范

- 用具体可执行的动词+名词。
- 杜绝空泛形容词。
- 只描述图片真实可见信息，看不到的标"无法确认"。
- 输出英文（台词保留中文）。
