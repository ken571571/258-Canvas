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

        window._canvas = this;
        this._initEvents();
        this._renderAll();
    }

    async init() {
        await refreshProviders();
        await this._loadAgentOpts();
        this._loadComfyWorkflows().catch(()=>{});
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
            body: JSON.stringify({ title: '默认画布' }),
        });
        const data = await response.json();
        return data.canvas.id;
    }

    async load() {
        if (!this.canvasId) return;
        try {
            const response = await apiFetch(`/api/boards/${this.canvasId}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            const canvas = data.canvas || {};
            // 记录服务器时间戳用于乐观并发控制
            this._canvasUpdatedAt = canvas.updated_at || 0;
            this.nodes = (canvas.nodes || []).map(node => ({
                ...node,
                runState: node.runState && node.runState !== 'idle' ? 'idle' : (node.runState || 'idle'),
                runMessage: node.runMessage || '',
            }));
            this._undoStack = [{ nodes: this.nodes.map(n => ({...n})), connections: this.connections.map(c => ({...c})), groups: this.groups.map(g => ({...g, childIds: [...g.childIds]})) }];
            this._undoIndex = 0;
            this.connections = canvas.connections || [];
            this.groups = canvas.groups || [];
            if (canvas.viewport) this.view = canvas.viewport;
            this._renderAll();
        } catch (error) {
            if (String(error.message || '').includes('404')) {
                const id = await this._createDefaultCanvas();
                this.canvasId = id;
                localStorage.setItem('canvas_current_id', id);
                return this.load();
            }
            console.warn('load canvas failed, continue with empty board', error);
            this._renderAll();
        }
    }

    async save() {
        if (!this.canvasId || String(this.canvasId).startsWith('local_')) return;
        const payload = {
            nodes: this.nodes,
            connections: this.connections,
            groups: this.groups,
            viewport: this.view,
            base_updated_at: this._canvasUpdatedAt,
            client_id: this._clientId || '',
        };
        try {
            const response = await apiFetch(`/api/boards/${this.canvasId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                silent: true,
            });
            if (response.status === 409) {
                // 冲突：服务器版本更新，自动刷新本地数据
                try {
                    const errData = await response.json();
                    const detail = errData?.detail || {};
                    if (detail.canvas) {
                        this.nodes = (detail.canvas.nodes || []).map(n => ({...n, runState: 'idle', runMessage: ''}));
                        this.connections = detail.canvas.connections || [];
                        this.groups = detail.canvas.groups || [];
                        this.view = detail.canvas.viewport || this.view;
                        this._canvasUpdatedAt = detail.canvas.updated_at || 0;
                        this._undoStack = [{ nodes: this.nodes.map(n => ({...n})), connections: this.connections.map(c => ({...c})), groups: this.groups.map(g => ({...g, childIds: [...g.childIds]})) }];
                        this._undoIndex = 0;
                        this.selected.clear();
                        this.selectedConnectionId = '';
                        this._renderAll();
                        alert('画布已被其他页面更新，已刷新为最新版本。请重新尝试您的编辑。');
                        return;
                    }
                } catch (_) { /* fall through to error */ }
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            // 保存成功 → 更新本地时间戳
            const data = await response.json().catch(() => ({}));
            this._canvasUpdatedAt = (data.canvas || {}).updated_at || 0;
            this._setSaveIndicator('已保存', 'ok');
        } catch (error) {
            console.error('save failed', error);
            this._setSaveIndicator('保存失败', 'error');
        }
    }

    createNode(type, point = null) {
        const pt = point || this._menuPoint || this._screenToWorld(window.innerWidth / 2, window.innerHeight / 2);
        const labels = {
            image: '图片', prompt: '提示词',
            generator: '生成',      // 兼容旧节点
            image_gen: '图片生成',
            video_gen: '视频生成',
            agent: 'Agent', loop: '列队', output: '输出', comfy: 'ComfyUI',
        };
        const node = {
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
            model: type === 'image_gen' ? 'dall-e-3' : (type === 'video_gen' ? 'veo3-fast' : (type === 'generator' ? 'dall-e-3' : 'gpt-4o-mini')),
            systemPrompt: '',
            outputText: '',
            lastResult: '',
            images: [],
            agentId: '',
            comfyWorkflow: '',
            loopCount: 3,
            loopMode: 'serial',
            loopImageInput: true,
            loopStart: 1,
            hasConfig: false,
            knowledgeBases: [],
            skills: [],
            userInput: '',
            runState: 'idle',
            runMessage: '',
        };
        this.nodes.push(node);
        this._renderAll();
        this._markDirty();
        return node;
    }

    _deleteNode(nodeId) {
        this.nodes = this.nodes.filter(node => node.id !== nodeId);
        this.connections = this.connections.filter(connection => connection.from !== nodeId && connection.to !== nodeId);
        this.selected.delete(nodeId);
        if (this.selectedConnectionId && !this.connections.some(connection => connection.id === this.selectedConnectionId)) {
            this.selectedConnectionId = '';
        }
        this._renderAll();
        this._markDirty();
    }

    _deleteSelectedNodes() {
        if (!this.selected.size) return;
        const ids = new Set(this.selected);
        this.nodes = this.nodes.filter(node => !ids.has(node.id));
        this.connections = this.connections.filter(connection => !ids.has(connection.from) && !ids.has(connection.to));
        // Auto-remove groups whose children are all gone
        this.groups = this.groups.map(group => ({
            ...group,
            childIds: group.childIds.filter(cid => !ids.has(cid)),
        })).filter(group => group.childIds.length >= 2);
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
            this._renderAll();
        }
    }

    _isPointInGroup(point, group) {
        const children = this.nodes.filter(n => group.childIds.includes(n.id));
        if (!children.length) return false;
        const padding = group.padding || 18;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        children.forEach(n => {
            if (n.x < minX) minX = n.x;
            if (n.y < minY) minY = n.y;
            if (n.x + (n.w || 260) > maxX) maxX = n.x + (n.w || 260);
            if (n.y + (n.h || 120) > maxY) maxY = n.y + (n.h || 120);
        });
        return point.x >= minX - padding && point.x <= maxX + padding &&
               point.y >= minY - padding && point.y <= maxY + padding;
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
        if (this.selectedConnectionId === connectionId) this.selectedConnectionId = '';
        if (this._contextConnectionId === connectionId) this._contextConnectionId = '';
        this._hideConnectionMenu();
        this._renderAll();
        this._markDirty();
    }

    _snapshot() {
        // 保存状态快照用于撤销
        this._undoStack = this._undoStack.slice(0, this._undoIndex + 1);
        this._undoStack.push({
            nodes: this.nodes.map(n => ({...n})),
            connections: this.connections.map(c => ({...c})),
            groups: this.groups.map(g => ({...g, childIds: [...g.childIds]})),
        });
        if (this._undoStack.length > 50) this._undoStack.shift();
        this._undoIndex = this._undoStack.length - 1;
    }

    undo() {
        if (this._undoIndex < 0) return;
        const snap = this._undoStack[this._undoIndex];
        if (!snap) return;
        this.nodes = snap.nodes.map(n => ({...n}));
        this.connections = snap.connections.map(c => ({...c}));
        this.groups = snap.groups.map(g => ({...g, childIds: [...g.childIds]}));
        this._undoIndex--;
        this.selected.clear();
        this.selectedConnectionId = '';
        this._renderAll();
        this.save();
    }

    _markDirty() {
        this._snapshot();
        this._setSaveIndicator('待保存');
        clearTimeout(this._saveDebounceTimer);
        this._saveDebounceTimer = setTimeout(() => this.save(), 800);
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
                    indicator.textContent = '等待编辑';
                    indicator.dataset.state = '';
                }
            }, 1200);
        }
    }

    _updateNodeProp(id, prop, value) {
        const node = this.nodes.find(item => item.id === id);
        if (!node) return;
        node[prop] = value;
        this._markDirty();
    }

    _removeImage(nodeId) {
        const node = this.nodes.find(item => item.id === nodeId);
        if (!node) return;
        node.url = '';
        node.imageName = '';
        node.imageWidth = 0;
        node.imageHeight = 0;
        this._renderAll();
        this._markDirty();
    }

    _loadImageSize(url) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
            img.onerror = () => resolve({ w: 0, h: 0 });
            img.src = url;
        });
    }

    async _loadAgentOpts() {
        try {
            const data = await apiJson('/api/agents');
            this._agentList = data.agents || [];
        } catch(e) { this._agentList = []; }
    }

    _getProviderId() {
        // 返回第一个有生图或视频模型的平台
        try {
            const provs = getCachedProviders();
            const p = provs.find(x => (x.image_models||[]).length > 0 || (x.video_models||[]).length > 0);
            return p ? p.id : 'apimart';
        } catch(e) { return 'apimart'; }
    }

    async _loadComfyWorkflows() {
        try { const d=await apiJson('/api/comfyui/workflows'); this._comfyWfList=d.workflows||[];
            // 加载每个工作流的配置（含字段映射）
            for(const w of this._comfyWfList){
                try{const wd=await apiJson('/api/comfyui/workflows/'+encodeURIComponent(w.name));w._fields=(wd.config?.fields)||[];}catch(e){w._fields=[];}
            }
            // 工作流列表加载完成后重新渲染（更新下拉框选中状态）
            this._renderAll();
        } catch(e) { this._comfyWfList=[]; }
    }

    _copySelected() {
        this._clipboard = this.nodes.filter(n => this.selected.has(n.id)).map(n => ({...n}));
    }

    _pasteNodes() {
        if (!this._clipboard.length) return;
        const offset = 40;
        const newIds = [];
        this._clipboard.forEach((src, i) => {
            const newNode = {...src, id: this._uid(src.type), x: src.x + offset * (i + 1), y: src.y + offset * (i + 1), runState: 'idle', runMessage: ''};
            this.nodes.push(newNode);
            newIds.push(newNode.id);
        });
        // Re-create connections between pasted nodes
        this._clipboard.forEach((src, i) => {
            this.connections.filter(c => this._clipboard.some(s => s.id === c.from || s.id === c.to)).forEach(c => {
                const fromIdx = this._clipboard.findIndex(s => s.id === c.from);
                const toIdx = this._clipboard.findIndex(s => s.id === c.to);
                if (fromIdx >= 0 && toIdx >= 0) {
                    this.connections.push({ id: this._uid('c'), from: newIds[fromIdx], to: newIds[toIdx] });
                }
            });
        });
        this.selected = new Set(newIds);
        this.selectedConnectionId = '';
        this._renderAll();
        this._markDirty();
    }

    zoomIn() { this._applyZoom(1.2); }
    zoomOut() { this._applyZoom(0.8); }
    zoomFit() {
        if (!this.nodes.length) return;
        const padding = 80;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        this.nodes.forEach(n => {
            if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
            if (n.x + (n.w||260) > maxX) maxX = n.x + (n.w||260);
            if (n.y + (n.h||120) > maxY) maxY = n.y + (n.h||120);
        });
        const rect = this.board.getBoundingClientRect();
        const scaleX = (rect.width - padding * 2) / (maxX - minX + padding * 2);
        const scaleY = (rect.height - padding * 2) / (maxY - minY + padding * 2);
        this.view.scale = Math.min(scaleX, scaleY, 2);
        this.view.x = -minX * this.view.scale + padding;
        this.view.y = -minY * this.view.scale + padding;
        this._renderTransform();
    }
    _applyZoom(delta) {
        const rect = this.board.getBoundingClientRect();
        const mx = rect.width / 2, my = rect.height / 2;
        const newScale = Math.max(0.1, Math.min(5, this.view.scale * delta));
        this.view.x -= (mx - this.view.x) * (newScale / this.view.scale - 1);
        this.view.y -= (my - this.view.y) * (newScale / this.view.scale - 1);
        this.view.scale = newScale;
        this._renderTransform();
    }

    _ensureOutput(sourceId) {
        const existing = this.connections.find(connection => {
            const target = this.nodes.find(node => node.id === connection.to);
            return connection.from === sourceId && target?.type === 'output';
        });
        if (existing) {
            const node = this.nodes.find(item => item.id === existing.to);
            if (node) return node;
        }

        const source = this.nodes.find(item => item.id === sourceId);
        const output = this.createNode('output', {
            x: (source?.x || 0) + 340,
            y: source?.y || 0,
        });
        this.connections.push({ id: this._uid('c'), from: sourceId, to: output.id });
        return output;
    }

    _showCreateMenu(x, y) {
        const menu = document.getElementById('create-menu');
        if (!menu) return;
        this._hideConnectionMenu();
        const hasSelection = this.selected.size > 0;
        const hasMulti = this.selected.size >= 2;
        menu.innerHTML = `
            ${!hasSelection ? `
            <button onclick="window._canvas.createNode('image');document.getElementById('create-menu').style.display='none'">图片节点</button>
            <button onclick="window._canvas.createNode('prompt');document.getElementById('create-menu').style.display='none'">提示词节点</button>
            <button onclick="window._canvas.createNode('image_gen');document.getElementById('create-menu').style.display='none'">🖼 图片生成</button>
            <button onclick="window._canvas.createNode('video_gen');document.getElementById('create-menu').style.display='none'">🎬 视频生成</button>
            <button onclick="window._canvas.createNode('agent');document.getElementById('create-menu').style.display='none'">Agent 节点</button>
            <button onclick="window._canvas.createNode('loop');document.getElementById('create-menu').style.display='none'">列队节点</button>
            <button onclick="window._canvas.createNode('output');document.getElementById('create-menu').style.display='none'">输出节点</button>
            <button onclick="window._canvas.createNode('comfy');document.getElementById('create-menu').style.display='none'">ComfyUI 节点</button>
            ` : ''}
            ${hasSelection ? `<div class="menu-section-title">选中操作</div>` : ''}
            ${hasSelection ? `<button onclick="window._canvas._copySelected();document.getElementById('create-menu').style.display='none'">复制 Ctrl+C</button>` : ''}
            ${this._clipboard?.length ? `<button onclick="window._canvas._pasteNodes();document.getElementById('create-menu').style.display='none'">粘贴 Ctrl+V</button>` : ''}
            ${hasMulti ? `<button onclick="window._canvas._groupSelected();document.getElementById('create-menu').style.display='none'">打组 Ctrl+G</button>` : ''}
            ${hasSelection && this.groups.some(g => g.childIds.some(cid => this.selected.has(cid))) ? `<button onclick="window._canvas._ungroupSelected();document.getElementById('create-menu').style.display='none'">解组 Ctrl+Shift+G</button>` : ''}
            ${hasSelection ? `<button onclick="window._canvas._deleteSelectedNodes();document.getElementById('create-menu').style.display='none'" style="color:#dc2626;">删除 Delete</button>` : ''}
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
            <button onclick="window._canvas.confirmDeleteConnectionFromMenu()">删除连线</button>
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
    }

    _uid(prefix = 'n') {
        return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
    }

    _esc(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
}
