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
