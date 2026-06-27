CanvasEngine.prototype._renderAll = function() {
    this._renderTransform();
    this._renderNodes();
    this._renderGroups();
    this._renderLinks();
    this._renderMarquee();
    this._renderMinimap();
    // 全量渲染完成后清除脏标记，使后续增量渲染可以生效
    if (this.store) this.store.clearDirty();
};

// 延迟渲染：在下一帧执行，避免 select onchange 等事件处理器中同步销毁 DOM
CanvasEngine.prototype._renderAllDeferred = function() {
    if (this._rafRenderPending) return;
    this._rafRenderPending = true;
    var self = this;
    requestAnimationFrame(function() {
        self._rafRenderPending = false;
        self._renderAll();
    });
};


CanvasEngine.prototype._renderMinimap = function() {
    const mc = document.getElementById('minimap-canvas');
    const vp = document.getElementById('minimap-viewport');
    if (!mc || !vp) return;
    if (!this.nodes.length) { mc.style.display='none'; vp.style.display='none'; return; }
    if (!this.view.scale || this.view.scale <= 0) return;  // 防御：scale 无效时不渲染小地图
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

    // 每次读取 CSS 变量确保主题切换后正确（getComputedStyle 在现代浏览器中很快）
    const minimapBg = getComputedStyle(document.documentElement).getPropertyValue('--surface-2').trim() || '#eee';
    ctx.fillStyle = minimapBg;
    ctx.fillRect(0, 0, mapW, mapH);

    // 节点色块
    const colors = {image:'#3b82f6', prompt:'#8b5cf6', image_gen:'#f59e0b', video_gen:'#ef4444', agent:'#10b981', loop:'#ec4899', comfy:'#a855f7', output:'#6b7280'};
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
    if (!this.view.scale || this.view.scale <= 0) return { x: node.x, y: node.y };  // 防御：scale 无效时回退到节点坐标
    const el = this.nodesEl.querySelector(`[data-id="${node.id}"]`);
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
    // v2.5.52：改用 _t() 替代 _tt()，避免 _tt 映射表遗漏导致英文模式显示中文
    if (node.runState === 'running') return '<span class="node-state-badge is-running">' + _t('nodeState.running','运行中') + '</span>';
    if (node.runState === 'success') return '<span class="node-state-badge is-success">' + _t('nodeState.success','成功') + '</span>';
    if (node.runState === 'error') return '<span class="node-state-badge is-error">' + _t('nodeState.error','失败') + '</span>';
    if (node.runState === 'cancelled') return '<span class="node-state-badge is-cancelled">' + _t('nodeState.cancelled','已取消') + '</span>';
    return '';
};


CanvasEngine.prototype._renderNodeMeta = function(node) {
    if (!node.runMessage) return '';
    return `<div class="node-meta">${this._esc(node.runMessage)}</div>`;
};


CanvasEngine.prototype._setNodeRunState = function(node, state, message = '') {
    node.runState = state;
    node.runMessage = message;
    // 优先直接更新 DOM badge（避免 _renderAll 全量重建）
    var el = this.nodesEl && this.nodesEl.querySelector('[data-id="' + node.id + '"]');
    if (el) {
        // 更新 state class
        el.classList.remove('is-running', 'is-success', 'is-error', 'is-cancelled');
        if (state === 'running') el.classList.add('is-running');
        else if (state === 'success') el.classList.add('is-success');
        else if (state === 'error') el.classList.add('is-error');
        else if (state === 'cancelled') el.classList.add('is-cancelled');
        // 更新 badge HTML
        var badgeEl = el.querySelector('.node-state-badge');
        var newBadge = this._renderNodeStateBadge(node);
        if (badgeEl && newBadge) {
            badgeEl.outerHTML = newBadge;
        } else if (newBadge && !badgeEl) {
            var titleEl = el.querySelector('.node-head-title');
            if (titleEl) titleEl.insertAdjacentHTML('beforeend', newBadge);
        } else if (!newBadge && badgeEl) {
            badgeEl.remove();
        }
        // 更新 meta 消息
        var metaEl = el.querySelector('.node-meta');
        if (message && metaEl) {
            metaEl.textContent = message;
        } else if (message && !metaEl) {
            var bodyEl = el.querySelector('.node-body');
            if (bodyEl) bodyEl.insertAdjacentHTML('afterbegin', '<div class="node-meta">' + this._esc(message) + '</div>');
        } else if (!message && metaEl) {
            metaEl.remove();
        }
    } else {
        // 节点 DOM 尚未创建 → 全量渲染
        this._renderAll();
    }
};

