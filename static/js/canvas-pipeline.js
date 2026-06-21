// canvas-pipeline.js — pipeline / execution methods
// Prototype extension pattern: attach each method to CanvasEngine.prototype

// ============================================================
// Class-level data fields
// ============================================================

CanvasEngine.prototype._activePipelineAbort = null;
CanvasEngine.prototype._activeVideoAbort = null;

// 视频模型时长和分辨率参数 —— 运行时由 _loadVideoModelParams() 从 GET /api/video/model-params 填充
CanvasEngine.prototype._videoDurations = {};
CanvasEngine.prototype._videoResolutions = {};
CanvasEngine.prototype._videoPollMaxRetries = 75;
CanvasEngine.prototype._videoPollIntervalMs = 8000;

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
        node.imageWidth = data.width || 0;
        node.imageHeight = data.height || 0;
        this._renderAll();
        this._markDirty();
    } catch (error) {
        alert(`上传失败: ${error.message}`);
    }
};

CanvasEngine.prototype._collectInputs = function(nodeId) {
    const texts = [];
    const images = [];
    const videos = [];

    this.connections
        .filter(connection => connection.to === nodeId)
        .forEach(connection => {
            const from = this.nodes.find(node => node.id === connection.from);
            if (!from) return;
            const tag = connection.fieldId || '';
            if (from.type === 'prompt' && from.text) texts.push(tag ? tag+'::'+from.text : from.text);
            if (from.type === 'agent' && from.lastResult) texts.push(tag ? tag+'::'+from.lastResult : from.lastResult);
            if (from.type === 'output' && from.outputText) texts.push(tag ? tag+'::'+from.outputText : from.outputText);
            if (from.type === 'output' && from.images) from.images.forEach(img => {
                const u = typeof img === 'string' ? img : img.url; if (u) images.push(tag ? tag+'::'+u : u);
            });
            if (from.type === 'image' && from.url) {
                const u = from.url;
                if (/\.(mp4|webm|mov|m4v)$/i.test(u)) videos.push(tag ? tag+'::'+u : u);
                else images.push(tag ? tag+'::'+u : u);
            }
            if (from.type === 'loop' && from._queue && from._queue.length) {
                from._queue.forEach(item => {
                    if (item.url) images.push(tag ? tag+'::'+item.url : item.url);
                });
            }
        });

    return { texts, images, videos };
};

CanvasEngine.prototype._clearOutput = function(nodeId) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node) return;
    node.outputText = '';
    node.images = [];
    node.videos = [];
    this._renderAll();
    this._markDirty();
};

CanvasEngine.prototype._removeOutputItem = function(nodeId, index, type) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node) return;
    const arr = type === 'image' ? node.images : node.videos;
    if (arr && index < arr.length) arr.splice(index, 1);
    this._renderAll();
    this._markDirty();
};

CanvasEngine.prototype._loadOutputDimensions = function(node) {
    // 异步加载输出项的图片/视频尺寸并缓存到 item._w/_h
    (node.images || []).forEach((item, i) => {
        const url = typeof item === 'string' ? item : (item.url || '');
        if (!url || (typeof item === 'object' && item._w)) return;
        if (/\.(png|jpg|jpeg|webp|gif)$/i.test(url)) {
            const img = new Image();
            img.onload = () => {
                if (node.images[i]) {
                    if (typeof node.images[i] === 'string') node.images[i] = { url: node.images[i] };
                    node.images[i]._w = img.naturalWidth;
                    node.images[i]._h = img.naturalHeight;
                    this._renderAll();
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
            if (node.videos[i]) {
                if (typeof node.videos[i] === 'string') node.videos[i] = { url: node.videos[i] };
                node.videos[i]._w = vid.videoWidth;
                node.videos[i]._h = vid.videoHeight;
                this._renderAll();
            }
        };
        vid.src = url;
    });
};

CanvasEngine.prototype._saveOutputAsset = async function(url) {
    if (!url) return;
    try {
        const resp = await fetch(url);
        const blob = await resp.blob();
        const form = new FormData();
        const ext = url.split('.').pop()?.split('?')[0] || 'png';
        form.append('file', blob, 'saved_' + Date.now() + '.' + ext);
        await apiFetch('/api/upload', { method: 'POST', body: form });
        // 刷新资产库
        if (typeof this._loadAssets === 'function') this._loadAssets('output');
        alert(_t('pipeline.savedToAssets','已保存到资产库'));
    } catch(e) { alert('保存失败: ' + e.message); }
};

CanvasEngine.prototype._updateGroupLabel = function(groupId, value) {
    const g = this.groups.find(x => x.id === groupId);
    if (g) { g.label = value.trim().slice(0, 40); this._markDirty(); }
};

CanvasEngine.prototype._removeLoopItem = function(nodeId, index) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node?._queue || index >= node._queue.length) return;
    const removed = node._queue.splice(index, 1)[0];
    if (!node._removedUrls) node._removedUrls = [];
    if (!node._removedUrls.includes(removed.url)) node._removedUrls.push(removed.url);
    this._markDirty();
    requestAnimationFrame(() => this._renderAll());
};

CanvasEngine.prototype._moveLoopItem = function(nodeId, index, dir) {
    const node = this.nodes.find(n => n.id === nodeId);
    if (!node || !node._queue) return;
    const newIdx = index + dir;
    if (newIdx < 0 || newIdx >= node._queue.length) return;
    const item = node._queue.splice(index, 1)[0];
    node._queue.splice(newIdx, 0, item);
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
    this._renderAll();
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
    if (payload.images) outputNode.images = [...(outputNode.images || []), ...payload.images];
    if (payload.videos) outputNode.videos = [...(outputNode.videos || []), ...payload.videos];
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

CanvasEngine.prototype._runComfyUI = async function(nodeId) {
    const node = this.nodes.find(n=>n.id===nodeId); if(!node||!node.comfyWorkflow) { this._setNodeRunState(node,'error',_t('pipeline.selectWorkflow','请选择工作流')); return; }
    const inputs=this._collectInputs(nodeId);
    this._setNodeRunState(node,'running','提交 ComfyUI...');
    try {
        const fields = {};
        const wf = (this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);
        const flds = wf?._fields||[];
        // 优先按字段标签精确匹配
        const tagMap = {};
        [...inputs.images, ...inputs.texts].forEach(v=>{
            const parts = String(v).split('::'); if(parts.length>=2){ tagMap[parts[0]]=parts.slice(1).join('::'); }
        });
        flds.forEach(f=>{
            if (tagMap[f.id]) { fields[f.node+'::'+f.input] = tagMap[f.id]; return; }
            // 回退：按类型自动映射
            if (f.type==='image'&&inputs.images.length){ const v=inputs.images.shift(); fields[f.node+'::'+f.input]=String(v).includes('::')?String(v).split('::').slice(1).join('::'):v; }
            else if(f.type!=='image'&&inputs.texts.length){ const v=inputs.texts.shift(); fields[f.node+'::'+f.input]=String(v).includes('::')?String(v).split('::').slice(1).join('::'):v; }
            else if(f.default) fields[f.node+'::'+f.input]=f.default;
        });
        if (!Object.keys(fields).length && inputs.texts.length) fields['prompt'] = inputs.texts.join('\n');
        const resp=await apiFetch('/api/comfyui/workflows/'+encodeURIComponent(node.comfyWorkflow)+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fields,client_id:nodeId})});
        const data=await resp.json();
        if(data.images?.length||data.videos?.length){
            const outputNode = this._ensureOutput(nodeId);
            if(data.images?.length) outputNode.images = [...(outputNode.images||[]), ...data.images.map(u=>typeof u==='string'?{url:u,name:'ComfyUI结果'}:u)];
            if(data.videos?.length) outputNode.videos = [...(outputNode.videos||[]), ...data.videos.map(u=>typeof u==='string'?{url:u,name:'ComfyUI视频'}:u)];
            node.runState='success'; node.runMessage=`${data.images?.length?'图片':'视频'}已生成`;
        }else{
            node.runState='error'; node.runMessage='无输出 keys='+JSON.stringify(Object.keys(data))+' imgs='+JSON.stringify(data.images)+' vids='+JSON.stringify(data.videos);
        }
    }catch(e){node.runState='error'; node.runMessage=e.message||String(e);}
    this._renderAll();this._markDirty();
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
                this._setNodeRunState(node, 'running', '管线执行中...');
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
};

CanvasEngine.prototype._runGenerator = async function(id) {
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;

    const inputs = this._collectInputs(id);
    const provs = getCachedProviders();
    const provider = provs.find(x => x.id === (node.provider_id || this._getProviderId()));
    if (!provider) {
        this._setNodeRunState(node, 'error', '未找到可用的 API 平台，请先在设置中配置 API Key');
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
        this._setNodeRunState(node, 'error', '该平台未配置可用模型，请在设置中添加模型');
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
    this._setNodeRunState(node, 'running', '正在生成图片...');
    try {
        const response = await apiFetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: inputs.texts.join('\n') || 'a beautiful image',
                provider_id: node.provider_id || this._getProviderId(),
                model: model,
                size: inputs.images.length ? ((node.size||'').startsWith('custom') ? '' : (node.size || '')) : (node.size || '1024x1024'),
                reference_images: inputs.images,
            }),
        });
        const data = await response.json();
        if (data.detail) throw new Error(data.detail);
        if (!data.url) throw new Error(_t('pipeline.noImageReturned','未返回图片地址'));
        const outputNode = this._ensureOutput(node.id);
        outputNode.images = [...(outputNode.images || []), { url: data.url, name: _t('pipeline.resultImage','生成结果') }];
        outputNode.outputText = '';
        this._loadOutputDimensions(outputNode);
        this._setNodeRunState(node, 'success', _t('pipeline.imageGenerated','图片已生成'));
        this._renderAll();
        this._markDirty();
        this._refreshAssetLibrary();
    } catch (error) {
        const msg = error.message || String(error);
        this._setNodeRunState(node, 'error', msg.slice(0, 200));
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

    this._setNodeRunState(node, 'running', '正在提交视频生成...');
    try {
        // 1. 提交异步视频任务
        const submitResp = await apiFetch('/api/video/generate/async', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: inputs.texts.join('\n') || 'a beautiful video',
                provider_id: node.provider_id || this._getProviderId(),
                model: model,
                duration: node.duration || 5,
                resolution: node.resolution || (inputs.images.length ? 'auto' : '720p'),
                reference_images: inputs.images,
                generate_audio: node.generate_audio !== false,
            }),
        });
        const submitData = await submitResp.json();
        if (!submitData.task_id) throw new Error('视频任务提交失败: ' + JSON.stringify(submitData));

        // 2. 轮询任务状态
        for (let i = 0; i < this._videoPollMaxRetries; i++) {
            if (_isCancelled(this)) {
                this._setNodeRunState(node, 'cancelled', '视频生成已取消');
                this._renderAll();
                this._markDirty();
                return;
            }
            await new Promise(r => setTimeout(r, this._videoPollIntervalMs));  // 每 8 秒查一次（AIHubMix 建议 15s）
            if (_isCancelled(this)) {
                this._setNodeRunState(node, 'cancelled', '视频生成已取消');
                this._renderAll();
                this._markDirty();
                return;
            }
            const pollResp = await apiFetch('/api/tasks/' + submitData.task_id);
            const pollData = await pollResp.json();
            if (pollData.status === 'succeeded') {
                const videoUrl = pollData.result?.video_url || '';
                if (!videoUrl) throw new Error(_t('pipeline.videoDoneNoUrl','视频任务完成但无下载地址'));
                const outputNode = this._ensureOutput(node.id);
                outputNode.videos = [...(outputNode.videos || []), { url: videoUrl, name: _t('pipeline.resultVideo','生成视频') }];
                outputNode.outputText = '';
                this._loadOutputDimensions(outputNode);
                this._setNodeRunState(node, 'success', _t('pipeline.videoGenerated','视频已生成'));
                this._renderAll();
                this._markDirty();
                this._refreshAssetLibrary();
                return;
            }
            if (pollData.status === 'failed') {
                throw new Error(pollData.error || _t('pipeline.videoFailed','视频生成失败'));
            }
            if (!_isCancelled(this)) {
                this._setNodeRunState(node, 'running', '视频生成中 (' + (pollData.progress || i * 3) + 's)...');
            }
        }
        throw new Error(_t('pipeline.videoTimeout','视频生成超时'));
    } catch (error) {
        if (signal.aborted) {
            this._setNodeRunState(node, 'cancelled', '视频生成已取消');
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
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;

    if (!node.agentId) {
        this._setNodeRunState(node, 'error', _t('pipeline.selectAgent','请先在上方下拉框选择一个智能体'));
        return;
    }

    const inputs = this._collectInputs(id);
    const finalInput = [inputs.texts.join('\n'), node.userInput].filter(Boolean).join('\n') || _t('pipeline.defaultTask','请执行任务');
    this._setNodeRunState(node, 'running', 'Agent 执行中...');

    try {
        const response = await apiFetch(`/api/agents/${node.agentId}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_input: finalInput,
                input_images: inputs.images,
            }),
        });
        const data = await response.json();
        node.lastResult = data.final_output || '';

        const outputImages = (data.output_images || []).map(url => ({ url, name: 'Agent 输出' }));
        const outputNode = this._ensureOutput(id);
        outputNode.outputText = node.lastResult || '';
        if (outputImages.length) {
            outputNode.images = [...(outputNode.images || []), ...outputImages];
            this._loadOutputDimensions(outputNode);
        }

        this._setNodeRunState(node, 'success', 'Agent 完成');
        this._renderAll();
        this._markDirty();
    } catch (error) {
        node.lastResult = `请求失败: ${error.message}`;
        this._setNodeRunState(node, 'error', 'Agent 失败');
        this._markDirty();
    }
};

CanvasEngine.prototype._configAgent = function(id) {
    const node = this.nodes.find(item => item.id === id);
    if (!node) return;
    // 通知父窗口跳转到 Agent 页面
    window.parent.postMessage({ type: 'navigate', page: 'agents' }, location.origin);
};
