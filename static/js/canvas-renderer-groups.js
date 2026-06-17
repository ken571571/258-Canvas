CanvasEngine.prototype._renderGroups = function() {
    if (!this.groupsEl) return;
    this.groupsEl.innerHTML = '';

    this.groups.forEach(group => {
        const children = this.nodes.filter(node => group.childIds.includes(node.id));
        if (children.length === 0) return;

        const padding = group.padding || 18;

        // Compute bounding box from children
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        children.forEach(node => {
            const w = node.w || 260;
            const h = node.h || 120;
            if (node.x < minX) minX = node.x;
            if (node.y < minY) minY = node.y;
            if (node.x + w > maxX) maxX = node.x + w;
            if (node.y + h > maxY) maxY = node.y + h;
        });

        const x = minX - padding;
        const y = minY - padding;
        const w = maxX - minX + padding * 2;
        const h = maxY - minY + padding * 2;

        const div = document.createElement('div');
        div.className = 'group-container';
        div.style.left = `${x}px`;
        div.style.top = `${y}px`;
        div.style.width = `${w}px`;
        div.style.height = `${h}px`;
        div.setAttribute('data-group-id', group.id);
        div.innerHTML = `
            <div class="group-label-wrap">
                <input class="group-label-input" data-group-id="${group.id}" value="${this._esc(group.label || '')}" placeholder="输入组名" maxlength="40"
                    onblur="window._canvas._updateGroupLabel('${group.id}', this.value)"
                    onkeydown="if(event.key==='Enter')this.blur()"
                    onclick="event.stopPropagation()"
                    onmousedown="event.stopPropagation()">
                <button class="group-delete" title="删除组（保留节点）" onclick="event.stopPropagation();">&times;</button>
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
            this._dragNodes = {
                pointerStart,
                groupId: group.id,
                items: this.nodes
                    .filter(item => group.childIds.includes(item.id))
                    .map(item => ({ node: item, startX: item.x, startY: item.y })),
            };
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
                const startPadding = padding;

                const onMove = moveEvent => {
                    const dx = (moveEvent.clientX - startX) / this.view.scale;
                    const dy = (moveEvent.clientY - startY) / this.view.scale;
                    let delta = 0;
                    if (corner === 'se') delta = Math.max(dx, dy);
                    else if (corner === 'nw') delta = -Math.min(dx, dy);
                    else if (corner === 'ne') delta = Math.max(dx, -dy);
                    else if (corner === 'sw') delta = Math.max(-dx, dy);
                    group.padding = Math.max(4, startPadding + delta);
                    this._renderGroups();
                };

                const onUp = () => {
                    window.removeEventListener('mousemove', onMove);
                    window.removeEventListener('mouseup', onUp);
                    this._markDirty();
                };

                window.addEventListener('mousemove', onMove);
                window.addEventListener('mouseup', onUp);
            });
        });

        this.groupsEl.appendChild(div);
    });
};

