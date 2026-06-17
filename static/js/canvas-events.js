CanvasEngine.prototype._initEvents = function() {
    // 点击画布区域自动聚焦（否则快捷键不生效）
    // 双击编辑节点描述（事件委托，不随 DOM 重建丢失）
    this.nodesEl.addEventListener('dblclick', event => {
        const descEl = event.target.closest('[data-node-desc]');
        if (!descEl) return;
        event.stopPropagation();
        const nodeId = descEl.dataset.nodeDesc;
        const node = this.nodes.find(n => n.id === nodeId);
        if (!node) return;
        const input = document.createElement('input');
        input.value = node.desc || '';
        input.maxLength = 20;
        input.style.cssText = 'width:110px;height:20px;border:1px solid var(--accent);border-radius:4px;padding:0 4px;font-size:10px;font-weight:600;background:var(--bg);color:var(--text);outline:none;';
        input.onblur = () => { node.desc = input.value.trim().slice(0, 20); this._renderAll(); this._markDirty(); };
        input.onkeydown = e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { input.value = node.desc || ''; input.blur(); } };
        descEl.replaceWith(input);
        input.focus(); input.select();
    });

    // 小地图点击
    const minimapEl = document.getElementById('minimap');
    if (minimapEl) minimapEl.addEventListener('click', e => this._onMinimapClick(e));

    // 允许画布接收拖放
    this.board.addEventListener('dragover', event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
    this.board.addEventListener('drop', event => this._onBoardDrop(event));

    this.board.addEventListener('mousedown', () => this.board.focus());

    this.linksEl.addEventListener('click', event => {
        const hit = event.target.closest('[data-connection-id]');
        if (!hit) return;
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = hit.dataset.connectionId || '';
        this._hideConnectionMenu();
        this._renderAll();
    });

    this.handlesEl?.addEventListener('click', event => {
        const handle = event.target.closest('[data-connection-action="delete"]');
        if (!handle) return;
        event.preventDefault();
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = handle.dataset.connectionId || '';
        this._hideConnectionMenu();
        this._renderAll();
    });

    this.handlesEl?.addEventListener('contextmenu', event => {
        const handle = event.target.closest('[data-connection-action="delete"]');
        if (!handle) return;
        event.preventDefault();
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = handle.dataset.connectionId || '';
        this._showConnectionMenu(event.clientX, event.clientY, this.selectedConnectionId);
        this._renderAll();
    });

    this.board.addEventListener('mousedown', event => {
        if (!this._isBoardBackground(event.target)) return;
        if (event.button === 1 || (event.button === 0 && this._spacePressed)) {
            event.preventDefault();
            this._startBoardPan(event);
            return;
        }
        if (event.button !== 0) return;
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
            this._startMarquee(event);
        } else {
            this._startBoardPan(event);
        }
    });

    this.board.addEventListener('wheel', event => {
        event.preventDefault();
        const delta = event.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.1, Math.min(5, this.view.scale * delta));
        const rect = this.board.getBoundingClientRect();
        const mx = event.clientX - rect.left;
        const my = event.clientY - rect.top;
        this.view.x -= (mx - this.view.x) * (newScale / this.view.scale - 1);
        this.view.y -= (my - this.view.y) * (newScale / this.view.scale - 1);
        this.view.scale = newScale;
        this._renderTransform();
    }, { passive: false });

    this.board.addEventListener('contextmenu', event => {
        if (!this._isBoardBackground(event.target)) return;
        event.preventDefault();
        this._hideConnectionMenu();
        this._menuPoint = this._screenToWorld(event.clientX, event.clientY);
        this._showCreateMenu(event.clientX, event.clientY);
    });

    document.addEventListener('click', event => {
        if (event.target.closest('#create-menu') || event.target.closest('#connection-menu')) return;
        this._hideMenus();
    });

    window.addEventListener('mousemove', event => {
        if (this._dragBoard) {
            this.view.x = event.clientX - this._dragBoard.x;
            this.view.y = event.clientY - this._dragBoard.y;
            this._renderTransform();
        }

        if (this._dragNodes) {
            const pointer = this._screenToWorld(event.clientX, event.clientY);
            const dx = pointer.x - this._dragNodes.pointerStart.x;
            const dy = pointer.y - this._dragNodes.pointerStart.y;
            this._dragNodes.items.forEach(item => {
                item.node.x = item.startX + dx;
                item.node.y = item.startY + dy;
            });
            this._renderAll();
        }

        if (this._marquee) {
            const rect = this.board.getBoundingClientRect();
            this._marquee.endLocal = {
                x: event.clientX - rect.left,
                y: event.clientY - rect.top,
            };
            this._renderMarquee();
        }

        if (this._linkFrom) {
            this._tempPointer = this._screenToWorld(event.clientX, event.clientY);
            this._renderLinks();
        }
    });

    window.addEventListener('mouseup', event => {
        if (this._dragBoard) {
            this._dragBoard = null;
            this.board.classList.remove('panning');
        }

        if (this._dragNodes) {
            const wasCtrlExtract = !!this._dragNodes.ctrlExtract;
            this._dragNodes = null;
            this._syncGroupMembership(wasCtrlExtract);
            this._markDirty();
        }

        if (this._marquee) {
            this._finishMarquee();
        }

        if (this._linkFrom) {
            this._finishConnectionDrag(event);
        }
    });

    // Space 保持全局监听（画布任意位置都能按住空格拖拽）
    window.addEventListener('keydown', event => {
        if (event.code === 'Space' && !event.repeat) {
            this._spacePressed = true;
            this.board.classList.add('panning');
        }
    });
    window.addEventListener('keyup', event => {
        if (event.code === 'Space') {
            this._spacePressed = false;
            this.board.classList.remove('panning');
        }
    });

    // 快捷键 — 参照 888 方案，在 window 上直接监听（不用 capture）
    window.addEventListener('keydown', event => {
        const tag = String((event.target || document.activeElement)?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || (event.target || document.activeElement)?.isContentEditable) return;

        // Ctrl+G: 打组
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key || '').toLowerCase() === 'g') {
            event.preventDefault();
            if (this.selected.size >= 2) this._groupSelected();
            return;
        }
        // Ctrl+Shift+G: 解组
        if ((event.ctrlKey || event.metaKey) && event.shiftKey && String(event.key || '').toLowerCase() === 'g') {
            event.preventDefault();
            if (this.selected.size) this._ungroupSelected();
            return;
        }
        // Ctrl+Z: 撤销
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key || '').toLowerCase() === 'z') {
            event.preventDefault();
            this.undo();
            return;
        }
        // Ctrl+C: 复制选中节点
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key || '').toLowerCase() === 'c') {
            event.preventDefault();
            this._clipboard = this.nodes.filter(n => this.selected.has(n.id)).map(n => ({...n}));
            return;
        }
        // Ctrl+V: 粘贴节点
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key || '').toLowerCase() === 'v') {
            event.preventDefault();
            this._pasteNodes();
            return;
        }
        // ?: 快捷键面板
        if (event.key === '?' && !event.ctrlKey && !event.metaKey) {
            event.preventDefault();
            document.getElementById('shortcutPanel')?.classList.toggle('open');
            return;
        }

        // Delete/Backspace: 删除
        if (event.key === 'Delete' || event.key === 'Backspace') {
            if (this.selectedConnectionId) {
                event.preventDefault();
                this.deleteSelectedConnection();
                return;
            }
            if (this.selected.size) {
                event.preventDefault();
                this._deleteSelectedNodes();
            }
        }
    });

};

CanvasEngine.prototype._startBoardPan = function(event) {
    this._dragBoard = {
        x: event.clientX - this.view.x,
        y: event.clientY - this.view.y,
    };
    this.board.classList.add('panning');
    this.selected.clear();
    this.selectedConnectionId = '';
    this._renderAll();
};

CanvasEngine.prototype._startMarquee = function(event) {
    const rect = this.board.getBoundingClientRect();
    const startLocal = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
    };
    this._marquee = {
        additive: event.shiftKey,
        startLocal,
        endLocal: startLocal,
    };
    if (!this._marquee.additive) {
        this.selected.clear();
        this.selectedConnectionId = '';
    }
    this._renderAll();
};

CanvasEngine.prototype._finishMarquee = function() {
    if (!this._marquee) return;

    const selectionWorld = this._localRectToWorld(this._marquee.startLocal, this._marquee.endLocal);
    const nextSelected = this._marquee.additive ? new Set(this.selected) : new Set();

    this.nodes.forEach(node => {
        const width = node.w || 260;
        const height = node.h || 120;
        const intersects = !(
            node.x + width < selectionWorld.x ||
            node.x > selectionWorld.x + selectionWorld.w ||
            node.y + height < selectionWorld.y ||
            node.y > selectionWorld.y + selectionWorld.h
        );
        if (intersects) nextSelected.add(node.id);
    });

    this.selected = nextSelected;
    this.selectedConnectionId = '';
    this._marquee = null;
    this._renderAll();
};

CanvasEngine.prototype._finishConnectionDrag = function(event) {
    let targetPort = null;
    // 先试 elementFromPoint
    const target = document.elementFromPoint(event.clientX, event.clientY);
    targetPort = target?.closest?.('.port');

    // 如果没找到 port，检查是否在 ComfyUI 节点的左侧蓝点区域
    if (!targetPort) {
        const worldPt = this._screenToWorld(event.clientX, event.clientY);
        const comfyNode = this.nodes.find(n=>{
            if (n.type!=='comfy') return false;
            const nw=n.w||260, nh=n.h||120;
            return worldPt.x>=n.x-15 && worldPt.x<=n.x+5 && worldPt.y>=n.y && worldPt.y<=n.y+nh;
        });
        if (comfyNode) {
            const wf=(this._comfyWfList||[]).find(w=>w.name===comfyNode.comfyWorkflow);
            const fields=wf?._fields||[];
            const relY=worldPt.y-comfyNode.y;
            const idx=Math.round((relY-48)/34);
            if (idx>=0 && idx<fields.length) {
                // 创建虚拟 port 数据
                targetPort = {dataset:{node:comfyNode.id, port:'in', fieldId:fields[idx].id}};
            }
        }
    }

    if (targetPort && targetPort.dataset.node !== this._linkFrom.nodeId) {
        const targetPortType = targetPort.dataset.port;
        const fromId = this._linkFrom.portType === 'out' ? this._linkFrom.nodeId : targetPort.dataset.node;
        const toId = this._linkFrom.portType === 'out' ? targetPort.dataset.node : this._linkFrom.nodeId;
        const validDirection = this._linkFrom.portType !== targetPortType;
        const fieldId = targetPort.dataset.fieldId || '';
        if (validDirection && this._canConnect(fromId, toId, fieldId)) {
            const conn = { id: this._uid('c'), from: fromId, to: toId };
            if (fieldId) conn.fieldId = fieldId;
            this.connections.push(conn);
            this.selectedConnectionId = conn.id;
            this._renderAll();
            this._markDirty();
        }
    }

    this._linkFrom = null;
    this._tempPointer = null;
    this._renderLinks();
};

CanvasEngine.prototype.confirmDeleteConnectionFromMenu = function() {
    if (!this._contextConnectionId) return;
    const id = this._contextConnectionId;
    this._contextConnectionId = '';
    this.deleteConnection(id);
};

CanvasEngine.prototype._onMinimapClick = function(event) {
    const el = document.getElementById('minimap');
    if (!el || !this.nodes.length) return;
    const rect = el.getBoundingClientRect();
    const mx = event.clientX - rect.left, my = event.clientY - rect.top;
    const mapW = 180, mapH = 120;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    this.nodes.forEach(n => {
        if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
        if (n.x+(n.w||260) > maxX) maxX = n.x+(n.w||260); if (n.y+(n.h||120) > maxY) maxY = n.y+(n.h||120);
    });
    const pad = 40, w = maxX - minX + pad*2, h = maxY - minY + pad*2;
    const s = Math.min(mapW/w, mapH/h);
    const ox = (mapW - w*s)/2, oy = (mapH - h*s)/2;
    const board = this.board.getBoundingClientRect();
    this.view.x = -((mx - ox)/s + minX - pad) * this.view.scale + board.width/2;
    this.view.y = -((my - oy)/s + minY - pad) * this.view.scale + board.height/2;
    this._renderAll();
};

CanvasEngine.prototype._isBoardBackground = function(target) {
    return target === this.board || target === this.world || target === this.linksEl || target === this.nodesEl || target === this.selectionEl || target === this.handlesEl;
};

CanvasEngine.prototype._screenToWorld = function(screenX, screenY) {
    const rect = this.board.getBoundingClientRect();
    return {
        x: (screenX - rect.left - this.view.x) / this.view.scale,
        y: (screenY - rect.top - this.view.y) / this.view.scale,
    };
};

CanvasEngine.prototype._localRectToWorld = function(startLocal, endLocal) {
    const rect = {
        x: Math.min(startLocal.x, endLocal.x),
        y: Math.min(startLocal.y, endLocal.y),
        w: Math.abs(endLocal.x - startLocal.x),
        h: Math.abs(endLocal.y - startLocal.y),
    };
    return {
        x: (rect.x - this.view.x) / this.view.scale,
        y: (rect.y - this.view.y) / this.view.scale,
        w: rect.w / this.view.scale,
        h: rect.h / this.view.scale,
    };
};

CanvasEngine.prototype._onBoardDrop = function(event) {
    event.preventDefault();
    if (!event.dataTransfer) return;
    this._onAssetDragEnd();
    try {
        const raw = event.dataTransfer.getData('text/plain');
        if (!raw) return;
        const {url, name} = JSON.parse(raw);
        if (!url) return;

        const worldPt = this._screenToWorld(event.clientX, event.clientY);

        // 检查是否拖到了已有的图片节点上
        const hitImg = this._findImageNodeAt(worldPt);
        if (hitImg) {
            hitImg.url = url;
            hitImg.imageName = name || hitImg.imageName || '';
            hitImg.imageWidth = 0;
            hitImg.imageHeight = 0;
            this._renderAll();
            this._markDirty();
            this._loadImageSize(url).then(size => {
                if (hitImg.url === url && size.w) {
                    hitImg.imageWidth = size.w;
                    hitImg.imageHeight = size.h;
                    this._renderAll();
                }
            });
            return;
        }

        // 检查是否拖到了组中
        const hitGroup = this._findGroupAt(worldPt);
        if (hitGroup) {
            worldPt.x = Math.max(worldPt.x, hitGroup.x + 10);
            worldPt.y = Math.max(worldPt.y, hitGroup.y + 10);
        }

        // 创建新节点
        const node = this.createNode('image', worldPt);
        node.url = url;
        node.imageName = name || '';
        node.imageWidth = 0;
        node.imageHeight = 0;
        this._renderAll();
        this._markDirty();
        this._loadImageSize(url).then(size => {
            if (node.url === url && size.w) {
                node.imageWidth = size.w;
                node.imageHeight = size.h;
                this._renderAll();
            }
        });
    } catch(e) { /* ignore */ }
};

CanvasEngine.prototype._findImageNodeAt = function(point) {
    return this.nodes.find(n => {
        if (n.type !== 'image') return false;
        const w = n.w || 260, h = n.h || 120;
        return point.x >= n.x && point.x <= n.x + w && point.y >= n.y && point.y <= n.y + h;
    });
};

CanvasEngine.prototype._findGroupAt = function(point) {
    for (const g of this.groups) {
        const children = this.nodes.filter(n => g.childIds.includes(n.id));
        if (!children.length) continue;
        const pad = g.padding || 18;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        children.forEach(n => { const w = n.w||260, h = n.h||120; if(n.x<minX)minX=n.x; if(n.y<minY)minY=n.y; if(n.x+w>maxX)maxX=n.x+w; if(n.y+h>maxY)maxY=n.y+h; });
        if (point.x >= minX - pad && point.x <= maxX + pad && point.y >= minY - pad && point.y <= maxY + pad) {
            g.x = minX - pad; g.y = minY - pad;
            return g;
        }
    }
    return null;
};
