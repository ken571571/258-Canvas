CanvasEngine.prototype._renderAll = function() {
    this._renderTransform();
    this._renderNodes();
    this._renderGroups();
    this._renderLinks();
    this._renderMarquee();
    this._renderMinimap();
};


CanvasEngine.prototype._renderMinimap = function() {
    const mc = document.getElementById('minimap-canvas');
    const vp = document.getElementById('minimap-viewport');
    if (!mc || !vp) return;
    if (!this.nodes.length) { mc.style.display='none'; vp.style.display='none'; return; }
    mc.style.display=''; vp.style.display='';

    const mapW = 180, mapH = 120;
    mc.width = mapW * 2; mc.height = mapH * 2;
    mc.style.width = mapW + 'px'; mc.style.height = mapH + 'px';
    const ctx = mc.getContext('2d');
    ctx.scale(2, 2);

    // 计算所有节点的包围盒
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    this.nodes.forEach(n => {
        if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
        const r = n.x + (n.w||260); if (r > maxX) maxX = r;
        const b = n.y + (n.h||120); if (b > maxY) maxY = b;
    });
    const pad = 40, w = maxX - minX + pad*2, h = maxY - minY + pad*2;
    const sx = mapW / w, sy = mapH / h, s = Math.min(sx, sy);
    const ox = (mapW - w * s) / 2, oy = (mapH - h * s) / 2;

    // 背景
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface-2').trim() || '#eee';
    ctx.fillRect(0, 0, mapW, mapH);

    // 节点色块
    const colors = {image:'#3b82f6', prompt:'#8b5cf6', image_gen:'#f59e0b', video_gen:'#ef4444', generator:'#f59e0b', agent:'#10b981', loop:'#ec4899', output:'#6b7280'};
    this.nodes.forEach(n => {
        ctx.fillStyle = colors[n.type] || '#999';
        ctx.fillRect(ox + (n.x - minX + pad) * s, oy + (n.y - minY + pad) * s, (n.w||260) * s, (n.h||120) * s);
    });

    // 视口框
    const board = this.board.getBoundingClientRect();
    const vw = board.width / this.view.scale, vh = board.height / this.view.scale;
    const vx = -this.view.x / this.view.scale, vy = -this.view.y / this.view.scale;
    vp.style.left = (ox + (vx - minX + pad) * s) + 'px';
    vp.style.top = (oy + (vy - minY + pad) * s) + 'px';
    vp.style.width = (vw * s) + 'px';
    vp.style.height = (vh * s) + 'px';
};


CanvasEngine.prototype._renderTransform = function() {
    this.world.style.transform = `translate(${this.view.x}px, ${this.view.y}px) scale(${this.view.scale})`;
    const lbl = document.getElementById('zoom-label');
    if (lbl) lbl.textContent = Math.round(this.view.scale * 100) + '%';
};


CanvasEngine.prototype._renderMarquee = function() {
    if (!this.selectionEl) return;
    if (!this._marquee) {
        this.selectionEl.style.display = 'none';
        return;
    }
    const x = Math.min(this._marquee.startLocal.x, this._marquee.endLocal.x);
    const y = Math.min(this._marquee.startLocal.y, this._marquee.endLocal.y);
    const w = Math.abs(this._marquee.endLocal.x - this._marquee.startLocal.x);
    const h = Math.abs(this._marquee.endLocal.y - this._marquee.startLocal.y);
    this.selectionEl.style.display = 'block';
    this.selectionEl.style.left = `${x}px`;
    this.selectionEl.style.top = `${y}px`;
    this.selectionEl.style.width = `${w}px`;
    this.selectionEl.style.height = `${h}px`;
};


CanvasEngine.prototype._getPortPoint = function(node, portType, fieldId = '') {
    const el = document.querySelector(`[data-id="${node.id}"]`);
    let portEl = null;
    if (fieldId) {
        // ComfyUI 多端口：找特定 fieldId 的端口
        portEl = el?.querySelector(`.port-in[data-field-id="${fieldId}"]`);
    }
    if (!portEl) {
        portEl = el?.querySelector(portType === 'out' ? '.port-out' : '.port-in');
    }
    if (portEl) {
        const nodeRect = el.getBoundingClientRect();
        const portRect = portEl.getBoundingClientRect();
        const boardRect = this.board.getBoundingClientRect();
        return {
            x: (portRect.left + portRect.width / 2 - boardRect.left - this.view.x) / this.view.scale,
            y: (portRect.top + portRect.height / 2 - boardRect.top - this.view.y) / this.view.scale,
        };
    }
    // fallback
    return {
        x: portType === 'out' ? node.x + (node.w || 260) + 9 : node.x - 9,
        y: node.y + (node.h || 120) / 2,
    };
};


CanvasEngine.prototype._canConnect = function(fromId, toId, fieldId = '') {
    if (!fromId || !toId || fromId === toId) return false;
    // 不同 fieldId 视为不同连接（ComfyUI 多端口）
    return !this.connections.some(connection => connection.from === fromId && connection.to === toId && (connection.fieldId || '') === (fieldId || ''));
};


CanvasEngine.prototype._curveMeta = function(start, end) {
    const dx = end.x - start.x;
    const bend = Math.max(72, Math.abs(dx) * 0.42 + 36);
    const cp1 = { x: start.x + bend, y: start.y };
    const cp2 = { x: end.x - bend, y: end.y };
    const path = `M ${start.x} ${start.y} C ${cp1.x} ${cp1.y}, ${cp2.x} ${cp2.y}, ${end.x} ${end.y}`;
    const midpoint = {
        x: (start.x + 3 * cp1.x + 3 * cp2.x + end.x) / 8,
        y: (start.y + 3 * cp1.y + 3 * cp2.y + end.y) / 8,
    };
    return { path, midpoint };
};


CanvasEngine.prototype._renderNodeStateBadge = function(node) {
    if (node.runState === 'running') return '<span class="node-state-badge is-running">运行中</span>';
    if (node.runState === 'success') return '<span class="node-state-badge is-success">成功</span>';
    if (node.runState === 'error') return '<span class="node-state-badge is-error">失败</span>';
    return '';
};


CanvasEngine.prototype._renderNodeMeta = function(node) {
    if (!node.runMessage) return '';
    return `<div class="node-meta">${this._esc(node.runMessage)}</div>`;
};


CanvasEngine.prototype._setNodeRunState = function(node, state, message = '') {
    node.runState = state;
    node.runMessage = message;
    this._renderAll();
};

