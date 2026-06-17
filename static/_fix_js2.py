"""Comprehensive i18n fix — add data-t to all HTML and _t() to all JS"""
import re, os

BASE = r'E:\画布\571无限画布\static'
JS = os.path.join(BASE, 'js')

def read(path):
    with open(path, 'r', encoding='utf-8') as f: return f.read()
def write(path, s):
    with open(path, 'w', encoding='utf-8') as f: f.write(s)

# ============================================================
# PART 1: canvas-renderer-nodes.js — ~40 strings
# ============================================================
path = os.path.join(JS, 'canvas-renderer-nodes.js')
s = read(path)

pairs = [
    ("""'删除节点'""", """_t('node.delete','删除节点')"""),
    ("""'替换'""", """_t('node.replace','替换')"""),
    ("""'删除'""", """_t('node.delete','删除')"""),
    ("""点击上传图片<br>或从右侧资产库拖入""", """${_t('node.clickUpload','点击上传图片')}<br>${_t('node.dragFromAsset','或从右侧资产库拖入')}"""),
    ("""placeholder="输入提示词..." """, """placeholder="${_t('node.inputPrompt','输入提示词...')}" """),
    ("""'生成图片'""", """_t('pipeline.generateImage','生成图片')"""),
    ("""'1:1 方形'""", """_t('size.square','1:1 方形')"""),
    ("""'16:9 横版'""", """_t('size.wide','16:9 横版')"""),
    ("""'9:16 竖版'""", """_t('size.tall','9:16 竖版')"""),
    ("""'4:3'""", """_t('size.43','4:3')"""),
    ("""'3:4'""", """_t('size.34','3:4')"""),
    ("""'21:9 宽屏'""", """_t('size.ultrawide','21:9 宽屏')"""),
    ("""'1:1'""", """_t('size.sq','1:1')"""),
    ("""'720p'""", """'720p'"""),
    ("""'1080p'""", """'1080p'"""),
    ("""'x2 放大'""", """_t('size.x2','x2 放大')"""),
    ("""'x3 放大'""", """_t('size.x3','x3 放大')"""),
    ("""'自定义最长边 →'""", """_t('size.custom','自定义最长边 →')"""),
    ("""'连接提示词或图片后生成结果，并自动写入输出节点。'""", """_t('node.hintImageGen','连接提示词或图片后生成结果，并自动写入输出节点。')"""),
    ("""'🖼 生成图片'""", """_t('pipeline.generateImage','🖼 生成图片')"""),
    ("""'W'""", """'W'"""),
    ("""'H'""", """'H'"""),
    ("""'宽'""", """_t('size.width','宽')"""),
    ("""'高'""", """_t('size.height','高')"""),
    ("""'连接提示词或图片后生成结果'""", """_t('node.hintVideoGen','连接提示词或图片后生成结果')"""),
    ("""'🔊 有声'""", """_t('pipeline.audioOn','🔊 有声')"""),
    ("""'🎬 生成视频'""", """_t('pipeline.generateVideo','🎬 生成视频')"""),
    ("""'选择智能体...'""", """_t('agent.selectAgent','选择智能体...')"""),
    ("""'选择已有的智能体并输入任务要求。'""", """_t('agent.hint','选择已有的智能体并输入任务要求。')"""),
    ("""'运行'""", """_t('common.run','运行')"""),
    ("""'清除全部'""", """_t('common.clearAll','清除全部')"""),
    ("""'连接上游节点后<br>结果自动显示在这里'""", """${_t('node.hintOutput','连接上游节点后')}<br>${_t('node.hintOutput2','结果自动显示在这里')}"""),
    ("""'连接图片后显示'""", """_t('node.connectToShow','连接图片后显示')"""),
    ("""'选择工作流...'""", """_t('comfy.selectWorkflow','选择工作流...')"""),
    ("""'输入端口（连接上游节点）'""", """_t('comfy.inputPort','输入端口（连接上游节点）')"""),
    ("""'连接上游节点后点运行，自动按类型映射：图片→图片字段，文本→提示词字段。'""", """_t('comfy.hint','连接上游节点后点运行，自动按类型映射：图片→图片字段，文本→提示词字段。')"""),
    ("""'未知节点类型'""", """_t('node.unknownType','未知节点类型')"""),
    ("""'📎 跟随输入图'""", """_t('size.followInput','📎 跟随输入图')"""),
    ("""'📎 自动'""", """_t('size.auto','📎 自动')"""),
]
for old, new in pairs:
    if old in s: s = s.replace(old, new); print(f'  OK: {old[:40]}')
    else: print(f'  MISS: {old[:40]}')
write(path, s)
print('canvas-renderer-nodes.js DONE\n')

# ============================================================
# PART 2: canvas-core.js — create menu & connection menu strings
# ============================================================
path = os.path.join(JS, 'canvas-core.js')
s = read(path)

pairs2 = [
    ("""'图片节点'""", """_t('nodeType.image','图片节点')"""),
    ("""'提示词节点'""", """_t('nodeType.prompt','提示词节点')"""),
    ("""'🖼 图片生成'""", """_t('nodeType.imageGen','🖼 图片生成')"""),
    ("""'🎬 视频生成'""", """_t('nodeType.videoGen','🎬 视频生成')"""),
    ("""'Agent 节点'""", """_t('nodeType.agent','Agent 节点')"""),
    ("""'列队节点'""", """_t('nodeType.loop','列队节点')"""),
    ("""'输出节点'""", """_t('nodeType.output','输出节点')"""),
    ("""'ComfyUI 节点'""", """_t('nodeType.comfy','ComfyUI 节点')"""),
    ("""'选中操作'""", """_t('menu.selection','选中操作')"""),
    ("""'复制 Ctrl+C'""", """_t('menu.copy','复制 Ctrl+C')"""),
    ("""'粘贴 Ctrl+V'""", """_t('menu.paste','粘贴 Ctrl+V')"""),
    ("""'打组 Ctrl+G'""", """_t('menu.group','打组 Ctrl+G')"""),
    ("""'解组 Ctrl+Shift+G'""", """_t('menu.ungroup','解组 Ctrl+Shift+G')"""),
    ("""'删除 Delete'""", """_t('menu.delete','删除 Delete')"""),
    ("""'删除连线'""", """_t('menu.deleteConnection','删除连线')"""),
    ("""'画布已被其他页面更新，已刷新为最新版本。请重新尝试您的编辑。'""", """_t('canvas.conflictMessage','画布已被其他页面更新，已刷新为最新版本。请重新尝试您的编辑。')"""),
]
for old, new in pairs2:
    if old in s: s = s.replace(old, new); print(f'  OK: {old[:40]}')
    else: print(f'  MISS: {old[:40]}')
write(path, s)
print('canvas-core.js DONE\n')

# ============================================================
# PART 3: canvas-pipeline.js — remaining strings
# ============================================================
path = os.path.join(JS, 'canvas-pipeline.js')
s = read(path)

pairs3 = [
    ("""'无输入（请连接图片或输入文本）'""", """_t('pipeline.noInput','无输入（请连接图片或输入文本）')"""),
    ("""'ComfyUI结果'""", """_t('pipeline.comfyResult','ComfyUI结果')"""),
    ("""'ComfyUI视频'""", """_t('pipeline.comfyVideo','ComfyUI视频')"""),
    ("""'管线执行中...'""", """_t('pipeline.running','管线执行中...')"""),
    ("""'正在生成图片...'""", """_t('pipeline.generatingImage','正在生成图片...')"""),
    ("""'正在提交视频生成...'""", """_t('pipeline.submittingVideo','正在提交视频生成...')"""),
    ("""'视频任务提交失败: '""", """_t('pipeline.videoSubmitFailed','视频任务提交失败: ')"""),
    ("""'Agent 执行中...'""", """_t('pipeline.agentRunning','Agent 执行中...')"""),
    ("""'Agent 输出'""", """_t('pipeline.agentOutput','Agent 输出')"""),
    ("""'Agent 完成'""", """_t('pipeline.agentDone','Agent 完成')"""),
    ("""'Agent 失败'""", """_t('pipeline.agentFailed','Agent 失败')"""),
    ("""'请求失败: '""", """_t('pipeline.requestFailed','请求失败: ')"""),
]
for old, new in pairs3:
    if old in s: s = s.replace(old, new); print(f'  OK: {old[:40]}')
    else: print(f'  MISS: {old[:40]}')

# Fix template literal _t() wrapping for dynamic messages
s = s.replace("`完成 ${count} 次`", "`${_t('pipeline.completed','完成')} ${count} ${_t('pipeline.times','次')}`")
s = s.replace("`上传失败: ${error.message}`", "`${_t('pipeline.uploadFailed','上传失败')}: ${error.message}`")
s = s.replace("`保存失败: ' + e.message`", "`${_t('canvas.saveFailed','保存失败')}: ${e.message}`")
s = s.replace("`视频生成中 (${pollData.progress || i * 3}s)...`", "`${_t('pipeline.videoGenerating','视频生成中')} (${pollData.progress || i * 3}s)...`")

write(path, s)
print('canvas-pipeline.js DONE\n')

print('=== All JS files processed ===')
