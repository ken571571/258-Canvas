CanvasEngine.prototype._initEvents = function() {
    // 点击画布区域自动聚焦（否则快捷键不生效）
    // 双击编辑节点描述（事件委托，不随 DOM 重建丢失）
    this._onNodesDblClick = event => {
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
    };
    this.nodesEl.addEventListener('dblclick', this._onNodesDblClick);

    // 小地图点击
    this._onMinimapClickWrapper = e => this._onMinimapClick(e);
    const minimapEl = document.getElementById('minimap');
    if (minimapEl) minimapEl.addEventListener('click', this._onMinimapClickWrapper);

    // 允许画布接收拖放
    this._onBoardDragOver = event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; };
    this.board.addEventListener('dragover', this._onBoardDragOver);
    this._onBoardDropHandler = event => this._onBoardDrop(event);
    this.board.addEventListener('drop', this._onBoardDropHandler);

    this._onBoardFocusClick = () => this.board.focus();
    this.board.addEventListener('mousedown', this._onBoardFocusClick);

    this._onLinksClick = event => {
        const hit = event.target.closest('[data-connection-id]');
        if (!hit) return;
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = hit.dataset.connectionId || '';
        this._hideConnectionMenu();
        this._renderAll();
    };
    this.linksEl.addEventListener('click', this._onLinksClick);

    this._onHandlesClick = event => {
        const handle = event.target.closest('[data-connection-action="delete"]');
        if (!handle) return;
        event.preventDefault();
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = handle.dataset.connectionId || '';
        this._hideConnectionMenu();
        this._renderAll();
    };
    this.handlesEl?.addEventListener('click', this._onHandlesClick);

    this._onHandlesContext = event => {
        const handle = event.target.closest('[data-connection-action="delete"]');
        if (!handle) return;
        event.preventDefault();
        event.stopPropagation();
        this.selected.clear();
        this.selectedConnectionId = handle.dataset.connectionId || '';
        this._showConnectionMenu(event.clientX, event.clientY, this.selectedConnectionId);
        this._renderAll();
    };
    this.handlesEl?.addEventListener('contextmenu', this._onHandlesContext);

    this._onBoardMouseDown = event => {
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
    };
    this.board.addEventListener('mousedown', this._onBoardMouseDown);

    this._onBoardWheel = event => {
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
    };
    this.board.addEventListener('wheel', this._onBoardWheel, { passive: false });

    this._onBoardContext = event => {
        // 允许右键节点或空白处弹出创建菜单
        const hitNode = event.target.closest('.node');
        if (!hitNode && !this._isBoardBackground(event.target)) return;
        event.preventDefault();
        this._hideConnectionMenu();
        this._menuPoint = this._screenToWorld(event.clientX, event.clientY);
        this._showCreateMenu(event.clientX, event.clientY);
    };
    this.board.addEventListener('contextmenu', this._onBoardContext);

    this._onDocClick = event => {
        if (event.target.closest('#create-menu') || event.target.closest('#connection-menu')) return;
        this._hideMenus();
    };
    document.addEventListener('click', this._onDocClick);

    // 按需绑定 mousemove/mouseup：仅在拖拽进行中才监听，大幅减少空闲期间的 CPU 消耗
    var self = this;
    this._onDragMove = function(event) {
        if (self._dragBoard) {
            self.view.x = event.clientX - self._dragBoard.x;
            self.view.y = event.clientY - self._dragBoard.y;
            self._renderTransform();
        }
        if (self._dragNodes) {
            var pointer = self._screenToWorld(event.clientX, event.clientY);
            var dx = pointer.x - self._dragNodes.pointerStart.x;
            var dy = pointer.y - self._dragNodes.pointerStart.y;
            self._dragNodes.items.forEach(function(item) {
                item.node.x = item.startX + dx;
                item.node.y = item.startY + dy;
            });
            // 拖拽中：仅更新 transform + 节点位置 + 连线 + 组边框，跳过 minimap 重建
            self._renderTransform();
            self._renderNodes();
            self._renderLinks();
            // 组边框实时跟随（直接 CSS，不重建 DOM）
            if (self.groups.length > 0 && self.groupsEl) {
                var draggedIds = {};
                self._dragNodes.items.forEach(function(item) { draggedIds[item.node.id] = true; });
                self.groups.forEach(function(g) {
                    if (!self._dragNodes.groupId && !g.childIds.some(function(cid) { return draggedIds[cid]; })) return;
                    var gel = self.groupsEl.querySelector('[data-group-id="' + g.id + '"]');
                    if (!gel) return;
                    var b = self._getGroupBounds(g);
                    if (b) { gel.style.left = b.x + 'px'; gel.style.top = b.y + 'px'; gel.style.width = b.w + 'px'; gel.style.height = b.h + 'px'; }
                });
            }
            self._renderTempLine();
        }
        if (self._marquee) {
            var rect = self.board.getBoundingClientRect();
            self._marquee.endLocal = {
                x: event.clientX - rect.left,
                y: event.clientY - rect.top,
            };
            self._renderMarquee();
        }
        if (self._linkFrom) {
            self._tempPointer = self._screenToWorld(event.clientX, event.clientY);
            self._renderTempLine();
        }
    };
    this._onDragUp = function(event) {
        var hadDragBoard = !!self._dragBoard;
        var hadDragNodes = !!self._dragNodes;
        var hadMarquee = !!self._marquee;
        var hadLinkFrom = !!self._linkFrom;

        if (self._dragBoard) {
            self._dragBoard = null;
            self.board.classList.remove('panning');
        }
        if (self._dragNodes) {
            var wasCtrlExtract = !!self._dragNodes.ctrlExtract;
            self._dragNodes = null;
            self._syncGroupMembership(wasCtrlExtract);
            self._markDirty();
        }
        if (self._marquee) {
            self._finishMarquee();
        }
        if (self._linkFrom) {
            self._finishConnectionDrag(event);
        }

        // 所有拖拽结束后移除监听器
        if (hadDragBoard || hadDragNodes || hadMarquee || hadLinkFrom) {
            window.removeEventListener('mousemove', self._onDragMove);
            window.removeEventListener('mouseup', self._onDragUp);
        }
    };
    this._ensureDragListeners = function() {
        window.removeEventListener('mousemove', self._onDragMove);
        window.removeEventListener('mouseup', self._onDragUp);
        window.addEventListener('mousemove', self._onDragMove);
        window.addEventListener('mouseup', self._onDragUp);
    };

    // Space 保持全局监听（输入框内不触发，避免打字时误触画布平移）
    this._onSpaceKeyDown = event => {
        if (event.code === 'Space' && !event.repeat) {
            var tag = String((event.target || document.activeElement)?.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea' || (event.target || document.activeElement)?.isContentEditable) return;
            this._spacePressed = true;
            this.board.classList.add('panning');
        }
    };
    this._onSpaceKeyUp = event => {
        if (event.code === 'Space') {
            this._spacePressed = false;
            this.board.classList.remove('panning');
        }
    };
    window.addEventListener('keydown', this._onSpaceKeyDown);
    window.addEventListener('keyup', this._onSpaceKeyUp);

    // 快捷键 — 参照 888 方案，在 window 上直接监听（不用 capture）
    this._onShortcutKeyDown = event => {
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
        // Ctrl+Y 或 Ctrl+Shift+Z: 重做
        if ((event.ctrlKey || event.metaKey) &&
            (String(event.key || '').toLowerCase() === 'y' ||
             (event.shiftKey && String(event.key || '').toLowerCase() === 'z'))) {
            event.preventDefault();
            this.redo();
            return;
        }
        // Ctrl+C: 复制选中节点
        if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key || '').toLowerCase() === 'c') {
            event.preventDefault();
            this._clipboard = this.nodes.filter(n => this.selected.has(n.id)).map(n => this._deepCloneNode(n));
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
    };
    window.addEventListener('keydown', this._onShortcutKeyDown);

};

CanvasEngine.prototype._startBoardPan = function(event) {
    this._dragBoard = {
        x: event.clientX - this.view.x,
        y: event.clientY - this.view.y,
    };
    this._ensureDragListeners();
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
    this._ensureDragListeners();
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
            var wf=(this._comfyWfList||[]).find(function(w){return w.name===comfyNode.comfyWorkflow;});
            var fields=wf?._fields||[];
            var relY=worldPt.y-comfyNode.y;
            var idx=Math.round((relY-48)/34);  // 48=端口起始偏移, 34=端口间距（与 renderer-nodes.js 保持同步）
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
            this.store.addConnection(conn);  // 同步 Store
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
            // 保留旧尺寸直到异步加载完成（避免中间态显示错误）
            // imageWidth/imageHeight 保持原值不变
            this.store.updateNode(hitImg.id, { url, imageName: hitImg.imageName });
            this._renderAll();
            this._markDirty();
            this._loadImageSize(url).then(size => {
                if (hitImg.url === url && size.w) {
                    this._syncImageNodeSize(hitImg, size.w, size.h);
                    this._renderAll();
                }
            });
            return;
        }

        // 检查是否拖到了组中
        const hit = this._findGroupAt(worldPt);
        if (hit) {
            worldPt.x = Math.max(worldPt.x, hit.bounds.x + 10);
            worldPt.y = Math.max(worldPt.y, hit.bounds.y + 10);
        }

        // 创建新节点（URL 直接传入，首次 render 已有 src）
        const node = this.createNode('image', worldPt, { url, imageName: name || '', imageWidth: 0, imageHeight: 0 });
        this._loadImageSize(url).then(size => {
            if (node.url === url && size.w) {
                this._syncImageNodeSize(node, size.w, size.h);
                this._renderAll();
            }
        });
    } catch(e) { /* ignore */ }
};

CanvasEngine.prototype._findImageNodeAt = function(point) {
    return this.nodes.find(n => {
        if (n.type !== 'image') return false;
        const w = n.w || 260, h = n.h || 100;
        return point.x >= n.x && point.x <= n.x + w && point.y >= n.y && point.y <= n.y + h;
    });
};

CanvasEngine.prototype._findGroupAt = function(point) {
    for (const g of this.groups) {
        const bounds = this._getGroupBounds(g);
        if (!bounds) continue;
        if (point.x >= bounds.x && point.x <= bounds.x + bounds.w &&
            point.y >= bounds.y && point.y <= bounds.y + bounds.h) {
            return { group: g, bounds: bounds };
        }
    }
    return null;
};

// ——— 销毁引擎，清理所有事件监听器和定时器 ———
CanvasEngine.prototype.destroy = function() {
    // 移除 DOM 元素级监听器（_initEvents 中注册的）
    if (this._onNodesDblClick) {
        this.nodesEl?.removeEventListener('dblclick', this._onNodesDblClick);
        this._onNodesDblClick = null;
    }
    if (this._onMinimapClickWrapper) {
        var mEl = document.getElementById('minimap');
        if (mEl) mEl.removeEventListener('click', this._onMinimapClickWrapper);
        this._onMinimapClickWrapper = null;
    }
    if (this._onBoardDragOver) {
        this.board?.removeEventListener('dragover', this._onBoardDragOver);
        this._onBoardDragOver = null;
    }
    if (this._onBoardDropHandler) {
        this.board?.removeEventListener('drop', this._onBoardDropHandler);
        this._onBoardDropHandler = null;
    }
    if (this._onBoardFocusClick) {
        this.board?.removeEventListener('mousedown', this._onBoardFocusClick);
        this._onBoardFocusClick = null;
    }
    if (this._onLinksClick) {
        this.linksEl?.removeEventListener('click', this._onLinksClick);
        this._onLinksClick = null;
    }
    if (this._onHandlesClick) {
        this.handlesEl?.removeEventListener('click', this._onHandlesClick);
        this._onHandlesClick = null;
    }
    if (this._onHandlesContext) {
        this.handlesEl?.removeEventListener('contextmenu', this._onHandlesContext);
        this._onHandlesContext = null;
    }
    if (this._onBoardMouseDown) {
        this.board?.removeEventListener('mousedown', this._onBoardMouseDown);
        this._onBoardMouseDown = null;
    }
    if (this._onBoardWheel) {
        this.board?.removeEventListener('wheel', this._onBoardWheel);
        this._onBoardWheel = null;
    }
    if (this._onBoardContext) {
        this.board?.removeEventListener('contextmenu', this._onBoardContext);
        this._onBoardContext = null;
    }
    // 移除 window 级键盘监听器
    if (this._onSpaceKeyDown) {
        window.removeEventListener('keydown', this._onSpaceKeyDown);
        this._onSpaceKeyDown = null;
    }
    if (this._onSpaceKeyUp) {
        window.removeEventListener('keyup', this._onSpaceKeyUp);
        this._onSpaceKeyUp = null;
    }
    if (this._onShortcutKeyDown) {
        window.removeEventListener('keydown', this._onShortcutKeyDown);
        this._onShortcutKeyDown = null;
    }
    // 移除 document 点击监听器
    if (this._onDocClick) {
        document.removeEventListener('click', this._onDocClick);
        this._onDocClick = null;
    }
    // 移除拖拽监听器（如果仍在监听中）
    if (this._onDragMove) {
        window.removeEventListener('mousemove', this._onDragMove);
        this._onDragMove = null;
    }
    if (this._onDragUp) {
        window.removeEventListener('mouseup', this._onDragUp);
        this._onDragUp = null;
    }
    this._ensureDragListeners = null;
    // 移除语言切换监听器
    if (this._onLangChanged) {
        window.removeEventListener('lang-changed', this._onLangChanged);
        this._onLangChanged = null;
    }
    // 清理定时器
    if (this._saveIndicatorTimer) { clearTimeout(this._saveIndicatorTimer); this._saveIndicatorTimer = null; }
    if (this._outputClickTimer) { clearTimeout(this._outputClickTimer); this._outputClickTimer = null; }
    if (this._assetClickTimer) { clearTimeout(this._assetClickTimer); this._assetClickTimer = null; }  // v2.5.50
    if (this._saveDebounceTimer) { clearTimeout(this._saveDebounceTimer); this._saveDebounceTimer = null; }
    // 清除全局引用
    if (window._canvas === this) { window._canvas = null; }
};
