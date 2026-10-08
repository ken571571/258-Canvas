// canvas-pipeline.js — pipeline / execution methods
// Prototype extension pattern: attach each method to CanvasEngine.prototype

// ============================================================
// Class-level data fields
// ============================================================

CanvasEngine.prototype._activeComfyAbort = null;  // 独立运行 ComfyUI 的兜底控制器（链上下文缺位时）

// v2.5.70：链级执行上下文注册表——每条运行中的链一个 ctx（独立 AbortController + 去重集合），
// 多链并发互不干扰；节点「取消」只中止所在链，全局「停止」/ESC 中止全部。
// ctx 结构：{ id, rootId, abort, signal, ranAgents, loopRanAgents, nodes }
CanvasEngine.prototype._activeChains = new Map(); // ctx.id -> ctx

// 视频模型时长和分辨率参数 —— 运行时由 _loadVideoModelParams() 从 GET /api/video/model-params 填充
CanvasEngine.prototype._videoDurations = {};
CanvasEngine.prototype._videoResolutions = {};
CanvasEngine.prototype._videoPollMaxRetries = 80;

// ============================================================
// Pipeline / execution methods
// ============================================================

CanvasEngine.prototype._handleImageUpload = async function(id, input) {
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        const response = await apiFetch('/api/upload', { method: 'POST', body: form });
        const data = await response.json();
        const node = this.nodes.find(item => item.id === id);
        if (!node) return;
        node.url = data.url;
        node.imageName = data.name || '';
        // 同步 Store + 自动调整节点高度（上传时服务器返回尺寸）
        if (data.width && data.height) {
            this._syncImageNodeSize(node, data.width, data.height);
        } else {
            this.store.updateNode(id, { url: data.url, imageName: node.imageName });
        }
        this._renderAll();
        this._markDirty();
    } catch (error) {
        alert((typeof _t !== 'undefined' ? _t('pipeline.uploadFailed','上传失败') : '上传失败') + ': ' + error.message);
    }
};

CanvasEngine.prototype._handleAudioUpload = async function(id, input) {
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        const response = await apiFetch('/api/upload', { method: 'POST', body: form });
        const data = await response.json();
        const node = this.nodes.find(item => item.id === id);
        if (!node) return;
        node.url = data.url;
        node.imageName = data.name || '';
        this.store.updateNode(id, { url: data.url, imageName: node.imageName });
        this._renderAll();
        this._markDirty();
    } catch (error) {
        alert((typeof _t !== 'undefined' ? _t('pipeline.uploadFailed','上传失败') : '上传失败') + ': ' + error.message);
    }
};

CanvasEngine.prototype._collectInputs = function(nodeId) {
    var texts = [];
    var images = [];
    var videos = [];
    var audios = [];
    var seenLoop = {};  // 防止 loop 多端口连线导致重复收集

    this.connections
        .filter(function(connection) { return connection.to === nodeId; })
        .forEach(function(connection) {
            var from = this.nodes.find(function(node) { return node.id === connection.from; });
            if (!from) return;
            var tag = connection.fieldId || '';
            if (from.type === 'prompt' && from.text) texts.push(tag ? tag+'::'+from.text : from.text);
            if (from.type === 'agent' && from.lastResult) texts.push(tag ? tag+'::'+from.lastResult : from.lastResult);
            // 输出节点是终端展示节点，内容不流入下游管线
            if (from.type === 'image' && from.url) {
                var u = from.url;
                if (/\.(mp4|webm|mov|m4v)$/i.test(u)) videos.push(tag ? tag+'::'+u : u);
                else images.push(tag ? tag+'::'+u : u);
            }
            // v2.5.67：输出节点产物可沿连线流入下游（支持组间直连；role 由连线 fieldId 标签携带）
            if (from.type === 'output') {
                (from.images || []).forEach(function(it) {
                    var u = (it && it.url) || it;
                    if (u) images.push(tag ? tag + '::' + u : u);
                });
                (from.videos || []).forEach(function(it) {
                    var u = (it && it.url) || it;
                    if (u) videos.push(tag ? tag + '::' + u : u);
                });
            }
            // v2.5.59：音频节点连线 → 音频参考（如 MiniMax-H3 r2va 音频驱动）
            if (from.type === 'audio' && from.url) {
                var au = from.url;
                audios.push(tag ? tag+'::'+au : au);
            }
            if (from.type === 'loop') {
                var bs = from._batchSize || 1;
                var start = from._cursorImg || 0;
                var total = from._queue ? from._queue.length : 0;
                var txtCount = from._textSegments ? from._textSegments.length : 0;
                // v2.5.53：图片只收集一次（seenLoop 去重），文本每条连线都收集（支持多端口 fieldId 路由）
                if (!seenLoop[from.id]) {
                    seenLoop[from.id] = true;
                    if (total > 0) {
                        if (txtCount > 0) {
                            var effective = total - (total % bs);
                            if (effective > 0) {
                                for (var j = 0; j < bs; j++) {
                                    var idx = (start + j) % effective;
                                    var item = from._queue[idx];
                                    if (item && item.url) images.push(tag ? tag+'::'+item.url : item.url);
                                }
                            }
                        } else {
                            var slice = from._queue.slice(start, start + bs);
                            slice.forEach(function(item) { if (item.url) images.push(tag ? tag+'::'+item.url : item.url); });
                        }
                    }
                }
                // 文本：每条连线独立收集，允许不同 fieldId 路由同一文本段到不同工作流字段
                if (txtCount > 0) {
                    var ct = from._cursorTxt || 0;
                    if (ct < txtCount) texts.push(tag ? tag+'::'+from._textSegments[ct] : from._textSegments[ct]);
                }
            }
        }, this);

    return { texts, images, videos, audios };
};

CanvasEngine.prototype._clearOutput = function(nodeId) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node) return;
    node.outputText = '';
    node.images = [];
    node.videos = [];
    this._syncOutputToStore(node);  // 持久化清空（save() 只同步位置，内容靠此方法）
    this._renderAll();
    this._markDirty();
};

CanvasEngine.prototype._removeOutputItem = function(nodeId, index, type) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const arr = type === 'image' ? node.images : node.videos;
    if (arr && index < arr.length) arr.splice(index, 1);
    this._syncOutputToStore(node);  // 持久化删除
    this._renderAll();
    this._markDirty();
};

CanvasEngine.prototype._loadOutputDimensions = function(node) {
    // 异步加载输出项的图片/视频尺寸并缓存到 item._w/_h
    // 使用 rAF 批量渲染：多图并发加载时避免每图一次 _renderAll
    var pendingRender = false;
    var self = this;
    var scheduleRender = function() {
        if (pendingRender) return;
        // ComfyUI 异步轮询期间跳过 rAF 全量渲染，避免与用户拖拽交互冲突
        if (self._activeComfyAbort && !self._activeComfyAbort.signal.aborted) return;
        pendingRender = true;
        requestAnimationFrame(function() {
            pendingRender = false;
            self._renderAll();
        });
    };
    (node.images || []).forEach((item, i) => {
        const url = typeof item === 'string' ? item : (item.url || '');
        if (!url || (typeof item === 'object' && item._w)) return;
        if (/\.(png|jpg|jpeg|webp|gif)$/i.test(url)) {
            const img = new Image();
            img.onload = () => {
                if (!self.nodes.some(function(n) { return n.id === node.id; })) return;
                if (node.images[i]) {
                    if (typeof node.images[i] === 'string') node.images[i] = { url: node.images[i] };
                    node.images[i]._w = img.naturalWidth;
                    node.images[i]._h = img.naturalHeight;
                    self.store.updateNode(node.id, { images: node.images.slice() });
                    scheduleRender();
                }
            };
            img.src = url;
        }
    });
    (node.videos || []).forEach((item, i) => {
        const url = typeof item === 'string' ? item : (item.url || '');
        if (!url || (typeof item === 'object' && item._w)) return;
        const vid = document.createElement('video');
        vid.preload = 'metadata';
        vid.onloadedmetadata = () => {
            if (!self.nodes.some(function(n) { return n.id === node.id; })) return;
            if (node.videos[i]) {
                if (typeof node.videos[i] === 'string') node.videos[i] = { url: node.videos[i] };
                node.videos[i]._w = vid.videoWidth;
                node.videos[i]._h = vid.videoHeight;
                self.store.updateNode(node.id, { videos: node.videos.slice() });
                scheduleRender();
            }
        };
        vid.src = url;
    });
};

CanvasEngine.prototype._saveOutputAsset = async function(url) {
    if (!url) return;
    // 已是本地服务器文件 → 直接打开资产库定位
    if (url.startsWith('/output/') || url.startsWith('/input/')) {
        this._openAssetPanelTo(url.startsWith('/output/') ? 'output' : 'input');
        return;
    }
    // 外部 URL → 下载后存入资产库 input/
    try {
        const resp = await fetch(url);
        const blob = await resp.blob();
        const form = new FormData();
        const ext = url.split('.').pop()?.split('?')[0] || 'png';
        form.append('file', blob, 'saved_' + Date.now() + '.' + ext);
        await apiFetch('/api/upload', { method: 'POST', body: form });
        if (typeof this._loadAssets === 'function') this._loadAssets('input');
        alert(_t('pipeline.savedToAssets','已保存到资产库'));
    } catch(e) { alert((typeof _t !== 'undefined' ? _t('pipeline.saveFailed','保存失败') : '保存失败') + ': ' + e.message); }
};

/** 打开资产面板并切换到指定标签（'input' | 'output'） */
CanvasEngine.prototype._openAssetPanelTo = function(dir) {
    const panel = document.getElementById('asset-panel');
    if (panel && !panel.classList.contains('open')) panel.classList.add('open');
    if (typeof this._loadAssets === 'function') this._loadAssets(dir || 'output');
};

CanvasEngine.prototype._updateGroupLabel = function(groupId, value) {
    const g = this.groups.find(x => x.id === groupId);
    if (g) { g.label = value.trim().slice(0, 40); this._markDirty(); }
};

CanvasEngine.prototype._removeLoopItem = function(nodeId, index) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node?._queue || index >= node._queue.length) return;
    const removed = node._queue.splice(index, 1)[0];
    // 仅对上游来源的项记录移除（手动拖入的不会被上游自动加回，不需记录）
    if (removed._src !== 'manual') {
        if (!node._removedUrls) node._removedUrls = [];
        if (!node._removedUrls.includes(removed.url)) node._removedUrls.push(removed.url);
    }
    this.store.updateNode(nodeId, { _queue: node._queue.slice(), _removedUrls: (node._removedUrls||[]).slice() });
    this.store._dirty.all = true;
    this._markDirty();
    requestAnimationFrame(() => this._renderAll());
};

CanvasEngine.prototype._moveLoopItem = function(nodeId, index, dir) {
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node || !node._queue) return;
    var newIdx = index + dir;
    if (newIdx < 0 || newIdx >= node._queue.length) return;
    var item = node._queue.splice(index, 1)[0];
    node._queue.splice(newIdx, 0, item);
    this.store.updateNode(nodeId, { _queue: node._queue.slice() });
    this.store._dirty.all = true;  // 强制全量重建（队列重排需要重建 HTML，快速路径只更新位置不够）
    this._renderAll();
};

CanvasEngine.prototype._reorderLoopQueue = function(nodeId, e) {
    e = e || window.event; if (!e) return;
    e.preventDefault();
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node || !node._queue || node._queue.length < 2) return;
    const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
    if (isNaN(fromIdx) || fromIdx >= node._queue.length) return;
    const container = document.getElementById('loop-queue-' + nodeId);
    if (!container) return;
    const thumbs = [...container.querySelectorAll('.loop-thumb')];
    let toIdx = fromIdx;
    for (let i = 0; i < thumbs.length; i++) {
        const rect = thumbs[i].getBoundingClientRect();
        if (e.clientX < rect.left + rect.width / 2) { toIdx = i; break; }
        toIdx = thumbs.length - 1;
    }
    if (fromIdx === toIdx) return;
    const item = node._queue.splice(fromIdx, 1)[0];
    node._queue.splice(toIdx, 0, item);
    this.store.updateNode(nodeId, { _queue: node._queue.slice() });
    this.store._dirty.all = true;
    this._renderAll();
    this._markDirty();
};

// ——— Loop 拖拽 ———

CanvasEngine.prototype._onLoopDragStart = function(event, nodeId, index) {
    event.dataTransfer.setData('text/plain', JSON.stringify({ loopNodeId: nodeId, fromIndex: index }));
    event.dataTransfer.effectAllowed = 'move';
    event.currentTarget.style.opacity = '0.5';
};

CanvasEngine.prototype._onLoopDrop = function(event, nodeId) {
    event.preventDefault();
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!node._queue) node._queue = [];
    try {
        var raw = event.dataTransfer.getData('text/plain');
        if (!raw) return;
        var data = JSON.parse(raw);
        // 内部排序：同一节点的拖拽
        if (data.loopNodeId === nodeId && typeof data.fromIndex === 'number') {
            var fromIdx = data.fromIndex;
            if (fromIdx >= node._queue.length) return;
            var container = document.getElementById('loop-queue-' + nodeId);
            if (!container) return;
            var thumbs = container.querySelectorAll('.loop-thumb');
            var toIdx = fromIdx;
            for (var i = 0; i < thumbs.length; i++) {
                var rect = thumbs[i].getBoundingClientRect();
                if (event.clientX < rect.left + rect.width / 2) { toIdx = i; break; }
                toIdx = thumbs.length - 1;
            }
            if (fromIdx !== toIdx) {
                var item = node._queue.splice(fromIdx, 1)[0];
                node._queue.splice(toIdx, 0, item);
                this.store.updateNode(nodeId, { _queue: node._queue.slice() });
                this.store._dirty.all = true;
                this._renderAll();
                this._markDirty();
            }
        } else if (data.url) {
            // 外部拖入：图片 URL（标记 _src 防止上游同步时误删）
            if (!node._queue.some(function(q) { return q.url === data.url; })) {
                node._queue.push({ url: data.url, id: 'q_' + Date.now() + Math.random(), _src: 'manual' });
                this.store.updateNode(nodeId, { _queue: node._queue.slice() });
                this.store._dirty.all = true;
                this._renderAll();
                this._markDirty();
            }
        }
    } catch(e) { console.warn('loop drag drop failed', e); }
};

// ——— Loop 执行引擎 ———

// v2.5.73：列队文本统一分段（执行与 UI 预览共用），三级回退：
//          1) 优先 ---- 分隔（项目强约束格式）
//          2) 失败时识别「独立分隔行」：一行仅由 3+ 个 - = _ * — 组成（如 markdown 的 --- 或中文 ——）
//          3) 再失败回退空行分段（Agent 未必每次遵守 ---- 约束，可能只用空行分段）
CanvasEngine.prototype._splitLoopSegments = function(raw) {
    var s = String(raw || '');
    var segs = s.split('----').map(function(x) { return x.trim(); }).filter(Boolean);
    if (segs.length > 1) return segs;
    // 分隔行必须整行只有分隔字符（两侧可空白），行内混有文字（如「——因为」）不会误切
    segs = s.split(/\n\s*[-=_*—]{3,}\s*\n/).map(function(x) { return x.trim(); }).filter(Boolean);
    if (segs.length > 1) return segs;
    return s.split(/\n\s*\n+/).map(function(x) { return x.trim(); }).filter(Boolean);
};

CanvasEngine.prototype._runLoop = async function(nodeId, visited, ctx) {
    var self = this;
    ctx = self._ensureCtx(ctx, nodeId);
    ctx.nodes.add(nodeId);
    var node = self.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!node._queue) node._queue = [];
    if (!node._textSegments) node._textSegments = [];
    // v2.5.52：快照防竞态 — await 期间用户可能添加/删除队列项，快照确保执行期间数据一致
    var execQueue = node._queue.slice();
    var execTexts = node._textSegments.slice();
    // v2.5.74：快照前预执行上游未跑 agent —— 修复时序缺陷：旧逻辑在批次内才跑 agent，
    //          文本快照永远是上一轮陈旧 lastResult（列队异常出图根因之二）。
    //          与 comfy 分支同款去重（ctx.ranAgents / ctx.loopRanAgents），批次内不会重跑。
    var upIds = self._upstreamOrder(nodeId);
    for (var ui = 0; ui < upIds.length; ui++) {
        var un = self.nodes.find(function(n) { return n.id === upIds[ui]; });
        if (!un || un.type !== 'agent') continue;
        if (visited.has(un.id)) continue;
        if (ctx.ranAgents.has(un.id) || (ctx.loopRanAgents && ctx.loopRanAgents.has(un.id))) continue;
        if (ctx.signal.aborted || node._cancelled) {
            self._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            self._renderAll(); self._markDirty(); return;
        }
        ctx.ranAgents.add(un.id);
        await self._runAgent(un.id, ctx);
        if (ctx.loopRanAgents) ctx.loopRanAgents.add(un.id);
        if (un.runState === 'cancelled') {
            self._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            self._renderAll(); self._markDirty(); return;
        }
        if (un.runState === 'error') {
            // v2.5.74：上游失败不开批，防止空/垃圾数据进入队列出图
            self._setNodeRunState(node, 'error', _t('pipeline.upstreamFailed','上游 Agent 执行失败，列队未开批'));
            self._renderAll(); self._markDirty(); return;
        }
    }
    // v2.5.53：收集上游文本并剥离 fieldId 标签，防止标签泄漏到 _textSegments
    var upstreamTexts = self._collectInputs(nodeId).texts.map(function(t) {
        var parts = String(t).split('::');
        return parts.length >= 2 ? parts.slice(1).join('::') : t;
    });
    // v2.5.73：统一分段（---- → 分隔行 → 空行，见 _splitLoopSegments）
    if (upstreamTexts.length) {
        execTexts = self._splitLoopSegments(upstreamTexts.join('\n'));
    }
    // 执行期间将 node 指向快照，确保所有下游读取一致
    node._queue = execQueue;
    node._textSegments = execTexts;
    if (!execQueue.length && !execTexts.length) {
        self._setNodeRunState(node, 'error',  _t('pipeline.loopEmpty','队列和文本均为空'));
        return;
    }
    // 收集所有直接下游可执行节点（去重：ComfyUI 多端口会产生多条连线到同一节点）
    var dsMap = {};
    var downstreams = [];
    self.connections
        .filter(function(c) { return c.from === nodeId; })
        .forEach(function(c) {
            var n = self.nodes.find(function(x) { return x.id === c.to; });
            if (n && self._isExecutable(n) && !dsMap[n.id]) {
                dsMap[n.id] = true;
                downstreams.push(n);
            }
        });
    if (!downstreams.length) {
        self._setNodeRunState(node, 'error', _t('pipeline.downstreamNotFound','No downstream generator found'));
        return;
    }
    var batchSize = node._batchSize || 1;
    var totalImages = node._queue.length;
    var totalTexts = node._textSegments.length;
    // v2.5.52：文本驱动/图片驱动双模式
    var txtDriven = totalTexts > 0;
    var imgDriven = !txtDriven && totalImages > 0;
    var batchCount = txtDriven ? totalTexts : (imgDriven ? Math.floor(totalImages / batchSize) : 0);
    if (!batchCount) {
        self._setNodeRunState(node, 'error',  _t('pipeline.loopEmpty','队列和文本均为空'));
        return;
    }
    // v2.5.74：调试日志（排查列队出图问题；控制台按 [loop] 过滤）
    console.log('[loop] ' + nodeId + ' segments=' + totalTexts + ' queueImgs=' + totalImages
        + ' batchSize=' + batchSize + ' batches=' + batchCount + ' txtDriven=' + txtDriven,
        execTexts.slice(0, 5));
    // 计算有效图片数（可被 batchSize 整除的部分）和剩余
    var effectiveImages = totalImages - (totalImages % batchSize);
    node._cursorImg = 0;
    node._cursorTxt = 0;
    node._cancelled = false;
    self._setNodeRunState(node, 'running', _t('pipeline.batchStart','开始批次处理...'));
    node._runCtx = ctx;  // v2.5.71：登记运行归属（取消级联防并发链互染）
    self._renderAll();
    // v2.5.56：本 loop 的"已跑 agent"集合——跨批次去重直接挂生成器上游的 agent。
    // v2.5.70：集合挂在链上下文上（ctx.loopRanAgents），嵌套 loop 继承父集合，退出时恢复父值；
    //          并发链各自持有，互不污染。
    var _prevRanAgents = ctx.loopRanAgents;
    ctx.loopRanAgents = _prevRanAgents ? new Set(_prevRanAgents) : new Set();
    try {
    for (var b = 0; b < batchCount; b++) {
        // v2.5.70：链被取消（节点取消/全局停止/ESC）或 loop 专用取消 → 立即退出批次循环
        if (node._cancelled || ctx.signal.aborted) {
            self._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            self._renderAll(); self._markDirty(); return;
        }
        // v2.5.72：批次进度写入 meta（badge 显示「调度中」，同屏只有下游执行节点显示「运行中」）
        self._setNodeRunState(node, 'running', _t('pipeline.batchProgress','批次 {i}/{n} · 下游执行中').replace('{i}', b + 1).replace('{n}', batchCount));
        // 设置当前批次游标
        if (txtDriven && effectiveImages > 0) {
            node._cursorImg = (b * batchSize) % effectiveImages;  // 循环取图起点
        } else if (imgDriven) {
            node._cursorImg = b * batchSize;  // 线性取图起点
        }
        node._cursorTxt = txtDriven ? b : 0;
        // 触发下游
        var triggered = {};
        var batchFailed = false;
        var batchVisited = new Set(visited);
        for (var d = 0; d < downstreams.length; d++) {
            if (!triggered[downstreams[d].id]) {
                await self._executeFrom(downstreams[d].id, batchVisited, ctx);
                self._markTriggered(downstreams[d].id, triggered);
                var ds = self.nodes.find(function(n) { return n.id === downstreams[d].id; });
                var descIds = self._findDownstream(downstreams[d].id);
                var hasError = (ds && ds.runState === 'error');
                for (var di = 0; di < descIds.length && !hasError; di++) {
                    var desc = self.nodes.find(function(n) { return n.id === descIds[di]; });
                    if (desc && desc.runState === 'error') { hasError = true; ds = desc; }
                }
                if (hasError) { batchFailed = true; break; }
            }
        }
        if (node._cancelled || ctx.signal.aborted) {
            self._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            self._renderAll(); self._markDirty(); return;
        }
        if (batchFailed) {
            var errMsg = (ds && ds.runMessage) || _t('pipeline.downstreamErrorStopped','下游节点出错，已停止');
            self._setNodeRunState(node, 'error', errMsg);
            self._renderAll(); self._markDirty(); return;
        }
    }
    self._setNodeRunState(node, 'success', _t('pipeline.batchComplete','完成 图片{cursorImg}/{queueLen} 张 · 文本{cursorTxt}/{textLen}段').replace('{cursorImg}',node._cursorImg).replace('{queueLen}',totalImages).replace('{cursorTxt}',node._cursorTxt).replace('{textLen}',totalTexts));
    self._renderAll(); self._markDirty();
    } finally {
        ctx.loopRanAgents = _prevRanAgents;
    }
};

CanvasEngine.prototype._cancelLoop = function(nodeId) {
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    node._cancelled = true;
    this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
    this.cancelPipeline();
};

CanvasEngine.prototype._cancelComfyUI = function(nodeId) {
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
    this.cancelPipeline();
    // 向上查找 Loop 节点并通知停止（P0-6：取消 ComfyUI 需传播到父 Loop）
    var self = this;
    var upstreamIds = self._findUpstream(nodeId);
    for (var i = 0; i < upstreamIds.length; i++) {
        var n = self.nodes.find(function(x) { return x.id === upstreamIds[i]; });
        if (n && n.type === 'loop') {
            n._cancelled = true;
        }
    }
};

CanvasEngine.prototype._findDownstream = function(nodeId, visited = new Set()) {
    if (visited.has(nodeId)) return [];
    visited.add(nodeId);
    const ids = [];
    this.connections
        .filter(c => c.from === nodeId)
        .forEach(c => { ids.push(c.to); ids.push(...this._findDownstream(c.to, visited)); });
    return ids;
};

CanvasEngine.prototype._findUpstream = function(nodeId, visited = new Set()) {
    if (visited.has(nodeId)) return [];
    visited.add(nodeId);
    const ids = [];
    this.connections
        .filter(c => c.to === nodeId)
        .forEach(c => { ids.push(c.from); ids.push(...this._findUpstream(c.from, visited)); });
    return ids;
};

CanvasEngine.prototype._upsertOutputFromNode = function(sourceId, payload) {
    const outputNode = this._ensureOutput(sourceId);
    if (!outputNode) return null;
    if (payload.text !== undefined) outputNode.outputText = payload.text;
    if (payload.images) outputNode.images = [...(outputNode.images || []), ...payload.images].slice(-50);
    if (payload.videos) outputNode.videos = [...(outputNode.videos || []), ...payload.videos].slice(-50);
    this._syncOutputToStore(outputNode);
    this._renderAll();
    this._loadOutputDimensions(outputNode);
    return outputNode;
};

CanvasEngine.prototype._getVideoDurations = function(model) {
    if (!model) return [5, 8, 10];
    if (this._videoDurations[model]) return this._videoDurations[model];
    // 模糊匹配：最长前缀匹配（处理火山模型名带日期后缀，如 doubao-seedance-1-0-pro-250528）
    let best = null;
    for (const key in this._videoDurations) {
        if (model.startsWith(key) && (!best || key.length > best.length)) best = key;
    }
    return best ? this._videoDurations[best] : [5, 8, 10];
};

CanvasEngine.prototype._getVideoResolutions = function(model) {
    if (!model) return [{v:'720p',l:'720p'},{v:'1080p',l:'1080p'},{v:'1280x720',l:'1280x720'}];
    if (this._videoResolutions[model]) return this._videoResolutions[model];
    // 模糊匹配：最长前缀匹配
    let best = null;
    for (const key in this._videoResolutions) {
        if (model.startsWith(key) && (!best || key.length > best.length)) best = key;
    }
    return best ? this._videoResolutions[best] : [{v:'720p',l:'720p'},{v:'1080p',l:'1080p'},{v:'1280x720',l:'1280x720'}];
};

CanvasEngine.prototype._upstreamOrder = function(nodeId, visited = new Set()) {
    if (visited.has(nodeId)) return [];
    visited.add(nodeId);
    const result = [];
    const incoming = this.connections.filter(c => c.to === nodeId);
    for (const c of incoming) result.push(...this._upstreamOrder(c.from, visited));
    const ups = incoming.map(c => this.nodes.find(n => n.id === c.from)).filter(Boolean);
    for (const n of ups) { if (!result.includes(n.id)) result.push(n.id); }
    return result;
};

// ——— 统一执行引擎 ———
var _EXEC_TYPES = {agent:1, image_gen:1, video_gen:1, comfy:1, loop:1, prompt:1};

CanvasEngine.prototype._isExecutable = function(node) {
    return node && _EXEC_TYPES[node.type];
};

CanvasEngine.prototype._findChainRoot = function(nodeId, visited) {
    visited = visited || new Set();
    if (visited.has(nodeId)) return nodeId;
    visited.add(nodeId);
    var self = this;
    // v2.5.68：穿透数据节点（image/audio/output/prompt）回溯到真正的可执行根节点，
    // 使跨组连线（如 output→agent）能被纳入同一条执行链。
    var execUp = this._nearestExecutableUpstream(nodeId, new Set());
    if (execUp) return this._findChainRoot(execUp, visited);
    // 没有可执行上游：当前可执行节点就是根
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (node && self._isExecutable(node)) return nodeId;
    return nodeId;
};

// v2.5.68：BFS 穿透数据节点，找到最近的可执行上游节点（无则返回 null）
CanvasEngine.prototype._nearestExecutableUpstream = function(nodeId, traversed) {
    traversed = traversed || new Set();
    if (traversed.has(nodeId)) return null;
    traversed.add(nodeId);
    var self = this;
    var ups = this.connections
        .filter(function(c) { return c.to === nodeId; })
        .map(function(c) { return self.nodes.find(function(n) { return n.id === c.from; }); })
        .filter(Boolean);
    for (var i = 0; i < ups.length; i++) {
        if (self._isExecutable(ups[i])) return ups[i].id;
    }
    for (var i = 0; i < ups.length; i++) {
        var deeper = this._nearestExecutableUpstream(ups[i].id, traversed);
        if (deeper) return deeper;
    }
    return null;
};

// v2.5.68：穿透数据节点，收集当前节点所有可达的可执行下游节点（BFS，带环路保护）。
// 用于跨组自动串联：image_gen→output→agent 这种"数据节点隔档"的下游能被触发。
CanvasEngine.prototype._nextExecutableDownstreams = function(nodeId, traversed) {
    traversed = traversed || new Set();
    if (traversed.has(nodeId)) return [];
    traversed.add(nodeId);
    var self = this;
    var result = [];
    var directDowns = this.connections
        .filter(function(c) { return c.from === nodeId; })
        .map(function(c) { return self.nodes.find(function(n) { return n.id === c.to; }); })
        .filter(Boolean);
    directDowns.forEach(function(n) {
        if (self._isExecutable(n)) {
            if (!result.some(function(x) { return x.id === n.id; })) result.push(n);
        } else {
            // 数据节点（image/audio/output/prompt）→ 穿透继续向下找
            self._nextExecutableDownstreams(n.id, traversed).forEach(function(d) {
                if (!result.some(function(x) { return x.id === d.id; })) result.push(d);
            });
        }
    });
    return result;
};

// ——— v2.5.70：链级执行上下文（chain context）辅助方法 ———

// 创建并注册一条链的执行上下文（独立 AbortController，取消只影响本链）
CanvasEngine.prototype._createChainCtx = function(rootId) {
    var ctx = {
        id: 'chain_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8),
        rootId: rootId || '',
        abort: new AbortController(),
        ranAgents: new Set(),      // 链级已跑 agent 去重（原 _chainRanAgents）
        loopRanAgents: null,       // 由 _runLoop 管理（保存/恢复，嵌套继承）
        nodes: new Set()           // 链已触及的节点（节点级取消定位用）
    };
    ctx.signal = ctx.abort.signal;
    this._activeChains.set(ctx.id, ctx);
    return ctx;
};

// 注销链上下文（仅当未被替换）
CanvasEngine.prototype._removeChainCtx = function(ctx) {
    if (ctx && ctx.id && this._activeChains.get(ctx.id) === ctx) {
        this._activeChains.delete(ctx.id);
    }
};

// 防御兜底：调用方未传 ctx 时创建临时上下文（不注册，无法被取消定位，仅保证信号可用）
CanvasEngine.prototype._ensureCtx = function(ctx, rootId) {
    if (ctx) return ctx;
    var c = { id: '', rootId: rootId || '', abort: new AbortController(), ranAgents: new Set(), loopRanAgents: null, nodes: new Set() };
    c.signal = c.abort.signal;
    return c;
};

// 按节点定位所在链：链根命中优先，其次取已触及该节点的链（多链命中时取最后注册的）
CanvasEngine.prototype._findChainCtxByNode = function(nodeId) {
    var self = this;
    var hit = null;
    this._activeChains.forEach(function(ctx) {
        if (ctx.rootId === nodeId) hit = ctx;
    });
    if (!hit) {
        this._activeChains.forEach(function(ctx) {
            if (ctx.nodes.has(nodeId)) hit = ctx;
        });
    }
    return hit;
};

// 点击任意节点 [运行] → 从链起点执行到终点
CanvasEngine.prototype._executeChain = async function(nodeId) {
    // v2.5.70：链级执行上下文——每条链独立 AbortController + ranAgents 去重，
    // 多链并发互不干扰；节点「取消」只中止所在链，全局「停止」/ESC 中止全部。
    var rootId = this._findChainRoot(nodeId);
    // v2.5.71：防重复启动——同一链已在运行则忽略本次点击（防双击/并发双跑同一链）
    var busy = false;
    this._activeChains.forEach(function(c) { if (c.rootId === rootId) busy = true; });
    if (busy) { console.warn('[canvas] chain already running, ignored:', rootId); return; }
    var ctx = this._createChainCtx(rootId);
    try {
        ctx.nodes.add(rootId);
        return await this._executeFrom(rootId, new Set(), ctx);
    } finally {
        this._removeChainCtx(ctx);
    }
};

// 标记节点及其所有下游为"已触发"（防止 loop 重复执行同一链上的节点）
CanvasEngine.prototype._markTriggered = function(nodeId, triggered) {
    if (triggered[nodeId]) return;  // 环路保护
    triggered[nodeId] = true;
    var self = this;
    this.connections
        .filter(function(c) { return c.from === nodeId; })
        .forEach(function(c) { self._markTriggered(c.to, triggered); });
};

// 从某个节点开始执行，递归向下游传播
CanvasEngine.prototype._executeFrom = async function(nodeId, visited, ctx) {
    var self = this;
    // v2.5.70：链级上下文贯穿（防御兜底：缺位时用临时 ctx，仅保证信号可用）
    ctx = self._ensureCtx(ctx, nodeId);
    // 环路保护：同一链上不重复执行
    if (!visited) visited = new Set();
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    var node = self.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!self._isExecutable(node)) return;

    // v2.5.70：登记链已触及节点（节点级取消定位用）
    ctx.nodes.add(nodeId);

    if (node.type === 'agent') {
        // 链级去重：若已被 _runPipeline/comfy 内部跑过则跳过（菱形汇聚场景）
        if (ctx.ranAgents.has(nodeId)) return;
        ctx.ranAgents.add(nodeId);
        await self._runAgent(nodeId, ctx);
    } else if (node.type === 'loop') {
        await self._runLoop(nodeId, visited, ctx);  // 内部每批调 _executeFrom 传播
        return;  // loop 内部已处理下游传播，不需要外面的逻辑
    } else if (node.type === 'comfy') {
        // 先执行上游 agent（Loop 由父链 _executeFrom(loopId) 处理，这里不重复执行）
        // v2.5.56：跳过 visited 中已执行的 agent（链根 agent，避免 LOOP 每批重跑）；
        //          并用 loopRanAgents 跨批次去重直接挂生成器上游的 agent（整个 loop 只跑一次）
        var upstreamIds = self._upstreamOrder(nodeId);
        for (var i = 0; i < upstreamIds.length; i++) {
            var un = self.nodes.find(function(n) { return n.id === upstreamIds[i]; });
            if (un && un.type === 'agent' && !visited.has(un.id) && !(ctx.loopRanAgents && ctx.loopRanAgents.has(un.id)) && !ctx.ranAgents.has(un.id)) {
                ctx.ranAgents.add(un.id);
                await self._runAgent(upstreamIds[i], ctx);
                if (ctx.loopRanAgents) ctx.loopRanAgents.add(un.id);
            }
        }
        await self._runComfyUI(nodeId, ctx);
    } else if (node.type === 'prompt') {
        // 提示词节点是数据节点，不执行，只向下游传播
    } else {
        // image_gen / video_gen → _runPipeline 内部处理上游 agent
        await self._runPipeline(nodeId, visited, ctx);
    }

    // v2.5.70：链被取消时立即停止传播
    if (ctx.signal.aborted) return;

    // v2.5.52：取消/错误时阻断下游传播，避免已取消链路的节点继续执行
    var nodeAfter = self.nodes.find(function(n) { return n.id === nodeId; });
    if (nodeAfter && (nodeAfter.runState === 'cancelled' || nodeAfter.runState === 'error')) return;

    // 向下游传播（v2.5.68：穿透数据节点，跨组自动串联）
    var downstreams = self._nextExecutableDownstreams(nodeId);
    for (var j = 0; j < downstreams.length; j++) {
        await self._executeFrom(downstreams[j].id, visited, ctx);
    }
};

CanvasEngine.prototype._runComfyUI = async function(nodeId, ctx) {
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!node.comfyWorkflow) { this._setNodeRunState(node,'error',_t('pipeline.selectWorkflow','请选择工作流')); return; }
    var inputs = this._collectInputs(nodeId);

    // v2.5.70：链上下文中用链级信号（节点「取消」只中止所在链）；
    // 独立运行兜底时才创建专用 AbortController（解决 P0-5：独立运行时取消无效）
    var standaloneComfy = null;
    var comfySignal;
    if (ctx) {
        comfySignal = ctx.signal;
    } else {
        if (this._activeComfyAbort) { this._activeComfyAbort.abort(); }
        standaloneComfy = new AbortController();
        this._activeComfyAbort = standaloneComfy;
        comfySignal = standaloneComfy.signal;
    }

    this._setNodeRunState(node,'running',_t('pipeline.comfySubmitting','提交 ComfyUI...'));
    node._runCtx = ctx || null;  // v2.5.71：登记运行归属（取消级联防并发链互染）
    this._renderAll();
    try {
        var fields = {};
        var wf = (this._comfyWfList||[]).find(function(w) { return w.name === node.comfyWorkflow; });
        var flds = wf?._fields||[];
        var tagMap = {};
        // v2.5.53：文本先入、图片后入，确保同名 fieldId 时图片覆盖文本（而非文本覆盖图片导致 LoadImage 报错）
        // v2.5.59：音频输入并入 tagMap 与字段路由（ComfyUI 音频参考/驱动）
        [...inputs.texts, ...inputs.images, ...inputs.audios].forEach(function(v) {
            var parts = String(v).split('::'); if(parts.length>=2){ tagMap[parts[0]]=parts.slice(1).join('::'); }
        });
        var imgIdx = 0, txtIdx = 0, audIdx = 0;
        flds.forEach(function(f) {
            if (tagMap[f.id]) { fields[f.node+'::'+f.input] = tagMap[f.id]; return; }
            if (f.type==='image'&&imgIdx<inputs.images.length){
                var v = inputs.images[imgIdx++];
                fields[f.node+'::'+f.input] = String(v).includes('::') ? String(v).split('::').slice(1).join('::') : v;
            } else if (f.type==='audio'&&audIdx<inputs.audios.length){
                var a = inputs.audios[audIdx++];
                fields[f.node+'::'+f.input] = String(a).includes('::') ? String(a).split('::').slice(1).join('::') : a;
            } else if (f.type!=='image'&&f.type!=='audio'&&txtIdx<inputs.texts.length){
                var t = inputs.texts[txtIdx++];
                fields[f.node+'::'+f.input] = String(t).includes('::') ? String(t).split('::').slice(1).join('::') : t;
            } else if (f.default) { fields[f.node+'::'+f.input] = f.default; }
        });
        if (!Object.keys(fields).length && inputs.texts.length) fields['prompt'] = inputs.texts.join('\n');

        if (comfySignal.aborted) return;
        var resp = await apiFetch('/api/comfyui/workflows/'+encodeURIComponent(node.comfyWorkflow)+'/run',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({fields,client_id:nodeId,
                // v2.5.60：节点可配置轮询（超时单位分→秒，间隔单位秒）
                poll_timeout:(parseInt(node.comfyPollTimeout)||60)*60,
                poll_interval:parseInt(node.comfyPollInterval)||1}),
            signal: comfySignal
        });
        var data = await resp.json();
        if (comfySignal.aborted) return;
        if (data.detail) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
        if(data.images?.length||data.videos?.length){
            var target = this._ensureOutput(nodeId) || node;
            if(data.images?.length) target.images = [...(target.images||[]), ...data.images.map(function(u){return typeof u==='string'?{url:u,name:_t('pipeline.comfyImageResult','ComfyUI结果')}:u;})].slice(-50);
            if(data.videos?.length) target.videos = [...(target.videos||[]), ...data.videos.map(function(u){return typeof u==='string'?{url:u,name:_t('pipeline.comfyVideoResult','ComfyUI视频')}:u;})].slice(-50);
            this._syncOutputToStore(target);
            this._refreshAssetLibrary();
            this._loadOutputDimensions(target);
            this._setNodeRunState(node,'success',(data.images?.length?_t('pipeline.imageGenerated','图片已生成'):_t('pipeline.videoGenerated','视频已生成')));
        }else{
            this._setNodeRunState(node,'error',_t('pipeline.comfyNoOutput','无输出')+' keys='+JSON.stringify(Object.keys(data)));
        }
    }catch(e){
        if (comfySignal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
        } else {
            this._setNodeRunState(node, 'error', e.message||String(e));
        }
    }finally{
        this._renderAll();this._markDirty();this.save();
        if (standaloneComfy && this._activeComfyAbort === standaloneComfy) this._activeComfyAbort = null;
    }
};

CanvasEngine.prototype._runPipeline = async function(nodeId, visited, ctx) {
    // v2.5.70：使用链级信号（不再创建全局 _activePipelineAbort；多链并发互不干扰）
    ctx = this._ensureCtx(ctx, nodeId);
    var signal = ctx.signal;

    try {
        const gen = this.nodes.find(n => n.id === nodeId);
        if (!gen) return;

        // 1. 按拓扑顺序依次执行上游 Agent 节点
        const upstreamIds = this._upstreamOrder(nodeId);
        for (const uid of upstreamIds) {
            if (signal.aborted) return;
            const node = this.nodes.find(n => n.id === uid);
            if (!node) continue;
            // v2.5.56：跳过 visited 中已执行的 agent（链根 agent，避免 LOOP 每批重跑）；
            //          并用 loopRanAgents 跨批次去重直接挂生成器上游的 agent（整个 loop 只跑一次）
            if (node.type === 'agent' && !(visited && visited.has(node.id)) && !(ctx.loopRanAgents && ctx.loopRanAgents.has(node.id)) && !ctx.ranAgents.has(node.id)) {
                ctx.ranAgents.add(node.id);
                ctx.nodes.add(node.id);
                this._setNodeRunState(node, 'running', _t('pipeline.pipelineRunning','管线执行中...'));
                await this._runAgent(uid, ctx);
                if (ctx.loopRanAgents) ctx.loopRanAgents.add(node.id);
            }
        }

        // 2. 执行生图
        if (!signal.aborted) {
            await this._runGenerator(nodeId, ctx);
        }
    } finally {
        // v2.5.70：链上下文由 _executeChain 统一注销，此处无需清理
    }
};

CanvasEngine.prototype.cancelPipeline = function() {
    // v2.5.70：中止所有活动链（链级 AbortController）——全局「停止」按钮 / ESC 入口
    var self = this;
    this._activeChains.forEach(function(ctx) { ctx.abort.abort(); });
    // 兜底：独立运行的 ComfyUI（无链上下文时）
    if (this._activeComfyAbort) {
        this._activeComfyAbort.abort();
    }
    // 即时反馈：所有 running 节点 → cancelled（异步回调稍后也会确认，幂等）
    this.nodes.forEach(function(n) {
        if (n.runState === 'running') self._setNodeRunState(n, 'cancelled', _t('pipeline.cancelled','Cancelled'));
    });
};

// v2.5.69：检测是否有任何节点正在运行（用于工具栏「停止」按钮显隐 / ESC 快捷键）
CanvasEngine.prototype._anyNodeRunning = function() {
    return this.nodes.some(function(n) { return n.runState === 'running'; });
};

// v2.5.70：节点级取消入口——定位节点所在链，只中止该链（多链并发互不影响）
CanvasEngine.prototype._cancelNodeRun = function(nodeId) {
    var hit = this._findChainCtxByNode(nodeId);
    if (hit) {
        hit.abort.abort();
        // 即时反馈：链上所有 running 节点 → cancelled
        // v2.5.71：归属过滤——仅重置「正由本链执行」的节点（_runCtx 为空视为陈旧状态，一并复位），
        //          防止并发链共享节点时误染另一条链的运行状态
        var self = this;
        this.nodes.forEach(function(n) {
            if (n.runState === 'running' && (n.id === hit.rootId || hit.nodes.has(n.id)) && (!n._runCtx || n._runCtx === hit)) {
                self._setNodeRunState(n, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            }
        });
        // loop 需同时置 _cancelled，让批次循环立即退出
        var ln = this.nodes.find(function(n) { return n.id === nodeId; });
        if (ln && ln.type === 'loop') ln._cancelled = true;
        return;
    }
    // 兜底：节点不在任何活动链中（loop 的 _cancelled 机制 / 独立 ComfyUI / 陈旧 running 状态）
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (node.type === 'loop') { this._cancelLoop(nodeId); return; }
    if (node.type === 'comfy') { this._cancelComfyUI(nodeId); return; }
    if (node.runState === 'running') {
        this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
    }
};

CanvasEngine.prototype._runGenerator = async function(id, ctx) {
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;

    const inputs = this._collectInputs(id);
    const provs = getCachedProviders();
    const fallbackType = node.type === 'video_gen' ? 'video' : (node.type === 'image_gen' ? 'image' : undefined);
    const provider = provs.find(x => x.id === (node.provider_id || this._getProviderId(fallbackType)));
    if (!provider) {
        this._setNodeRunState(node, 'error', _t('pipeline.noProvider','未找到可用的 API 平台，请先在设置中配置 API Key'));
        this._renderAll();
        return;
    }
    // video_gen 节点优先回退到视频模型，image_gen 优先图片模型
    const preferVideo = node.type === 'video_gen';
    const model = node.model
        || (preferVideo ? provider.video_models?.[0] : null)
        || provider.image_models?.[0]
        || provider.video_models?.[0]
        || '';
    if (!model) {
        this._setNodeRunState(node, 'error', _t('pipeline.noModel','该平台未配置可用模型，请在设置中添加模型'));
        this._renderAll();
        return;
    }
    const isVideoModel = (provider.video_models||[]).some(m => m.toLowerCase() === model.toLowerCase());

    if (isVideoModel) {
        // 视频生成：异步提交 → 轮询
        await this._runVideoGenerator(node, inputs, provider, model, ctx);
    } else {
        // 图片生成
        await this._runImageGenerator(node, inputs, provider, model, ctx);
    }
};

CanvasEngine.prototype._runImageGenerator = async function(node, inputs, provider, model, ctx) {
    // v2.5.52 修复 TOCTOU：捕获信号快照，避免动态读取被后续运行替换
    // v2.5.70：使用链级信号（ctx 由 _executeChain 提供；兜底临时 ctx 仅保证信号可用）
    ctx = this._ensureCtx(ctx, node.id);
    var mySignal = ctx.signal;
    ctx.nodes.add(node.id);
    this._setNodeRunState(node, 'running', _t('pipeline.generatingImage','正在生成图片...'));
    node._runCtx = ctx;  // v2.5.71：登记运行归属（取消级联防并发链互染）
    try {
        const response = await apiFetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: inputs.texts.join('\n') || _t('pipeline.defaultImagePrompt','a beautiful image'),
                provider_id: node.provider_id || this._getProviderId('image'),
                model: model,
                size: inputs.images.length ? ((node.size || '').startsWith('custom') ? '' : (node.size || '')) : (node.size || '1024x1024'),
                reference_images: inputs.images,
            }),
            signal: mySignal,
        });
        const data = await response.json();
        if (mySignal && mySignal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            this._renderAll();
            this._markDirty();
            return;
        }
        if (data.detail) throw new Error(data.detail);
        if (!data.url) throw new Error(_t('pipeline.noImageReturned','未返回图片地址'));
        const target = this._ensureOutput(node.id) || node;
        target.images = [...(target.images || []), { url: data.url, name: _t('pipeline.resultImage','生成结果') }].slice(-50);
        target.outputText = '';
        this._syncOutputToStore(target);
        this._loadOutputDimensions(target);
        this._setNodeRunState(node, 'success', _t('pipeline.imageGenerated','图片已生成'));
        this._renderAll();
        this._markDirty();
        this.save();
        this._refreshAssetLibrary();
    } catch (error) {
        if (mySignal && mySignal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
        } else {
            var msg = error.message || String(error);
            this._setNodeRunState(node, 'error', msg.slice(0, 200));
        }
        console.error('image generation failed', error);
        this._renderAll();
        this._markDirty();
    }
};

CanvasEngine.prototype._runVideoGenerator = async function(node, inputs, provider, model, ctx) {
    // v2.5.70：使用链级信号（不再创建全局 _activeVideoAbort；多链并发互不干扰）
    ctx = this._ensureCtx(ctx, node.id);
    var signal = ctx.signal;
    ctx.nodes.add(node.id);

    // 检查链级中止信号
    function _isCancelled() {
        return signal.aborted;
    }

    this._setNodeRunState(node, 'running', _t('pipeline.videoSubmitting','正在提交视频生成...'));
    node._runCtx = ctx;  // v2.5.71：登记运行归属（取消级联防并发链互染）
    try {
        // 1. 提交异步视频任务
        const submitResp = await apiFetch('/api/video/generate/async', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: inputs.texts.join('\n') || _t('pipeline.defaultVideoPrompt','a beautiful video'),
                provider_id: node.provider_id || this._getProviderId('video'),
                model: model,
                duration: node.duration || 5,
                resolution: node.resolution || (inputs.images.length ? 'auto' : '720p'),
                aspect_ratio: node.aspect_ratio || '16:9',
                reference_images: inputs.images,
                generate_audio: node.generate_audio !== false,
                reference_audio: inputs.audios,
            }),
            signal: signal,  // v2.5.51：传递 abort signal
        });
        const submitData = await submitResp.json();
        if (!submitData.task_id) throw new Error(_t('pipeline.videoSubmitFailed','视频任务提交失败') + ': ' + JSON.stringify(submitData));

        // 提交成功 → 立即更新进度（消除 8s 静默期）
        this._setNodeRunState(node, 'running', _t('pipeline.videoSubmitted','视频任务已提交，预计需 1-10 分钟...'));
        this._renderAll();

        // 2. 轮询任务状态（参数优先从后端 /api/video/model-params 加载，兜底硬编码值）
        var pollIntervalMs = (this._videoPollIntervalS || 15) * 1000;  // v2.5.52：与后端 constants.py 同步
        var maxRetries = this._videoPollTimeoutS && this._videoPollIntervalS
            ? Math.ceil(this._videoPollTimeoutS / this._videoPollIntervalS)
            : this._videoPollMaxRetries;
        for (let i = 0; i < maxRetries; i++) {
            if (_isCancelled(this)) {
                this._setNodeRunState(node, 'cancelled', _t('pipeline.videoCancelled','视频生成已取消'));
                this._renderAll();
                this._markDirty();
                return;
            }
            // abort 可中断的 sleep：取消时立即返回，不等满 interval
            await new Promise(r => {
                var t = setTimeout(r, pollIntervalMs);
                signal.addEventListener('abort', () => { clearTimeout(t); r(); }, { once: true });
            });
            if (_isCancelled(this)) {
                this._setNodeRunState(node, 'cancelled', _t('pipeline.videoCancelled','视频生成已取消'));
                this._renderAll();
                this._markDirty();
                return;
            }
            const pollResp = await apiFetch('/api/tasks/' + submitData.task_id, { signal: signal });
            const pollData = await pollResp.json();
            if (pollData.status === 'succeeded') {
                const videoUrl = pollData.result?.video_url || '';
                if (!videoUrl) throw new Error(_t('pipeline.videoDoneNoUrl','视频任务完成但无下载地址'));
                const target = this._ensureOutput(node.id) || node;
                target.videos = [...(target.videos || []), { url: videoUrl, name: _t('pipeline.resultVideo','生成视频') }].slice(-50);
                target.outputText = '';
                this._syncOutputToStore(target);
                this._loadOutputDimensions(target);
                this._setNodeRunState(node, 'success', _t('pipeline.videoGenerated','视频已生成'));
                this._renderAll();
                this._markDirty();
                this.save();
                this._refreshAssetLibrary();
                return;
            }
            if (pollData.status === 'failed') {
                throw new Error(pollData.error || _t('pipeline.videoFailed','视频生成失败'));
            }
            if (!_isCancelled(this)) {
                node.runMessage = _t('pipeline.videoPolling','视频生成中 ({t}s)...').replace('{t}', pollData.progress || i * 3);
            }
        }
        throw new Error(_t('pipeline.videoTimeout','视频生成超时'));
    } catch (error) {
        if (signal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.videoCancelled','视频生成已取消'));
        } else {
            const msg = error.message || String(error);
            this._setNodeRunState(node, 'error', msg.slice(0, 200));
        }
        console.error('video generation failed', error);
        this._renderAll();
        this._markDirty();
    } finally {
        // v2.5.70：链上下文由 _executeChain 统一注销，此处无需清理
    }
};

CanvasEngine.prototype._runAgent = async function(id, ctx) {
    // v2.5.52 修复 TOCTOU：捕获信号快照，避免动态读取被后续运行替换
    // v2.5.70：链上下文中用链级信号；独立运行（节点按钮直调）时创建并注册专用链 ctx——
    //          取消按钮/ESC 可中断，仍保留 300s 超时兜底（mimo 长 JSON 实测需 80~100s）。
    var standaloneCtx = null;
    if (!ctx) {
        // v2.5.71：防重复——该 agent 已在某条活动链中执行时忽略本次点击（防并发双跑）
        if (this._findChainCtxByNode(id)) { console.warn('[canvas] agent already running in a chain, ignored:', id); return; }
        standaloneCtx = this._createChainCtx(id);
        ctx = standaloneCtx;
    }
    ctx.nodes.add(id);
    var mySignal = standaloneCtx && typeof AbortSignal.any === 'function' && typeof AbortSignal.timeout === 'function'
        ? AbortSignal.any([ctx.signal, AbortSignal.timeout(300000)])
        : ctx.signal;
    const node = this.nodes.find(item => item.id === id);
    if (!node) {
        if (standaloneCtx) this._removeChainCtx(standaloneCtx);
        return;
    }

    if (!node.agentId) {
        this._setNodeRunState(node, 'error', _t('pipeline.selectAgent','请先在上方下拉框选择一个智能体'));
        if (standaloneCtx) this._removeChainCtx(standaloneCtx);
        return;
    }

    const inputs = this._collectInputs(id);
    const finalInput = [inputs.texts.join('\n'), node.userInput].filter(Boolean).join('\n') || _t('pipeline.defaultTask','请执行任务');
    this._setNodeRunState(node, 'running', _t('pipeline.agentRunning','Agent 执行中...'));
    node._runCtx = ctx;  // v2.5.71：登记运行归属（取消级联防并发链互染）

    try {
        const response = await apiFetch(`/api/agents/${node.agentId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_input: finalInput,
                input_images: inputs.images,
            }),
            signal: mySignal,
        });
        const data = await response.json();
        if (mySignal && mySignal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            this._renderAll();
            this._markDirty();
            return;
        }
        // v2.5.74：失败/降级响应直接抛错，防止垃圾文本（如「任务已执行但未获得最终输出。」）
        //          冒充正常结果存入 lastResult 并向下游列队/生图传播（列队异常出图根因之一）
        if (data.success === false) {
            throw new Error(data.error || _t('pipeline.agentFailed','Agent 失败'));
        }
        if (data.degraded || !data.final_output) {
            throw new Error(_t('pipeline.agentNoOutput','Agent 未产生最终输出（请检查模型是否支持图片等输入格式）'));
        }
        node.lastResult = data.final_output || '';
        this.store.updateNode(id, { lastResult: node.lastResult });

        const outputImages = (data.output_images || []).map(url => ({ url, name: _t('pipeline.agentOutput','Agent 输出') }));
        const target = this._ensureOutput(id) || node;
        if (target !== node) target.outputText = node.lastResult || '';  // 仅输出节点需要 outputText；agent 节点已单独显示 lastResult
        if (outputImages.length) {
            target.images = [...(target.images || []), ...outputImages].slice(-50);
            this._loadOutputDimensions(target);
        }
        this._syncOutputToStore(target);

        this._setNodeRunState(node, 'success', _t('pipeline.agentComplete','Agent 完成'));
        this._renderAll();
        this._markDirty();
        this.save();
    } catch (error) {
        if (mySignal && mySignal.aborted) {
            this._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
        } else {
            this._setNodeRunState(node, 'error', error.message ? error.message.slice(0, 200) : _t('pipeline.agentFailed','Agent 失败'));
        }
        this._markDirty();
    } finally {
        // v2.5.70：独立运行的 agent 链 ctx 用完即注销（链上下文由 _executeChain 注销）
        if (standaloneCtx) this._removeChainCtx(standaloneCtx);
    }
};

CanvasEngine.prototype._configAgent = function(id) {
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;
    // 通知父窗口跳转到 Agent 页面
    window.parent.postMessage({ type: 'navigate', page: 'agents' }, location.origin);
};
