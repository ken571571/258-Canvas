CanvasEngine.prototype._renderGroups = function() {
    if (!this.groupsEl) return;
    // ——— 快速路径：仅位置/尺寸更新（子节点拖拽后分组包围盒改变） ———
    var store = this.store;
    if (store && !store._dirty.all && store._dirty.groups.size === 0 && !this._dragNodes) {
        // 快速路径仅在非拖拽状态生效（拖拽时 engine 节点坐标更新而 Store 未同步，会导致分组 bounds 计算错误）
        var positionOnly = true;
        var self = this;
        store._dirty.nodes.forEach(function(id) {
            if (!positionOnly) return;
            var node = store.getNode(id);
            if (!node) return;
            self.groups.forEach(function(g) {
                if (g.childIds.indexOf(id) >= 0) {
                    var b = self._getGroupBounds(g);
                    if (b) {
                        var gel = self.groupsEl.querySelector('[data-group-id="' + g.id + '"]');
                        if (gel) {
                            gel.style.left = b.x + 'px';
                            gel.style.top = b.y + 'px';
                            gel.style.width = b.w + 'px';
                            gel.style.height = b.h + 'px';
                        } else {
                            positionOnly = false;
                        }
                    }
                }
            });
        });
        if (positionOnly) return;  // ← 跳过全量重建！
    }

    this.groupsEl.innerHTML = '';

    // 预建 nodeId→node 索引，O(N) 替代 O(N²) 的 filter+includes
    var nodeMap = {};
    this.nodes.forEach(function(node) { nodeMap[node.id] = node; });

    this.groups.forEach(group => {
        var children = [];
        group.childIds.forEach(cid => {
            if (nodeMap[cid]) children.push(nodeMap[cid]);
        });
        if (children.length === 0) return;

        // Compute bounding box from children（复用共享方法）
        const bounds = this._getGroupBounds(group);
        if (!bounds) return;

        const div = document.createElement('div');
        div.className = 'group-container';
        div.style.left = `${bounds.x}px`;
        div.style.top = `${bounds.y}px`;
        div.style.width = `${bounds.w}px`;
        div.style.height = `${bounds.h}px`;
        div.setAttribute('data-group-id', group.id);
        div.innerHTML = `
            <div class="group-label-wrap">
                <input class="group-label-input" data-group-id="${group.id}" value="${this._esc(group.label || '')}" placeholder="${_t('group.placeholder','输入组名')}" maxlength="40"
                    onblur="window._canvas._updateGroupLabel('${group.id}', this.value)"
                    onkeydown="if(event.key==='Enter')this.blur()"
                    onclick="event.stopPropagation()"
                    onmousedown="event.stopPropagation()">
                <button class="group-delete" title="${_t('group.deleteTitle','删除组（保留节点）')}" onclick="event.stopPropagation();">&times;</button>
            </div>
            <div class="group-resize nw" data-corner="nw"></div>
            <div class="group-resize ne" data-corner="ne"></div>
            <div class="group-resize sw" data-corner="sw"></div>
            <div class="group-resize se" data-corner="se"></div>
        `;

        // 删除按钮
        div.querySelector('.group-delete')?.addEventListener('click', event => {
            event.stopPropagation();
            const childIds = [...group.childIds];
            this.groups = this.groups.filter(g => g.id !== group.id);
            this.store.removeGroup(group.id);  // 同步 Store
            this.selected = new Set(childIds);
            this._renderAll();
            this._markDirty();
        });

        // Click on group background → select all children and drag
        div.addEventListener('mousedown', event => {
            if (event.target.closest('.node') || event.target.closest('.group-resize') || event.target.closest('.group-delete')) return;
            event.preventDefault();
            event.stopPropagation();
            this.selected.clear();
            this.selectedConnectionId = '';
            group.childIds.forEach(cid => this.selected.add(cid));
            const pointerStart = this._screenToWorld(event.clientX, event.clientY);
            const dragItems = [];
            group.childIds.forEach(cid => {
                const item = nodeMap[cid];
                if (item) dragItems.push({ node: item, startX: item.x, startY: item.y });
            });
            this._dragNodes = { pointerStart, groupId: group.id, items: dragItems };
            this._ensureDragListeners();
            this._renderAll();
        });

        // Resize handles
        div.querySelectorAll('.group-resize').forEach(handle => {
            handle.addEventListener('mousedown', event => {
                event.preventDefault();
                event.stopPropagation();
                const corner = handle.dataset.corner;
                const startX = event.clientX;
                const startY = event.clientY;
                const startPadding = group.padding || 18;
                // 捕获初始包围盒（resize 过程中子节点可能移动，用原始值更稳定）
                const bMinX = bounds.minX, bMinY = bounds.minY, bMaxX = bounds.maxX, bMaxY = bounds.maxY;

                const onMove = moveEvent => {
                    const dx = (moveEvent.clientX - startX) / this.view.scale;
                    const dy = (moveEvent.clientY - startY) / this.view.scale;
                    let delta = 0;
                    if (corner === 'se') delta = Math.max(dx, dy);
                    else if (corner === 'nw') delta = -Math.min(dx, dy);
                    else if (corner === 'ne') delta = Math.max(dx, -dy);
                    else if (corner === 'sw') delta = Math.max(-dx, dy);
                    group.padding = Math.max(4, startPadding + delta);
                    // 直接更新当前分组的 CSS，避免每像素重建全部 DOM
                    var newX = bMinX - group.padding;
                    var newY = bMinY - group.padding;
                    var newW = bMaxX - bMinX + group.padding * 2;
                    var newH = bMaxY - bMinY + group.padding * 2;
                    div.style.left = newX + 'px';
                    div.style.top = newY + 'px';
                    div.style.width = newW + 'px';
                    div.style.height = newH + 'px';
                };

                const onUp = () => {
                    window.removeEventListener('mousemove', onMove);
                    window.removeEventListener('mouseup', onUp);
                    // 同步 Store：resize 只修改了 group.padding
                    var storeGroup = this.store.getGroup(group.id);
                    if (storeGroup) storeGroup.padding = group.padding;
                    this._markDirty();
                };

                window.addEventListener('mousemove', onMove);
                window.addEventListener('mouseup', onUp);
            });
        });

        this.groupsEl.appendChild(div);
    });
};

