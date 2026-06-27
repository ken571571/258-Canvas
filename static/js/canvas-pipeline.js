// canvas-pipeline.js — pipeline / execution methods
// Prototype extension pattern: attach each method to CanvasEngine.prototype

// ============================================================
// Class-level data fields
// ============================================================

CanvasEngine.prototype._activePipelineAbort = null;
CanvasEngine.prototype._activeVideoAbort = null;
CanvasEngine.prototype._activeComfyAbort = null;

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

CanvasEngine.prototype._collectInputs = function(nodeId) {
    var texts = [];
    var images = [];
    var videos = [];
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

    return { texts, images, videos };
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

CanvasEngine.prototype._runLoop = async function(nodeId, visited) {
    var self = this;
    var node = self.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!node._queue) node._queue = [];
    if (!node._textSegments) node._textSegments = [];
    // v2.5.52：快照防竞态 — await 期间用户可能添加/删除队列项，快照确保执行期间数据一致
    var execQueue = node._queue.slice();
    var execTexts = node._textSegments.slice();
    // v2.5.53：收集上游文本并剥离 fieldId 标签，防止标签泄漏到 _textSegments
    var upstreamTexts = self._collectInputs(nodeId).texts.map(function(t) {
        var parts = String(t).split('::');
        return parts.length >= 2 ? parts.slice(1).join('::') : t;
    });
    if (upstreamTexts.length) {
        var raw = upstreamTexts.join('\n');
        execTexts = raw.split('----').map(function(s) { return s.trim(); }).filter(Boolean);
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
    // 计算有效图片数（可被 batchSize 整除的部分）和剩余
    var effectiveImages = totalImages - (totalImages % batchSize);
    node._cursorImg = 0;
    node._cursorTxt = 0;
    node._cancelled = false;
    self._setNodeRunState(node, 'running', _t('pipeline.batchStart','开始批次处理...'));
    self._renderAll();
    for (var b = 0; b < batchCount; b++) {
        if (node._cancelled) {
            self._setNodeRunState(node, 'cancelled', _t('pipeline.cancelled','Cancelled'));
            self._renderAll(); self._markDirty(); return;
        }
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
                await self._executeFrom(downstreams[d].id, batchVisited);
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
        if (node._cancelled) {
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
    return this._videoDurations[model] || [5, 8, 10];
};

CanvasEngine.prototype._getVideoResolutions = function(model) {
    return this._videoResolutions[model] || [{v:'720p',l:'720p'},{v:'1080p',l:'1080p'},{v:'1280x720',l:'1280x720'}];
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
    var ups = this.connections
        .filter(function(c) { return c.to === nodeId; })
        .map(function(c) { return self.nodes.find(function(n) { return n.id === c.from; }); })
        .filter(function(n) { return self._isExecutable(n); });
    if (!ups.length) return nodeId;
    return this._findChainRoot(ups[0].id, visited);
};

// 点击任意节点 [运行] → 从链起点执行到终点
CanvasEngine.prototype._executeChain = async function(nodeId) {
    var rootId = this._findChainRoot(nodeId);
    return this._executeFrom(rootId);
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
CanvasEngine.prototype._executeFrom = async function(nodeId, visited) {
    var self = this;
    // 环路保护：同一链上不重复执行
    if (!visited) visited = new Set();
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    var node = self.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!self._isExecutable(node)) return;

    if (node.type === 'agent') {
        await self._runAgent(nodeId);
    } else if (node.type === 'loop') {
        await self._runLoop(nodeId, visited);  // 内部每批调 _executeFrom 传播
        return;  // loop 内部已处理下游传播，不需要外面的逻辑
    } else if (node.type === 'comfy') {
        // 先执行上游 agent（Loop 由父链 _executeFrom(loopId) 处理，这里不重复执行）
        var upstreamIds = self._upstreamOrder(nodeId);
        for (var i = 0; i < upstreamIds.length; i++) {
            var un = self.nodes.find(function(n) { return n.id === upstreamIds[i]; });
            if (un && un.type === 'agent') await self._runAgent(upstreamIds[i]);
        }
        await self._runComfyUI(nodeId);
    } else if (node.type === 'prompt') {
        // 提示词节点是数据节点，不执行，只向下游传播
    } else {
        // image_gen / video_gen → _runPipeline 内部处理上游 agent
        await self._runPipeline(nodeId);
    }

    // v2.5.52：取消/错误时阻断下游传播，避免已取消链路的节点继续执行
    var nodeAfter = self.nodes.find(function(n) { return n.id === nodeId; });
    if (nodeAfter && (nodeAfter.runState === 'cancelled' || nodeAfter.runState === 'error')) return;

    // 向下游传播
    var downstreams = self.connections
        .filter(function(c) { return c.from === nodeId; })
        .map(function(c) { return self.nodes.find(function(n) { return n.id === c.to; }); })
        .filter(function(n) { return self._isExecutable(n); });
    for (var j = 0; j < downstreams.length; j++) {
        await self._executeFrom(downstreams[j].id, visited);
    }
};

CanvasEngine.prototype._runComfyUI = async function(nodeId) {
    var node = this.nodes.find(function(n) { return n.id === nodeId; });
    if (!node) return;
    if (!node.comfyWorkflow) { this._setNodeRunState(node,'error',_t('pipeline.selectWorkflow','请选择工作流')); return; }
    var inputs = this._collectInputs(nodeId);

    // 创建独立的 AbortController（解决 P0-5：独立运行时取消无效）
    if (this._activeComfyAbort) { this._activeComfyAbort.abort(); }
    this._activeComfyAbort = new AbortController();
    var comfySignal = this._activeComfyAbort.signal;

    this._setNodeRunState(node,'running',_t('pipeline.comfySubmitting','提交 ComfyUI...'));
    this._renderAll();
    try {
        var fields = {};
        var wf = (this._comfyWfList||[]).find(function(w) { return w.name === node.comfyWorkflow; });
        var flds = wf?._fields||[];
        var tagMap = {};
        // v2.5.53：文本先入、图片后入，确保同名 fieldId 时图片覆盖文本（而非文本覆盖图片导致 LoadImage 报错）
        [...inputs.texts, ...inputs.images].forEach(function(v) {
            var parts = String(v).split('::'); if(parts.length>=2){ tagMap[parts[0]]=parts.slice(1).join('::'); }
        });
        var imgIdx = 0, txtIdx = 0;
        flds.forEach(function(f) {
            if (tagMap[f.id]) { fields[f.node+'::'+f.input] = tagMap[f.id]; return; }
            if (f.type==='image'&&imgIdx<inputs.images.length){
                var v = inputs.images[imgIdx++];
                fields[f.node+'::'+f.input] = String(v).includes('::') ? String(v).split('::').slice(1).join('::') : v;
            } else if (f.type!=='image'&&txtIdx<inputs.texts.length){
                var t = inputs.texts[txtIdx++];
                fields[f.node+'::'+f.input] = String(t).includes('::') ? String(t).split('::').slice(1).join('::') : t;
            } else if (f.default) { fields[f.node+'::'+f.input] = f.default; }
        });
        if (!Object.keys(fields).length && inputs.texts.length) fields['prompt'] = inputs.texts.join('\n');

        if (comfySignal.aborted) return;
        var resp = await apiFetch('/api/comfyui/workflows/'+encodeURIComponent(node.comfyWorkflow)+'/run',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({fields,client_id:nodeId}),
            signal: comfySignal
        });
        var data = await resp.json();
        if (comfySignal.aborted) return;
        if (data.detail) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
        if(data.images?.length||data.videos?.length){
            var outputNode = this._ensureOutput(nodeId);
            if(data.images?.length) outputNode.images = [...(outputNode.images||[]), ...data.images.map(function(u){return typeof u==='string'?{url:u,name:_t('pipeline.comfyImageResult','ComfyUI结果')}:u;})].slice(-50);
            if(data.videos?.length) outputNode.videos = [...(outputNode.videos||[]), ...data.videos.map(function(u){return typeof u==='string'?{url:u,name:_t('pipeline.comfyVideoResult','ComfyUI视频')}:u;})].slice(-50);
            this._syncOutputToStore(outputNode);
            this._refreshAssetLibrary();
            this._loadOutputDimensions(outputNode);
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
        if (this._activeComfyAbort === comfySignal) this._activeComfyAbort = null;
    }
};

CanvasEngine.prototype._runPipeline = async function(nodeId) {
    // 取消之前的 pipeline（如果有）
    if (this._activePipelineAbort) {
        this._activePipelineAbort.abort();
    }
    this._activePipelineAbort = new AbortController();
    var signal = this._activePipelineAbort.signal;

    try {
        const gen = this.nodes.find(n => n.id === nodeId);
        if (!gen) return;

        // 1. 按拓扑顺序依次执行上游 Agent 节点
        const upstreamIds = this._upstreamOrder(nodeId);
        for (const uid of upstreamIds) {
            if (signal.aborted) return;
            const node = this.nodes.find(n => n.id === uid);
            if (!node) continue;
            if (node.type === 'agent') {
                this._setNodeRunState(node, 'running', _t('pipeline.pipelineRunning','管线执行中...'));
                await this._runAgent(uid);
            }
        }

        // 2. 执行生图
        if (!signal.aborted) {
            await this._runGenerator(nodeId);
        }
    } finally {
        if (this._activePipelineAbort === signal) {
            this._activePipelineAbort = null;
        }
    }
};

CanvasEngine.prototype.cancelPipeline = function() {
    if (this._activePipelineAbort) {
        this._activePipelineAbort.abort();
    }
    if (this._activeVideoAbort) {
        this._activeVideoAbort.abort();
    }
    if (this._activeComfyAbort) {
        this._activeComfyAbort.abort();
    }
};

CanvasEngine.prototype._runGenerator = async function(id) {
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
        await this._runVideoGenerator(node, inputs, provider, model);
    } else {
        // 图片生成
        await this._runImageGenerator(node, inputs, provider, model);
    }
};

CanvasEngine.prototype._runImageGenerator = async function(node, inputs, provider, model) {
    // v2.5.52 修复 TOCTOU：捕获信号快照，避免动态读取被后续运行替换
    var mySignal = this._activePipelineAbort?.signal;
    this._setNodeRunState(node, 'running', _t('pipeline.generatingImage','正在生成图片...'));
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
        const outputNode = this._ensureOutput(node.id);
        outputNode.images = [...(outputNode.images || []), { url: data.url, name: _t('pipeline.resultImage','生成结果') }].slice(-50);
        outputNode.outputText = '';
        this._syncOutputToStore(outputNode);
        this._loadOutputDimensions(outputNode);
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

CanvasEngine.prototype._runVideoGenerator = async function(node, inputs, provider, model) {
    // 取消之前的视频任务（如果有）
    if (this._activeVideoAbort) {
        this._activeVideoAbort.abort();
    }
    this._activeVideoAbort = new AbortController();
    var signal = this._activeVideoAbort.signal;

    // 检查管线级中止信号
    function _isCancelled(self) {
        if (signal.aborted) return true;
        if (self._activePipelineAbort && self._activePipelineAbort.signal.aborted) return true;
        return false;
    }

    this._setNodeRunState(node, 'running', _t('pipeline.videoSubmitting','正在提交视频生成...'));
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
                reference_images: inputs.images,
                generate_audio: node.generate_audio !== false,
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
                const outputNode = this._ensureOutput(node.id);
                outputNode.videos = [...(outputNode.videos || []), { url: videoUrl, name: _t('pipeline.resultVideo','生成视频') }].slice(-50);
                outputNode.outputText = '';
                this._syncOutputToStore(outputNode);
                this._loadOutputDimensions(outputNode);
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
        if (this._activeVideoAbort === signal) {
            this._activeVideoAbort = null;
        }
    }
};

CanvasEngine.prototype._runAgent = async function(id) {
    // v2.5.52 修复 TOCTOU：捕获信号快照，避免动态读取被后续运行替换
    var mySignal = this._activePipelineAbort?.signal;
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;

    if (!node.agentId) {
        this._setNodeRunState(node, 'error', _t('pipeline.selectAgent','请先在上方下拉框选择一个智能体'));
        return;
    }

    const inputs = this._collectInputs(id);
    const finalInput = [inputs.texts.join('\n'), node.userInput].filter(Boolean).join('\n') || _t('pipeline.defaultTask','请执行任务');
    this._setNodeRunState(node, 'running', _t('pipeline.agentRunning','Agent 执行中...'));

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
        node.lastResult = data.final_output || '';
        this.store.updateNode(id, { lastResult: node.lastResult });

        const outputImages = (data.output_images || []).map(url => ({ url, name: _t('pipeline.agentOutput','Agent 输出') }));
        const outputNode = this._ensureOutput(id);
        outputNode.outputText = node.lastResult || '';
        if (outputImages.length) {
            outputNode.images = [...(outputNode.images || []), ...outputImages].slice(-50);
            this._loadOutputDimensions(outputNode);
        }
        this._syncOutputToStore(outputNode);

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
    }
};

CanvasEngine.prototype._configAgent = function(id) {
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;
    // 通知父窗口跳转到 Agent 页面
    window.parent.postMessage({ type: 'navigate', page: 'agents' }, location.origin);
};
