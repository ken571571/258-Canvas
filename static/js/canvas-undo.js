// 画布撤销/重做系统 — 扩展 CanvasEngine.prototype
// 依赖: canvas-core.js（需先加载）

(function() {
  const proto = (typeof CanvasEngine !== 'undefined' && CanvasEngine.prototype) || null;
  if (!proto) return;

  // 深拷贝节点：防止浅拷贝导致 images/videos/_queue 等数组被共享引用破坏撤销栈
  proto._deepCloneNode = function(n) {
    return {
      ...n,
      images: [...(n.images || [])],
      videos: [...(n.videos || [])],
      _queue: [...(n._queue || [])],
      _removedUrls: [...(n._removedUrls || [])],
      knowledgeBases: [...(n.knowledgeBases || [])],
      skills: [...(n.skills || [])],
    };
  };

  // 保存状态快照用于撤销
  proto._snapshot = function() {
    this._undoStack = this._undoStack.slice(0, this._undoIndex + 1);
    this._undoStack.push({
      nodes: this.nodes.map(n => this._deepCloneNode(n)),
      connections: this.connections.map(c => ({...c})),
      groups: this.groups.map(g => ({...g, childIds: [...(g.childIds || [])]})),
    });
    if (this._undoStack.length > 50) this._undoStack.shift();
    this._undoIndex = this._undoStack.length - 1;
  };

  // 撤销操作
  proto.undo = async function() {
    if (this._undoIndex < 0) return;
    // _markDirty 在状态变更后拍快照，栈顶快照与当前状态相同
    // 跳过栈顶，直接恢复上一个有效快照，避免双击撤销
    if (this._undoIndex > 0 && this._undoIndex === this._undoStack.length - 1) {
      this._undoIndex--;
    }
    const snap = this._undoStack[this._undoIndex];
    if (!snap) return;
    this.nodes = snap.nodes.map(n => this._deepCloneNode(n));
    this.connections = snap.connections.map(c => ({...c}));
    this.groups = snap.groups.map(g => ({...g, childIds: [...(g.childIds || [])]}));
    this._undoIndex--;
    // 同步 Store，确保 save() 从 Store 读取正确的数据
    if (this.store) this.store.loadFromServer({ nodes: this.nodes, connections: this.connections, groups: this.groups, viewport: this.view });
    this.selected.clear();
    this.selectedConnectionId = '';
    this._renderAll();
    await this.save();
  };

  // 重做操作（撤销的逆操作）
  proto.redo = async function() {
    if (this._undoIndex >= this._undoStack.length - 2) return;
    this._undoIndex += 2;
    const snap = this._undoStack[this._undoIndex];
    if (!snap) return;
    this.nodes = snap.nodes.map(n => this._deepCloneNode(n));
    this.connections = snap.connections.map(c => ({...c}));
    this.groups = snap.groups.map(g => ({...g, childIds: [...(g.childIds || [])]}));
    this._undoIndex--;
    // 同步 Store，确保 save() 从 Store 读取正确的数据
    if (this.store) this.store.loadFromServer({ nodes: this.nodes, connections: this.connections, groups: this.groups, viewport: this.view });
    this.selected.clear();
    this.selectedConnectionId = '';
    this._renderAll();
    await this.save();
  };

  // 仅触发延迟保存（不拍快照）— 用于高频属性修改（如文本输入）
  proto._scheduleSave = function() {
    this._setSaveIndicator(_t('canvas.pendingSave','待保存'));
    clearTimeout(this._saveDebounceTimer);
    this._saveDebounceTimer = setTimeout(() => this.save(), 800);
  };

  // 标记脏数据 → 拍快照 + 延迟保存（用于结构性变更：创建/删除/移动/连线）
  proto._markDirty = function() {
    this._snapshot();
    this._scheduleSave();
  };
})();
