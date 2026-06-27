/**
 * CanvasStore — 画布数据层（单一数据源）
 *
 * 职责：
 * - 持有所有画布数据（nodes / connections / groups / viewport）
 * - O(1) 索引查找（Map）
 * - 脏标记系统（支持增量渲染）
 * - 订阅/通知机制（渲染器解耦）
 * - 序列化（供保存使用）
 *
 * 不可变红线：
 * - 不操作 DOM
 * - 不发起网络请求
 * - 不依赖 CanvasEngine
 */

var CanvasStore = (function() {
    'use strict';

    function CanvasStore() {
        /** @type {Array<Object>} */
        this.nodes = [];
        /** @type {Array<Object>} */
        this.connections = [];
        /** @type {Array<Object>} */
        this.groups = [];
        /** @type {{x:number, y:number, scale:number}} */
        this.viewport = { x: 0, y: 0, scale: 1 };

        // O(1) 索引
        /** @type {Map<string, Object>} */
        this._nodeById = new Map();
        /** @type {Map<string, Object>} */
        this._connById = new Map();
        /** @type {Map<string, Object>} */
        this._groupById = new Map();

        // 脏标记：记录哪些实体发生了变化
        /** @type {{nodes: Set<string>, connections: Set<string>, groups: Set<string>, all: boolean}} */
        this._dirty = {
            nodes: new Set(),
            connections: new Set(),
            groups: new Set(),
            all: true   // 首次强制全量渲染
        };

        // 订阅者列表
        /** @type {Set<Function>} */
        this._listeners = new Set();
    }

    // ——— 订阅机制 ———

    /**
     * 订阅数据变更事件。
     * @param {Function} fn - 回调函数，接收 event 对象
     * @returns {Function} 取消订阅函数
     */
    CanvasStore.prototype.subscribe = function(fn) {
        this._listeners.add(fn);
        var self = this;
        return function() { self._listeners.delete(fn); };
    };

    /** @private */
    CanvasStore.prototype._notify = function(event) {
        this._listeners.forEach(function(fn) {
            try { fn(event); } catch (e) { console.error('store listener error', e); }
        });
    };

    // ——— 批量加载 ———

    /**
     * 从服务器数据批量加载（load() 时使用）。
     * @param {{nodes, connections, groups, viewport}} canvasData
     */
    CanvasStore.prototype.loadFromServer = function(canvasData) {
        this.nodes = (canvasData.nodes || []).map(function(node) {
            return Object.assign({}, node, {
                runState: node.runState && node.runState !== 'idle' ? node.runState : 'idle',
                runMessage: node.runMessage || ''
            });
        });
        this.connections = (canvasData.connections || []).map(function(c) { return Object.assign({}, c); });
        this.groups = (canvasData.groups || []).map(function(g) {
            return Object.assign({}, g, { childIds: (g.childIds || []).slice() });
        });
        this.viewport = canvasData.viewport ? Object.assign({}, canvasData.viewport) : this.viewport;
        this._rebuildIndex();
        this._dirty.all = true;
        this._notify({ type: 'full-reload' });
    };

    /** @private */
    CanvasStore.prototype._rebuildIndex = function() {
        var self = this;
        this._nodeById = new Map();
        this.nodes.forEach(function(n) { self._nodeById.set(n.id, n); });
        this._connById = new Map();
        this.connections.forEach(function(c) { self._connById.set(c.id, c); });
        this._groupById = new Map();
        this.groups.forEach(function(g) { self._groupById.set(g.id, g); });
    };

    // ——— 查询（O(1)） ———

    CanvasStore.prototype.getNode = function(id) { return this._nodeById.get(id); };
    CanvasStore.prototype.getConnection = function(id) { return this._connById.get(id); };
    CanvasStore.prototype.getGroup = function(id) { return this._groupById.get(id); };

    // ——— 单节点更新 ———

    /**
     * 更新节点的指定属性（同步更新索引）。
     */
    CanvasStore.prototype.updateNode = function(id, patch) {
        var node = this._nodeById.get(id);
        if (!node) return;
        var keys = Object.keys(patch);
        for (var i = 0; i < keys.length; i++) {
            node[keys[i]] = patch[keys[i]];
        }
        this._dirty.nodes.add(id);
        this._notify({ type: 'node-updated', id: id, patch: patch });
    };

    // ——— 批量位置更新（拖拽结束时使用） ———

    /**
     * 批量更新节点位置。updates: [{id, x, y}]
     */
    CanvasStore.prototype.updateNodePositions = function(updates) {
        var dirtyIds = [];
        for (var i = 0; i < updates.length; i++) {
            var u = updates[i];
            var node = this._nodeById.get(u.id);
            if (node) {
                node.x = u.x;
                node.y = u.y;
                this._dirty.nodes.add(u.id);
                dirtyIds.push(u.id);
            }
        }
        if (dirtyIds.length) {
            this._notify({ type: 'positions-updated', ids: dirtyIds });
        }
    };

    // ——— 添加 ———

    CanvasStore.prototype.addNode = function(node) {
        this.nodes.push(node);
        this._nodeById.set(node.id, node);
        this._dirty.nodes.add(node.id);
        this._notify({ type: 'node-added', id: node.id });
    };

    CanvasStore.prototype.addConnection = function(conn) {
        this.connections.push(conn);
        this._connById.set(conn.id, conn);
        this._dirty.connections.add(conn.id);
        this._notify({ type: 'connection-added', id: conn.id });
    };

    CanvasStore.prototype.addGroup = function(group) {
        this.groups.push(group);
        this._groupById.set(group.id, group);
        this._dirty.groups.add(group.id);
        this._notify({ type: 'group-added', id: group.id });
    };

    CanvasStore.prototype.removeGroup = function(id) {
        this.groups = this.groups.filter(function(g) { return g.id !== id; });
        this._groupById.delete(id);
        this._dirty.all = true;
        this._notify({ type: 'group-removed', id: id });
    };

    /** 批量替换全部 groups（深拷贝），同步索引 */
    CanvasStore.prototype.syncGroups = function(groups) {
        var self = this;
        this.groups = groups.map(function(g) {
            return Object.assign({}, g, { childIds: (g.childIds || []).slice() });
        });
        this._groupById.clear();
        this.groups.forEach(function(g) { self._groupById.set(g.id, g); });
        this._dirty.all = true;
    };

    // ——— 删除 ———

    CanvasStore.prototype.removeNode = function(id) {
        this.nodes = this.nodes.filter(function(n) { return n.id !== id; });
        this.connections = this.connections.filter(function(c) { return c.from !== id && c.to !== id; });
        this.groups = this.groups.map(function(g) {
            return Object.assign({}, g, { childIds: g.childIds.filter(function(cid) { return cid !== id; }) });
        }).filter(function(g) { return g.childIds.length >= 2; });
        this._nodeById.delete(id);
        this._rebuildIndex();
        this._dirty.all = true;
        this._notify({ type: 'node-removed', id: id });
    };

    CanvasStore.prototype.removeConnection = function(id) {
        this.connections = this.connections.filter(function(c) { return c.id !== id; });
        this._connById.delete(id);
        // v2.5.40：连线删除影响全局布局（链接线移除、端口 handle 变化），标记全量重建
        // 原 _dirty.connections.add(id) 指向已删除 ID，增量渲染找不到 → DOM 残留
        this._dirty.all = true;
        this._notify({ type: 'connection-removed', id: id });
    };

    // ——— 选中管理 ———

    /** 获取选中节点 ID 的 Set（从外部传入，Store 不持有 selected） */
    CanvasStore.prototype.getSelectedNodes = function(selectedSet) {
        var self = this;
        var result = [];
        selectedSet.forEach(function(id) {
            var node = self._nodeById.get(id);
            if (node) result.push(node);
        });
        return result;
    };

    // ——— 序列化 ———

    CanvasStore.prototype.toSavePayload = function(clientId, baseUpdatedAt) {
        return {
            nodes: this.nodes,
            connections: this.connections,
            groups: this.groups,
            viewport: this.viewport,
            base_updated_at: baseUpdatedAt,
            client_id: clientId || ''
        };
    };

    // ——— 脏标记管理 ———

    CanvasStore.prototype.clearDirty = function() {
        this._dirty.nodes.clear();
        this._dirty.connections.clear();
        this._dirty.groups.clear();
        this._dirty.all = false;
    };

    CanvasStore.prototype.isDirty = function() {
        return this._dirty.all ||
               this._dirty.nodes.size > 0 ||
               this._dirty.connections.size > 0 ||
               this._dirty.groups.size > 0;
    };

    /** 检查特定节点是否脏（用于增量渲染判断） */
    CanvasStore.prototype.isNodeDirty = function(id) {
        return this._dirty.all || this._dirty.nodes.has(id);
    };

    /** 检查是否只有位置变化（无内容/结构变化，可走快速路径） */
    CanvasStore.prototype.isPositionOnly = function() {
        return !this._dirty.all &&
               this._dirty.nodes.size > 0 &&
               this._dirty.connections.size === 0 &&
               this._dirty.groups.size === 0;
    };

    return CanvasStore;
})();
