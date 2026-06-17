// _ttHelper — bridge between hardcoded Chinese text and i18n keys
// Usage: _tt('运行中') → uses _t('nodeState.running','运行中') internally
// Safe to use anywhere: template literals, regular strings, DOM building
// No template syntax nesting issues because it's a plain function call

(function() {
  // Chinese text → i18n key mapping (built once)
  var _textToKey = null;

  function buildMap() {
    _textToKey = {
      // nodeState
      '运行中': 'nodeState.running', '成功': 'nodeState.success', '失败': 'nodeState.error',
      // node labels
      '图片节点': 'nodeType.image', '提示词节点': 'nodeType.prompt',
      '图片生成': 'nodeType.imageGen', '视频生成': 'nodeType.videoGen',
      'Agent 节点': 'nodeType.agent', '列队节点': 'nodeType.loop',
      '输出节点': 'nodeType.output', 'ComfyUI 节点': 'nodeType.comfy',
      // menu
      '选中操作': 'menu.selection', '复制 Ctrl+C': 'menu.copy',
      '粘贴 Ctrl+V': 'menu.paste', '打组 Ctrl+G': 'menu.group',
      '解组 Ctrl+Shift+G': 'menu.ungroup', '删除 Delete': 'menu.delete',
      '删除连线': 'menu.deleteConnection',
      // node body
      '替换': 'node.replace', '删除': 'node.delete', '删除节点': 'node.delete',
      '点击上传图片': 'node.clickUpload', '或从右侧资产库拖入': 'node.dragFromAsset',
      '输入提示词...': 'node.inputPrompt', '双击添加描述': 'node.dblClickDesc',
      '生成图片': 'pipeline.generateImage', '🖼 生成图片': 'pipeline.generateImage',
      '🎬 生成视频': 'pipeline.generateVideo', '🔊 有声': 'pipeline.audioOn',
      '选择智能体...': 'agent.selectAgent',
      '选择已有的智能体并输入任务要求。': 'agent.hint',
      '运行': 'common.run', '清除全部': 'common.clearAll',
      '选择工作流...': 'comfy.selectWorkflow',
      '输入端口（连接上游节点）': 'comfy.inputPort',
      '连接上游节点后点运行，自动按类型映射：图片→图片字段，文本→提示词字段。': 'comfy.hint',
      '连接提示词或图片后生成结果': 'node.hintVideoGen',
      '连接提示词或图片后生成结果，并自动写入输出节点。': 'node.hintImageGen',
      '连接上游节点后': 'node.hintOutput', '结果自动显示在这里': 'node.hintOutput2',
      '连接图片后显示': 'node.connectToShow',
      '未知节点类型': 'node.unknownType',
      // pipeline
      '已保存到资产库': 'pipeline.savedToAssets', '请选择工作流': 'pipeline.selectWorkflow',
      '图片已生成': 'pipeline.imageGenerated', '视频已生成': 'pipeline.videoGenerated',
      '生成结果': 'pipeline.resultImage', '生成视频': 'pipeline.resultVideo',
      '视频生成失败': 'pipeline.videoFailed', '视频生成超时': 'pipeline.videoTimeout',
      '请先在上方下拉框选择一个智能体': 'pipeline.selectAgent',
      '请执行任务': 'pipeline.defaultTask', '未返回图片地址': 'pipeline.noImageReturned',
      '视频任务完成但无下载地址': 'pipeline.videoDoneNoUrl',
      '管线执行中...': 'pipeline.running', '正在生成图片...': 'pipeline.generatingImage',
      '正在提交视频生成...': 'pipeline.submittingVideo',
      'Agent 执行中...': 'pipeline.agentRunning', 'Agent 输出': 'pipeline.agentOutput',
      'Agent 完成': 'pipeline.agentDone', 'Agent 失败': 'pipeline.agentFailed',
      '请求失败: ': 'pipeline.requestFailed', '生成失败: ': 'generate.failed',
      // canvas
      '默认画布': 'canvas.defaultTitle', '未命名画布': 'canvas.untitled',
      '等待编辑': 'canvas.waitingEdit', '待保存': 'canvas.pendingSave',
      '已保存': 'canvas.saved', '保存失败': 'canvas.saveFailed',
      // size
      '1:1 方形': 'size.square', '16:9 横版': 'size.wide', '9:16 竖版': 'size.tall',
      '4:3 横版': 'size.43w', '3:4 竖版': 'size.34t', '21:9 宽屏': 'size.ultrawide',
      'x2 放大': 'size.x2', 'x3 放大': 'size.x3', '自定义最长边 →': 'size.custom',
      '📎 跟随输入图': 'size.followInput', '📎 自动': 'size.auto',
      '宽': 'size.width', '高': 'size.height',
      // menu bar
      '当前状态': 'toolbar.status',
      // common
      '输入': 'assets.input', '输出': 'assets.output',
      '⬇ 下载': 'lightbox.download', '请输入访问密码': 'auth.enterPassword',
      '1:1': 'size.sq',
      '无输入（请连接图片或输入文本）': 'pipeline.noInput',
      'ComfyUI结果': 'pipeline.comfyResult', 'ComfyUI视频': 'pipeline.comfyVideo',
      '视频任务提交失败: ': 'pipeline.videoSubmitFailed',
      '画布已被其他页面更新，已刷新为最新版本。请重新尝试您的编辑。': 'canvas.conflictMessage',
      '检测中…': 'about.checking', '检查更新': 'about.checkUpdate',
      '已是最新版本 ✓': 'about.upToDate', '发现新版本: v': 'about.newVersion',
      '，可前往设置页执行更新': 'about.updateHint', '检查失败: ': 'about.checkFailed',
      '网络错误，请稍后重试': 'about.networkError',
      '加载中...': 'common.loading',
      // —— settings.html ——
      '平台列表': 'settings.platformList', '新增平台': 'settings.addPlatform',
      '浏览推荐平台': 'settings.browseRec', '安全设置': 'settings.securitySettings',
      '选择平台': 'settings.selectPlatform', '从左侧列表选择一个平台进行配置': 'settings.selectHint',
      '注册账号': 'settings.register', '验证连接': 'settings.testConn', '拉取模型': 'settings.fetchModels',
      '保存当前': 'settings.saveCurrent', '基本信息': 'settings.basicInfo',
      '平台显示名、唯一标识和请求地址': 'settings.basicInfoDesc',
      '平台名称': 'settings.platformName', '平台 ID:': 'settings.platformId',
      '协议类型': 'settings.protocol', '请求地址 (Base URL)': 'settings.baseUrl',
      'API Key': 'settings.apiKey', '获取 API Key': 'settings.getKey',
      '账户余额 API Key': 'settings.walletKey',
      '生图模型': 'settings.imageModels', '在线生图和画布 API 生成使用': 'settings.imageModelsDesc',
      '文本模型': 'settings.chatModels', 'GPT 对话和 Agent 节点使用': 'settings.chatModelsDesc',
      '视频模型': 'settings.videoModels', '画布视频生成节点使用': 'settings.videoModelsDesc',
      '访问密码和跨域来源配置': 'settings.securityDesc',
      '访问密码 (APP_API_KEY)': 'settings.appApiKey',
      '留空则不启用鉴权': 'settings.authHint',
      '设置后所有 API 请求需要携带 X-API-Key，浏览器会自动存储': 'settings.authDesc',
      '多个来源用逗号分隔': 'settings.corsHint',
      '保存全部设置': 'settings.saveAll',
      '📋 推荐平台': 'settings.recommended', '← 返回配置': 'settings.backToConfig',
      '从上游拉取的模型清单': 'settings.modelListTitle',
      '按名称搜索模型…': 'settings.searchModel',
      '全部': 'settings.all', '生图': 'settings.img', 'LLM': 'settings.llm',
      '应用到模型列表': 'settings.applyModels',
      '新增 API 平台': 'settings.newProvider',
      '唯一标识，只能使用英文、数字、下划线和连字符': 'settings.idHint',
      '🏛️ 官方 API': 'settings.official', '🔄 第三方中转': 'settings.thirdParty',
      '官方 API 直接来自模型厂商，第三方中转通过中间商转发请求': 'settings.typeHint',
      '确认新增': 'settings.confirmAdd',
      '暂无模型': 'settings.noModels', '从 API 拉取模型': 'settings.fetchModelsHint',
      '或': 'settings.or', '在下方手动添加': 'settings.addManually',
      '官网': 'settings.vendorOfficial', '第三方': 'settings.vendorThird',
      '协议:': 'settings.protocolLabel', '个模型': 'settings.modelCount',
      // —— agents.html ——
      '智能体': 'agents.title', '新建': 'agents.new',
      'Agent设计器': 'agents.designer', '描述你想要的效果，AI 帮你生成系统提示词': 'agents.designerHint',
      '快速': 'agents.quick', '深度设计': 'agents.deepDesign',
      '选择一个智能体或新建一个开始配置': 'agents.selectHint', '+ 新建智能体': 'agents.createNew',
      '基本配置': 'agents.basicConfig', '名称': 'agents.name', '平台': 'agents.platform',
      '模型': 'agents.model', '步数': 'agents.steps',
      '系统提示词': 'agents.systemPrompt',
      '技能 Skills': 'agents.skills', '知识库': 'agents.knowledgeBase',
      '文件管理': 'agents.fileManager', '+ 上传': 'agents.upload',
      '测试运行': 'agents.testRun', '+ 图片': 'agents.addImage',
      '等待输入...': 'agents.waiting', '暂无知识库': 'agents.noKb',
      '当前 Agent: ': 'agents.currentAgent', '新智能体': 'agents.newAgent',
      '创建失败: ': 'agents.createFailed', '确定删除？': 'agents.confirmDelete',
      '删除失败: ': 'agents.deleteFailed', '未命名': 'agents.unnamed',
      '应用到 Agent': 'agents.apply', '查看过程': 'agents.viewProcess',
      '思考中...': 'agents.thinking',
      // —— comfyui.html ——
      '本地 ComfyUI': 'comfyui.title', '工作流列表': 'comfyui.wfList',
      '+ 上传工作流 JSON': 'comfyui.uploadWf', '选择一个工作流开始配置': 'comfyui.selectHint',
      '工作流配置': 'comfyui.wfConfig', '保存配置': 'comfyui.saveConfig',
      '工作流名称': 'comfyui.wfName', '节点参数映射': 'comfyui.nodeMapping',
      '暴露 ComfyUI 节点参数为画布输入': 'comfyui.mappingHint',
      '自动检测参数': 'comfyui.autoDetect', '等待运行...': 'comfyui.waitingRun',
      '暂无工作流': 'comfyui.noWf', '保存成功': 'comfyui.saved',
      '保存失败: ': 'comfyui.saveFailed', '上传成功': 'comfyui.uploadOk',
      '上传失败: ': 'comfyui.uploadFailed', '运行中...': 'comfyui.running',
      '运行失败: ': 'comfyui.runFailed',
      // —— chat.html ——
      '对话历史': 'chat.convHistory', '新对话': 'chat.newConv',
      '输入消息开始对话，Enter 发送': 'chat.startHint', '发送': 'chat.send',
      '流式输出': 'chat.streamToggle', '暂无对话': 'chat.noConv',
      '输入消息开始对话，Enter 发送': 'chat.emptyHint', '对话已加载。': 'chat.loaded',
      '加载失败。': 'chat.loadFailed', '确定删除此对话？': 'chat.confirmDelete',
      '无回复': 'chat.noReply', '错误: ': 'chat.error',
      // —— canvas-gate.html ——
      '画布管理': 'gate.title', '管理所有画布，点击进入编辑': 'gate.subtitle',
      '搜索画布...': 'gate.search', '+ 新建画布': 'gate.newCanvas',
      '还没有画布，创建一个开始吧': 'gate.emptyHint',
      // —— platforms.html ——
      '推荐平台': 'platforms.title', '浏览官方和社区推荐的 AI 平台，一键添加到你的 API 设置中': 'platforms.subtitle',
      '← 返回 API 设置': 'platforms.back', '编辑平台': 'platforms.edit',
      '描述': 'platforms.desc', 'Base URL': 'platforms.baseUrl',
      '✓ 已添加': 'platforms.added', '+ 添加到我的平台': 'platforms.addToMine',
      // —— generate.html ——
      '生成参数': 'generate.params', '结果预览': 'generate.result',
      '等待生成结果': 'generate.waiting',
      '生成中...': 'generate.generating', '正在请求 API...': 'generate.requesting',
      '生成成功': 'generate.success', '生成失败: ': 'generate.failed',
      '请求失败: ': 'generate.requestFailed', '请输入提示词': 'generate.enterPrompt',
      '请选择模型': 'generate.selectModel', '该平台无可用模型': 'generate.noModels',
      '无可用平台': 'generate.noPlatforms',
      '请在 API 设置中添加生图模型': 'generate.addModels',
      // —— common.js ——
      '取消': 'common.cancel', '确定': 'common.ok', '关闭': 'common.close',
      '保存': 'common.save', '删除': 'common.delete', '运行': 'common.run',
      '清除全部': 'common.clearAll',
    };
  }

  // Simple text-based translate: looks up Chinese text → i18n key → translated text
  window._tt = function(text) {
    if (!text || typeof text !== 'string') return text;
    if (!_textToKey) buildMap();
    var key = _textToKey[text];
    if (key && typeof _t === 'function') {
      return _t(key, text);
    }
    // Try partial match for template-like strings
    return text;
  };

  // Also expose as regular function for use in template literals
  // Usage: ${_t2('运行中')} → translated text
  window._t2 = window._tt;
})();
