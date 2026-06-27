class CanvasEngine {
    constructor(boardId, worldId, nodesId, linksId) {
        this.board = document.getElementById(boardId);
        this.world = document.getElementById(worldId);
        this.nodesEl = document.getElementById(nodesId);
        this.linksEl = document.getElementById(linksId);
        this.groupsEl = document.getElementById('groups-container');
        this.handlesEl = document.getElementById('connection-handles');
        this.selectionEl = document.getElementById('selection-marquee');
        this.connectionMenuEl = document.getElementById('connection-menu');

        this.canvasId = null;
        this.nodes = [];
        this.connections = [];
        this.groups = [];
        this.selected = new Set();
        this.selectedConnectionId = '';
        this.view = { x: 0, y: 0, scale: 1 };

        this._dragNodes = null;
        this._dragBoard = null;
        this._resizeNode = null;
        this._linkFrom = null;
        this._tempPointer = null;
        this._menuPoint = null;
        this._contextConnectionId = '';
        this._marquee = null;
        this._spacePressed = false;
        this._saveIndicatorTimer = 0;
        this._saveDebounceTimer = 0;
        this._undoStack = [];
        this._undoIndex = -1;
        this._clipboard = [];
        this._loadRetries = 0;

        window._canvas = this;
        this.store = new CanvasStore();
        window._store = this.store;  // 过渡期供 UI 组件和调试使用

        // 语言切换时重新渲染（_t() 动态文本更新）
        var self = this;
        this._onLangChanged = function() { self._renderAll(); };
        window.addEventListener('lang-changed', this._onLangChanged);
        this._initEvents();
        this._renderAll();
    }

    async init() {
        // 防御性容错：provider/agent 加载失败不影响画布启动
        try { await refreshProviders(); } catch(e) { console.warn('init: refreshProviders failed', e); }
        try { await this._loadAgentOpts(); } catch(e) { console.warn('init: _loadAgentOpts failed', e); }
        this._loadComfyWorkflows().catch(()=>{});
        this._loadVideoModelParams().catch(()=>{});
        const params = new URLSearchParams(location.search);
        const fromUrl = params.get('canvas_id');
        if (fromUrl) {
            this.canvasId = fromUrl;
            localStorage.setItem('canvas_current_id', fromUrl);
            await this.load();
            return;
        }

        let id = localStorage.getItem('canvas_current_id');
        if (!id || String(id).startsWith('local_')) {
            try {
                id = await this._createDefaultCanvas();
                localStorage.setItem('canvas_current_id', id);
            } catch (error) {
                console.warn('create default canvas failed, use local fallback', error);
                id = `local_${Date.now()}`;
            }
        }

        this.canvasId = id;
        await this.load();
    }

    async _createDefaultCanvas() {
        const response = await apiFetch('/api/boards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: _t('canvas.defaultTitle','默认画布') }),
        });
        const data = await response.json();
        return data.canvas.id;
    }

    async load() {
        if (!this.canvasId) return;
        clearTimeout(this._saveDebounceTimer);  // 取消残留的延迟保存，防止写入错误画布
        // v2.5.40：递增保存代数，使 load() 前发起的旧 save() 完成后自动丢弃结果
        this._saveGeneration = (this._saveGeneration || 0) + 1;
        // 递归保护：服务器持续故障时最多重试3次，避免无限递归
        const retries = this._loadRetries || 0;
        try {
            const response = await apiFetch(`/api/boards/${this.canvasId}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const canvas = data.canvas || {};
            // 数据验证通过后才清空旧数据（网络失败时保留原数据）
            this.nodes = [];
            this.connections = [];
            this.groups = [];
            this.selected.clear();
            // 记录服务器时间戳用于乐观并发控制
            this._canvasUpdatedAt = canvas.updated_at || 0;
            this.nodes = (canvas.nodes || []).map(node => ({
                ...node,
                runState: node.runState && node.runState !== 'idle' ? node.runState : 'idle',
                runMessage: node.runMessage || '',
            }));
            this.connections = canvas.connections || [];
            this.groups = canvas.groups || [];
            // 快照必须在所有数据加载完成后创建（connections/groups 在此之前为空）
            this._undoStack = [{ nodes: this.nodes.map(n => this._deepCloneNode(n)), connections: this.connections.map(c => ({...c})), groups: this.groups.map(g => ({...g, childIds: [...(g.childIds || [])]})) }];
            this._undoIndex = 0;
            if (canvas.viewport) this.view = canvas.viewport;
            // 同步到 Store（双写）
            this.store.loadFromServer({
                nodes: this.nodes,
                connections: this.connections,
                groups: this.groups,
                viewport: this.view
            });
            this._renderAll();
            this._loadRetries = 0;  // 成功后重置
        } catch (error) {
            if (String(error.message || '').includes('404') && retries < 3) {
                this._loadRetries = retries + 1;
                try {
                    const id = await this._createDefaultCanvas();
                    this.canvasId = id;
                    localStorage.setItem('canvas_current_id', id);
                } catch (createErr) {
                    console.warn('create default canvas failed', createErr);
                    this.canvasId = `local_${Date.now()}`;
                    this._loadRetries = 0;
                }
                if (!String(this.canvasId).startsWith('local_')) {
                    return this.load();
                }
            }
            console.warn('load canvas failed, continue with empty board', error);
            this._loadRetries = 0;
            this._renderAll();
        }
    }

    async save() {
        if (!this.canvasId) return;
        // 首次保存：local_ 画布先创建到服务器，再正常保存
        if (String(this.canvasId).startsWith('local_')) {
            try {
                var created = await apiJson('/api/boards', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: _t('canvas.defaultTitle','默认画布') }),
                });
                // v2.5.51：防御 apiJson 解析失败返回空对象
                if (!created || !created.canvas) throw new Error(_t('canvas.saveFailed','保存失败'));
                this.canvasId = created.canvas.id;
                this._canvasUpdatedAt = created.canvas.updated_at || 0;
                localStorage.setItem('canvas_current_id', this.canvasId);
            } catch (e) {
                this._setSaveIndicator(_t('canvas.saveFailed','保存失败'), 'error');
                return;
            }
        }
        // 防止并发保存：save() 未完成时新的 save() 调用排队等待
        if (this._saving) { this._pendingSave = true; return; }
        this._saving = true;
        try {
        // 捕获快照用于完成后验证（必须在 auto-create 之后，否则 local_→real 的切换会被误判）
        var capturingId = this.canvasId;
        var capturingGen = this._saveGeneration;
        // 保存前：将引擎完整同步到 Store（全字段，跳过运行时状态）
        // 设计：save() 从 Store 序列化负载，如果某字段只在引擎改了而 Store 没同步，刷新后丢失。
        // 之前只同步 x/y/w/h，导致 node.desc / _queue 排序 / ComfyUI 连线等多处遗漏 → 全字段同步根治。
        var SKIP_SAVE = {runState:1, runMessage:1, _cursorImg:1, _cursorTxt:1, _cancelled:1, _taH:1, _upstreamLast:1};
        for (var i = 0; i < this.nodes.length; i++) {
            var en = this.nodes[i];
            var sn = this.store.getNode(en.id);
            if (sn) {
                var keys = Object.keys(en);
                for (var k = 0; k < keys.length; k++) {
                    var key = keys[k];
                    if (SKIP_SAVE[key]) continue;
                    var v = en[key];
                    sn[key] = Array.isArray(v) ? v.slice() : v;
                }
            }
        }
        // 同步连线到 Store（ComfyUI 切换工作流过滤连线后可能遗漏 Store.removeConnection）
        this.store.connections = this.connections.map(function(c) { return Object.assign({}, c); });
        // 同步分组到 Store（分组 resize/删除/解组只修改了 Engine 的 this.groups）
        this.store.groups = this.groups.map(function(g) {
            var clean = Object.assign({}, g, { childIds: (g.childIds || []).slice() });
            delete clean._new;  // 清除临时 UI 标记，防止持久化到服务器
            return clean;
        });
        // 重建 Store 索引（直接数组赋值不会触发 _rebuildIndex）
        this.store._rebuildIndex();
        const payload = this.store.toSavePayload(this._clientId || '', this._canvasUpdatedAt);
        try {
            const response = await apiFetch(`/api/boards/${this.canvasId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                silent: true,
            });
            // v2.5.40：保存完成时画布已切换或已重新加载 → 丢弃旧数据防止覆盖
            if (this.canvasId !== capturingId || this._saveGeneration !== capturingGen) {
                return;
            }
            if (response.status === 409) {
                try {
                    const errData = await response.json();
                    const detail = errData?.detail || {};
                    if (detail.canvas) {
                        this.nodes = (detail.canvas.nodes || []).map(n => this._deepCloneNode(Object.assign(n, {runState: 'idle', runMessage: ''})));
                        this.connections = detail.canvas.connections || [];
                        this.groups = detail.canvas.groups || [];
                        this.view = detail.canvas.viewport || this.view;
                        this._canvasUpdatedAt = detail.canvas.updated_at || 0;
                        // 同步 Store：409 时引擎已替换为服务端最新数据，Store 必须同步
                        this.store.nodes = this.nodes.map(function(n) { return Object.assign({}, n); });
                        this.store.connections = this.connections.map(function(c) { return Object.assign({}, c); });
                        this.store.groups = this.groups.map(function(g) { return Object.assign({}, g, { childIds: (g.childIds || []).slice() }); });
                        this.store._rebuildIndex();
                        this._undoStack = [{ nodes: this.nodes.map(n => this._deepCloneNode(n)), connections: this.connections.map(c => ({...c})), groups: this.groups.map(g => ({...g, childIds: [...(g.childIds || [])]})) }];
                        this._undoIndex = 0;
                        this.selected.clear();
                        this.selectedConnectionId = '';
                        this._renderAll();
                        alert(_t('canvas.conflictMessage','画布已被其他页面更新，已刷新为最新版本。请重新尝试您的编辑。'));
                        return;
                    }
                } catch (_) {}
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json().catch(() => ({}));
            this._canvasUpdatedAt = (data.canvas || {}).updated_at || 0;
            this._setSaveIndicator(_t('canvas.saved','已保存'), 'ok');
            try { parent.postMessage({type:'refresh'}, location.origin); } catch(_) {}
        } catch (error) {
            console.error('save failed', error);
            this._setSaveIndicator(_t('canvas.saveFailed','保存失败'), 'error');
        }
        } finally {
            this._saving = false;
            // 并发调用排队：上一次保存期间又有新编辑 → 立即补一次保存
            if (this._pendingSave) { this._pendingSave = false; this.save(); }
        }
    }

    createNode(type, point = null, overrides = null) {
        const pt = point || this._menuPoint || this._screenToWorld(window.innerWidth / 2, window.innerHeight / 2);
        const labels = {
            image: _t('nodeType.image','图片'), prompt: _t('nodeType.prompt','提示词'),
            image_gen: _t('nodeType.imageGen','图片生成'),
            video_gen: _t('nodeType.videoGen','视频生成'),
            agent: _t('nodeType.agent','Agent'), loop: _t('nodeType.loop','列队'), output: _t('nodeType.output','输出'), comfy: _t('nodeType.comfy','ComfyUI'),
        };
        var node = {
            id: this._uid(type),
            type,
            x: pt.x,
            y: pt.y,
            w: 260,
            h: type === 'output' ? 200 : 100,
            label: labels[type] || type,
            desc: '',
            text: '',
            url: '',
            model: type === 'image_gen' ? ((getCachedProviders().find(p => (p.image_models||[]).length)?.image_models||[])[0] || 'dall-e-3') : (type === 'video_gen' ? ((getCachedProviders().find(p => (p.video_models||[]).length)?.video_models||[])[0] || 'veo3-fast') : ''),
            systemPrompt: '',
            outputText: '',
            lastResult: '',
            images: [],
            agentId: '',
            comfyWorkflow: '',
            _batchSize: 1,       // loop 节点每批输出数量 (1-5)
            hasConfig: false,
            knowledgeBases: [],
            skills: [],
            userInput: '',
            runState: 'idle',
            runMessage: '',
        };
        // 应用调用方传入的属性覆盖（在渲染前设置，避免二次 _renderAll 重建 img 标签）
        if (overrides) {
            var keys = Object.keys(overrides);
            for (var k = 0; k < keys.length; k++) { node[keys[k]] = overrides[keys[k]]; }
        }
        this.nodes.push(node);
        this.store.addNode(node);  // 双写 Store
        this._renderAll();
        this._markDirty();
        return node;
    }

    _deleteNode(nodeId) {
        this.nodes = this.nodes.filter(node => node.id !== nodeId);
        this.connections = this.connections.filter(connection => connection.from !== nodeId && connection.to !== nodeId);
        // 清理分组中的引用（与 _deleteSelectedNodes 保持一致）
        this.groups = this.groups.map(group => ({
            ...group,
            childIds: group.childIds.filter(cid => cid !== nodeId),
        })).filter(group => group.childIds.length >= 2);
        this.selected.delete(nodeId);
        if (this.selectedConnectionId && !this.connections.some(connection => connection.id === this.selectedConnectionId)) {
            this.selectedConnectionId = '';
        }
        this._renderAll();
        this.store.removeNode(nodeId);  // 双写 Store
        this._markDirty();
    }

    _deleteSelectedNodes() {
        if (!this.selected.size) return;
        const ids = new Set(this.selected);
        // v2.5.40：先过滤 Engine 端 → 再同步 Store，避免 removeNode 通知时 Store groups 仍引用已删节点
        this.nodes = this.nodes.filter(node => !ids.has(node.id));
        this.connections = this.connections.filter(connection => !ids.has(connection.from) && !ids.has(connection.to));
        // Auto-remove groups whose children are all gone
        this.groups = this.groups.map(group => ({
            ...group,
            childIds: group.childIds.filter(cid => !ids.has(cid)),
        })).filter(group => group.childIds.length >= 2);
        // 先同步 Store groups（此时 Store 已不引用已删节点），再逐个 removeNode
        this.store.syncGroups(this.groups);
        ids.forEach(id => this.store.removeNode(id));
        this.selected.clear();
        this.selectedConnectionId = '';
        this._renderAll();
        this._markDirty();
    }

    _groupSelected() {
        if (this.selected.size < 2) return;
        const childIds = Array.from(this.selected);
        const group = {
            id: this._uid('g'),
            label: '',
            childIds,
            collapsed: false,
            _new: true,
        };
        this.groups.push(group);
        this.store.addGroup(group);  // 同步 Store
        this._renderAll();
        // 视觉反馈：组边框闪烁
        const groupEl = document.querySelector(`.group-container[data-group-id="${group.id}"]`);
        if (groupEl) { groupEl.classList.add('group-flash'); setTimeout(() => groupEl.classList.remove('group-flash'), 600); }
        // 自动聚焦标签编辑
        const labelInput = document.querySelector(`.group-label-input[data-group-id="${group.id}"]`);
        if (labelInput) { setTimeout(() => { labelInput.focus(); labelInput.select(); }, 50); }
        this._markDirty();
    }

    _syncGroupMembership(skipReAdd = false) {
        // After drag ends, check each moved node for group membership changes
        let changed = false;
        this.nodes.forEach(node => {
            const nodeCenter = { x: node.x + (node.w || 260) / 2, y: node.y + (node.h || 120) / 2 };
            const currentGroup = this.groups.find(g => g.childIds.includes(node.id));

            if (currentGroup) {
                // Check if node is still inside its group boundaries
                if (!this._isPointInGroup(nodeCenter, currentGroup)) {
                    currentGroup.childIds = currentGroup.childIds.filter(cid => cid !== node.id);
                    changed = true;
                }
            } else if (!skipReAdd) {
                // Check if node entered any group
                const targetGroup = this.groups.find(g => this._isPointInGroup(nodeCenter, g));
                if (targetGroup) {
                    targetGroup.childIds.push(node.id);
                    changed = true;
                }
            }
        });
        // Clean up empty groups
        if (changed) {
            this.groups = this.groups.filter(g => g.childIds.length >= 2);
            this.store.syncGroups(this.groups);  // v2.5.40：立即同步，防止拖拽结束→浏览器崩溃丢分组
            this._renderAll();
        }
    }

    _isPointInGroup(point, group) {
        const bounds = this._getGroupBounds(group);
        if (!bounds) return false;
        return point.x >= bounds.x && point.x <= bounds.x + bounds.w &&
               point.y >= bounds.y && point.y <= bounds.y + bounds.h;
    }

    /** 计算组的包围盒（含 padding）。无子节点返回 null。 */
    _getGroupBounds(group) {
        const children = this.nodes.filter(n => group.childIds.includes(n.id));
        if (!children.length) return null;
        const pad = group.padding || 18;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        children.forEach(n => {
            const w = n.w || 260, h = n.h || 120;
            if (n.x < minX) minX = n.x;
            if (n.y < minY) minY = n.y;
            if (n.x + w > maxX) maxX = n.x + w;
            if (n.y + h > maxY) maxY = n.y + h;
        });
        return {
            x: minX - pad, y: minY - pad,
            w: maxX - minX + pad * 2, h: maxY - minY + pad * 2,
            minX, minY, maxX, maxY, pad,
        };
    }

    _ungroupSelected() {
        const selectedIds = new Set(this.selected);
        if (!selectedIds.size) return;
        const allChildren = [];
        this.groups = this.groups.filter(group => {
            if (group.childIds.some(id => selectedIds.has(id))) {
                allChildren.push(...group.childIds);
                return false;
            }
            return true;
        });
        if (!allChildren.length) return;
        // 同步 Store（解组前只修改了 Engine 的 this.groups）
        this.store.syncGroups(this.groups);
        // 解组后选中原组内所有节点
        this.selected = new Set(allChildren);
        this.selectedConnectionId = '';
        this._renderAll();
        this._markDirty();
    }

    deleteSelectedConnection() {
        this.deleteConnection(this.selectedConnectionId);
    }

    deleteConnection(connectionId) {
        if (!connectionId) return;
        this.connections = this.connections.filter(connection => connection.id !== connectionId);
        this.store.removeConnection(connectionId);  // 同步 Store
        if (this.selectedConnectionId === connectionId) this.selectedConnectionId = '';
        if (this._contextConnectionId === connectionId) this._contextConnectionId = '';
        this._hideConnectionMenu();
        this._renderAll();
        this._markDirty();
    }

    _setSaveIndicator(text, state = '') {
        const indicator = document.getElementById('save-indicator');
        if (!indicator) return;
        clearTimeout(this._saveIndicatorTimer);
        indicator.textContent = text;
        indicator.dataset.state = state;
        if (state === 'ok') {
            this._saveIndicatorTimer = window.setTimeout(() => {
                if (indicator.dataset.state === 'ok') {
                    indicator.textContent = _t('canvas.waitingEdit','等待编辑');
                    indicator.dataset.state = '';
                }
            }, 1200);
        }
    }

    _updateNodeProp(id, prop, value) {
        const node = this.nodes.find(item => item.id === id);
        if (!node) return;
        node[prop] = value;
        this.store.updateNode(id, { [prop]: value });  // 双写 Store
        // 文本输入属性每击键触发 → 仅调度保存，不拍快照（避免每击键全量深拷贝）
        // 其他属性（select/checkbox 等）→ 正常拍快照 + 保存
        if (prop === 'text' || prop === 'userInput') {
            this._scheduleSave();
        } else {
            this._markDirty();
        }
    }

    // provider 切换：批量更新 provider_id + 清空 model（一次快照，避免两次 _snapshot）
    _switchProvider(nodeId, newProviderId) {
        var node = this.nodes.find(function(n) { return n.id === nodeId; });
        if (!node) return;
        node.provider_id = newProviderId;
        node.model = '';
        this.store.updateNode(nodeId, { provider_id: newProviderId, model: '' });
        this._markDirty();
        this._renderAllDeferred();
    }

    // Agent 切换：更新 agentId + 清除旧 lastResult（一次快照，避免残留误导）
    _switchAgent(nodeId, newAgentId) {
        var node = this.nodes.find(function(n) { return n.id === nodeId; });
        if (!node) return;
        node.agentId = newAgentId;
        node.lastResult = '';
        this.store.updateNode(nodeId, { agentId: newAgentId, lastResult: '' });
        this._markDirty();
        this._renderAllDeferred();
    }

    // ComfyUI 工作流切换：更新名称 + 清除失效 fieldId 连线
    _switchComfyWorkflow(nodeId, newWorkflow) {
        var node = this.nodes.find(function(n) { return n.id === nodeId; });
        if (!node) return;
        node.comfyWorkflow = newWorkflow;
        // v2.5.53：保留新工作流中仍然存在的 fieldId 连线，避免同名端口映射丢失
        var wf = (this._comfyWfList||[]).find(function(w) { return w.name === newWorkflow; });
        var keepIds = new Set((wf?._fields||[]).map(function(f) { return f.id; }));
        this.connections = this.connections.filter(function(c) {
            return !(c.to === nodeId && c.fieldId && !keepIds.has(c.fieldId));
        });
        this.store.connections = this.connections.map(function(c) { return Object.assign({}, c); });
        this.store._rebuildIndex();
        this.store.updateNode(nodeId, { comfyWorkflow: newWorkflow });
        this._markDirty();
        this._renderAllDeferred();
    }

    // 生图/生视频节点尺寸切换（批量设置 _customWH + size，避免两次 _snapshot）
    _setGenSize(nodeId, value) {
        var node = this.nodes.find(function(n) { return n.id === nodeId; });
        if (!node) return;
        if (value === 'custom_wh') {
            node._customWH = true;
            node.size = (node._customW || 1024) + 'x' + (node._customH || 1024);
        } else {
            node._customWH = false;
            node.size = value;
        }
        this.store.updateNode(nodeId, { _customWH: node._customWH, size: node.size });
        this._markDirty();
        this._renderAllDeferred();
    }

    _removeImage(nodeId) {
        const node = this.nodes.find(item => item.id === nodeId);
        if (!node) return;
        node.url = '';
        node.imageName = '';
        node.imageWidth = 0;
        node.imageHeight = 0;
        this.store.updateNode(nodeId, { url: '', imageName: '', imageWidth: 0, imageHeight: 0 });
        this._renderAll();
        this._markDirty();
    }

    _loadImageSize(url) {
        return new Promise((resolve) => {
            var img = new Image();
            img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
            img.onerror = () => resolve({ w: 0, h: 0 });
            img.onabort = () => resolve({ w: 0, h: 0 });  // v2.5.40：防止快速翻页时 Promise 永不 resolve
            img.src = url;
        });
    }
    // 注意：所有 _loadImageSize 的调用方都通过 if (node.url === url) 守卫防竞态——
    // 快速替换图片时，旧 URL 的回调会被自动跳过，尺寸不会错乱。

    /** 图片尺寸加载后：同步 Store + 自动调整节点高度适配图片比例 */
    _syncImageNodeSize(node, w, h) {
        node.imageWidth = w;
        node.imageHeight = h;
        this.store.updateNode(node.id, { imageWidth: w, imageHeight: h });
        // 根据容器宽度和图片比例计算需要的节点高度
        if (w > 0 && h > 0) {
            const containerW = node.w || 260;
            const renderedImgH = containerW * h / w;
            const overhead = (node.imageName ? 20 : 0) + 40;  // 文件名行 + 按钮行
            const newH = Math.max(120, Math.round(renderedImgH + overhead));
            if (Math.abs((node.h || 100) - newH) > 10) {
                node.h = newH;
                this.store.updateNode(node.id, { h: newH });
            }
        }
    }

    // 输出节点缩略图点击：单击→创建图片节点，双击→灯箱
    _onOutputImageClick(event, url) {
        var self = this;
        // 用定时器区分单击/双击：120ms 内再次点击视为双击
        if (self._outputClickTimer) {
            // 第二次点击 → 双击 → 开灯箱，取消创建节点
            clearTimeout(self._outputClickTimer);
            self._outputClickTimer = null;
            self._showLightbox(url, 'image');
            return;
        }
        // 第一次点击 → 等待 120ms，无第二次点击则执行单击动作
        self._outputClickTimer = setTimeout(function() {
            self._outputClickTimer = null;
            var center = self._screenToWorld(window.innerWidth / 2, window.innerHeight / 2);
            var node = self.createNode('image', center, { url: url, imageName: url.split('/').pop() || '', imageWidth: 0, imageHeight: 0 });
            self._loadImageSize(url).then(function(size) {
                if (node.url === url && size.w) {
                    self._syncImageNodeSize(node, size.w, size.h);
                    // v2.5.50：直接更新 DOM 尺寸替代 _renderAll() 全量重建
                    var nel = self.nodesEl && self.nodesEl.querySelector('[data-id="' + node.id + '"]');
                    if (nel) { nel.style.width = (node.w || 260) + 'px'; nel.style.height = (node.h || 120) + 'px'; }
                    self._renderLinks();
                }
            });
        }, 120);
    }

    async _loadAgentOpts() {
        try {
            const data = await apiJson('/api/agents');
            this._agentList = data.agents || [];
        } catch(e) { this._agentList = []; }
    }

    _getProviderId(modelType) {
        // 返回第一个匹配类型的平台。modelType: 'image' | 'video' | undefined(any)
        try {
            const provs = getCachedProviders();
            let p;
            if (modelType === 'video') {
                p = provs.find(x => (x.video_models||[]).length > 0);
            } else if (modelType === 'image') {
                p = provs.find(x => (x.image_models||[]).length > 0);
            } else {
                p = provs.find(x => (x.image_models||[]).length > 0 || (x.video_models||[]).length > 0);
            }
            return p ? p.id : (provs[0] ? provs[0].id : null);
        } catch(e) { return null; }
    }

    async _loadComfyWorkflows() {
        try { const d=await apiJson('/api/comfyui/workflows'); this._comfyWfList=d.workflows||[];
            // 并行加载每个工作流的详细配置（含字段映射）
            await Promise.all(this._comfyWfList.map(async (w) => {
                try {
                    const wd = await apiJson('/api/comfyui/workflows/' + encodeURIComponent(w.name));
                    w._fields = (wd.config?.fields) || [];
                } catch(e) { w._fields = []; }
            }));
            // 工作流列表加载完成后重新渲染（更新下拉框选中状态）
            this._renderAll();
        } catch(e) { this._comfyWfList=[]; }
    }

    // 供外部调用（ComfyUI 页面增删工作流后刷新画布节点下拉框）
    async refreshComfyWorkflows() {
        await this._loadComfyWorkflows();
    }

    async _loadVideoModelParams() {
        try {
            const d = await apiJson('/api/video/model-params');
            this._videoDurations = d.durations || {};
            this._videoResolutions = d.resolutions || {};
            // 从后端加载轮询参数（与后端 VIDEO_POLL_TIMEOUT/INTERVAL 保持同步）
            if (d.poll_timeout && d.poll_interval) {
                this._videoPollTimeoutS = d.poll_timeout;
                this._videoPollIntervalS = d.poll_interval;
            }
        } catch(e) {
            this._videoDurations = this._videoDurations || {};
            this._videoResolutions = this._videoResolutions || {};
        }
    }

    _copySelected() {
        this._clipboard = this.nodes.filter(n => this.selected.has(n.id)).map(n => this._deepCloneNode(n));
    }

    _pasteNodes() {
        if (!this._clipboard.length) return;
        const offset = 40;
        const newIds = [];
        this._clipboard.forEach((src, i) => {
            const newNode = this._deepCloneNode({...src, id: this._uid(src.type), x: src.x + offset * (i + 1), y: src.y + offset * (i + 1), runState: 'idle', runMessage: ''});
            this.nodes.push(newNode);
            this.store.addNode(newNode);  // 同步 Store
            newIds.push(newNode.id);
        });
        // Re-create connections between pasted nodes（只执行一次，不在外层循环内）
        const pasteConns = this.connections.filter(c =>
            this._clipboard.some(s => s.id === c.from || s.id === c.to)
        );
        pasteConns.forEach(c => {
            const fromIdx = this._clipboard.findIndex(s => s.id === c.from);
            const toIdx = this._clipboard.findIndex(s => s.id === c.to);
            if (fromIdx >= 0 && toIdx >= 0) {
                const newConn = { id: this._uid('c'), from: newIds[fromIdx], to: newIds[toIdx] };
                this.connections.push(newConn);
                this.store.addConnection(newConn);  // 同步 Store
            }
        });
        this.selected = new Set(newIds);
        this.selectedConnectionId = '';
        this._renderAll();
        this._markDirty();
    }

    // zoom/undo/viewport 方法已拆分到 canvas-viewport.js 和 canvas-undo.js

    _ensureOutput(sourceId) {
        // 1) 已有连线到输出节点 → 复用
        const existing = this.connections.find(connection => {
            const target = this.nodes.find(node => node.id === connection.to);
            return connection.from === sourceId && target?.type === 'output';
        });
        if (existing) {
            const node = this.nodes.find(item => item.id === existing.to);
            if (node) return node;
        }

        const source = this.nodes.find(item => item.id === sourceId);

        // 2) 存在无入边的孤立输出节点 → 优先复用（用户手动放置的）
        const connectedOutputIds = new Set(this.connections.map(c => c.to));
        const orphanOutput = this.nodes.find(n => n.type === 'output' && !connectedOutputIds.has(n.id));
        if (orphanOutput) {
            const conn = { id: this._uid('c'), from: sourceId, to: orphanOutput.id };
            this.connections.push(conn);
            this.store.addConnection(conn);
            return orphanOutput;
        }

        // 3) 新建输出节点
        const output = this.createNode('output', {
            x: (source?.x || 0) + 340,
            y: source?.y || 0,
        });
        const conn = { id: this._uid('c'), from: sourceId, to: output.id };
        this.connections.push(conn);
        this.store.addConnection(conn);  // 同步 Store
        return output;
    }

    /** 管线产出写入 output 节点后同步 Store */
    _syncOutputToStore(node) {
        this.store.updateNode(node.id, {
            images: (node.images || []).slice(),
            videos: (node.videos || []).slice(),
            outputText: node.outputText || '',
        });
    }

    _showCreateMenu(x, y) {
        const menu = document.getElementById('create-menu');
        if (!menu) return;
        this._hideConnectionMenu();
        const hasSelection = this.selected.size > 0;
        const hasMulti = this.selected.size >= 2;
        menu.innerHTML = `
            ${!hasSelection ? `
            <button onclick="window._canvas.createNode('image');document.getElementById('create-menu').style.display='none'">${_tt('图片节点')}</button>
            <button onclick="window._canvas.createNode('prompt');document.getElementById('create-menu').style.display='none'">${_tt('提示词节点')}</button>
            <button onclick="window._canvas.createNode('image_gen');document.getElementById('create-menu').style.display='none'">🖼 ${_tt('图片生成')}</button>
            <button onclick="window._canvas.createNode('video_gen');document.getElementById('create-menu').style.display='none'">🎬 ${_tt('视频生成')}</button>
            <button onclick="window._canvas.createNode('agent');document.getElementById('create-menu').style.display='none'">${_tt('Agent 节点')}</button>
            <button onclick="window._canvas.createNode('loop');document.getElementById('create-menu').style.display='none'">${_tt('列队节点')}</button>
            <button onclick="window._canvas.createNode('output');document.getElementById('create-menu').style.display='none'">${_tt('输出节点')}</button>
            <button onclick="window._canvas.createNode('comfy');document.getElementById('create-menu').style.display='none'">${_tt('ComfyUI 节点')}</button>
            ` : ''}
            ${hasSelection ? `<div class="menu-section-title">${_t('contextMenu.selection','选中操作')}</div>` : ''}
            ${hasSelection ? `<button onclick="window._canvas._copySelected();document.getElementById('create-menu').style.display='none'">${_t('contextMenu.copy','复制 Ctrl+C')}</button>` : ''}
            ${this._clipboard?.length ? `<button onclick="window._canvas._pasteNodes();document.getElementById('create-menu').style.display='none'">${_t('contextMenu.paste','粘贴 Ctrl+V')}</button>` : ''}
            ${hasMulti ? `<button onclick="window._canvas._groupSelected();document.getElementById('create-menu').style.display='none'">${_t('contextMenu.group','打组 Ctrl+G')}</button>` : ''}
            ${hasSelection && this.groups.some(g => g.childIds.some(cid => this.selected.has(cid))) ? `<button onclick="window._canvas._ungroupSelected();document.getElementById('create-menu').style.display='none'">${_t('contextMenu.ungroup','解组 Ctrl+Shift+G')}</button>` : ''}
            ${hasSelection ? `<button onclick="window._canvas._deleteSelectedNodes();document.getElementById('create-menu').style.display='none'" style="color:#dc2626;">${_t('contextMenu.deleteSelected','删除 Delete')}</button>` : ''}
        `;
        menu.style.display = 'block';
        menu.style.left = `${Math.min(x, window.innerWidth - 190)}px`;
        menu.style.top = `${Math.min(y, window.innerHeight - 260)}px`;
    }

    _showConnectionMenu(x, y, connectionId) {
        if (!this.connectionMenuEl || !connectionId) return;
        this._contextConnectionId = connectionId;
        const menu = this.connectionMenuEl;
        menu.innerHTML = `
            <button onclick="window._canvas.confirmDeleteConnectionFromMenu()">${_t('contextMenu.deleteConnection','删除连线')}</button>
        `;
        menu.style.display = 'block';
        menu.style.left = `${Math.min(x, window.innerWidth - 160)}px`;
        menu.style.top = `${Math.min(y, window.innerHeight - 80)}px`;
        this.selectedConnectionId = connectionId;
        const createMenu = document.getElementById('create-menu');
        if (createMenu) createMenu.style.display = 'none';
    }

    _hideConnectionMenu() {
        if (!this.connectionMenuEl) return;
        this.connectionMenuEl.style.display = 'none';
    }

    _hideMenus() {
        const createMenu = document.getElementById('create-menu');
        if (createMenu) createMenu.style.display = 'none';
        this._hideConnectionMenu();
        this._menuPoint = null;  // 清除右键位置残留
    }

    _uid(prefix = 'n') {
        var r = Math.random().toString(36).slice(2, 10);
        while (r.length < 4) r += Math.random().toString(36).slice(2, 10);
        return prefix + '_' + r.slice(0, 8);
    }

    _esc(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // HTML 属性内 JS 字符串上下文转义（用于 onclick/ondblclick 中的动态值）
    // v2.5.40 修复转义顺序：\ → ' → " → &（& 必须最后，否则 &amp; 被后续替换破坏）
    _escJs(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/\\/g, '\\\\')    // ① 反斜杠（必须在引号前，防止 \\' 被双重转义）
            .replace(/'/g, "\\'")      // ② 单引号（JS 字符串分隔符）
            .replace(/"/g, '&quot;')   // ③ 双引号（HTML 属性分隔符）
            .replace(/&/g, '&amp;');   // ④ & 符号（HTML 实体起始符，必须最后）
    }
}
