CanvasEngine.prototype._renderLinks = function() {
    // ——— 快速路径：仅位置更新（节点拖拽后） ———
    var store = this.store;
    var hasDragNodes = !!this._dragNodes;
    if (store && !store._dirty.all &&
        (store._dirty.nodes.size > 0 || hasDragNodes) &&
        store._dirty.connections.size === 0) {
        // 只更新现有路径的 d 属性和 handle 位置，不重建 DOM
        var self = this;
        var paths = this.linksEl.querySelectorAll('.connection-line');
        var hitMap = {};
        this.linksEl.querySelectorAll('.connection-hit').forEach(function(h) { hitMap[h.dataset.connectionId] = h; });
        var handleMap = {};
        if (this.handlesEl) {
            this.handlesEl.querySelectorAll('.connection-handle').forEach(function(h) { handleMap[h.dataset.connectionId] = h; });
        }
        var connMap = {};
        this.connections.forEach(function(c) { connMap[c.id] = c; });
        // 拖拽时需用 engine 端坐标（Store 在拖拽期间未同步）
        var engineMap = null;
        if (hasDragNodes) {
            engineMap = {};
            this.nodes.forEach(function(n) { engineMap[n.id] = n; });
        }
        // 更新 path d 属性
        paths.forEach(function(path) {
            var cid = path.dataset.connectionId;
            var conn = connMap[cid];
            if (!conn) return;
            var from = engineMap ? engineMap[conn.from] : store.getNode(conn.from);
            var to = engineMap ? engineMap[conn.to] : store.getNode(conn.to);
            if (!from || !to) return;
            var start = self._getPortPoint(from, 'out');
            var end = self._getPortPoint(to, 'in', conn.fieldId || '');
            var curve = self._curveMeta(start, end);
            path.setAttribute('d', curve.path);
            // 同步更新 hit 区域（O(1) 映射查找，替代每连线 querySelector）
            var hit = hitMap[cid];
            if (hit) hit.setAttribute('d', curve.path);
            // 更新 handle 位置（O(1) 映射查找）
            var handle = handleMap[cid];
            if (handle) {
                handle.style.left = curve.midpoint.x + 'px';
                handle.style.top = curve.midpoint.y + 'px';
            }
        });
        this._renderTempLine();
        return;  // ← 跳过全量重建！
    }

    // ——— 完整路径：连接数变化时重建全部 ———
    // 仅重建静态连线，临时拖拽线由 _renderTempLine() 单独处理
    var html = '';
    var handlesHtml = '';

    this.connections.forEach(function(connection) {
        var from = this.nodes.find(function(node) { return node.id === connection.from; });
        var to = this.nodes.find(function(node) { return node.id === connection.to; });
        if (!from || !to) return;
        var start = this._getPortPoint(from, 'out');
        var end = this._getPortPoint(to, 'in', connection.fieldId||'');
        var curve = this._curveMeta(start, end);
        var selected = connection.id === this.selectedConnectionId ? ' is-selected' : '';
        var running = to.runState === 'running' ? ' is-running-target' : '';
        html += '<g class="connection-group' + selected + '" data-connection-id="' + connection.id + '">' +
            '<path class="connection-hit" data-connection-id="' + connection.id + '" d="' + curve.path + '" />' +
            '<path class="connection-line' + selected + running + '" data-connection-id="' + connection.id + '" d="' + curve.path + '" />' +
            '</g>';
        handlesHtml += '<button class="connection-handle' + selected + '" data-connection-id="' + connection.id + '" data-connection-action="delete" style="left:' + curve.midpoint.x + 'px;top:' + curve.midpoint.y + 'px" title="' + _t('contextMenu.deleteConnection','连线操作') + '"><span class="connection-handle-dot"></span></button>';
    }.bind(this));

    this.linksEl.innerHTML = html;
    if (this.handlesEl) this.handlesEl.innerHTML = handlesHtml;

    // 临时拖拽线单独渲染
    this._renderTempLine();
};

// 仅更新临时连线（连接拖拽期间每像素调用，避免重建全部SVG）
CanvasEngine.prototype._renderTempLine = function() {
    var tempEl = this.linksEl.querySelector('.temp-line');
    if (this._linkFrom && this._tempPointer) {
        var from = this.nodes.find(function(node) { return node.id === this._linkFrom.nodeId; }.bind(this));
        if (from) {
            var anchor = this._getPortPoint(from, this._linkFrom.portType);
            var start = this._linkFrom.portType === 'out' ? anchor : this._tempPointer;
            var end = this._linkFrom.portType === 'out' ? this._tempPointer : anchor;
            var curve = this._curveMeta(start, end);
            if (!tempEl) {
                tempEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                tempEl.setAttribute('class', 'temp-line');
                this.linksEl.appendChild(tempEl);
            }
            tempEl.setAttribute('d', curve.path);
            return;
        }
    }
    // 无拖拽 → 清除临时线
    if (tempEl) tempEl.remove();
};

