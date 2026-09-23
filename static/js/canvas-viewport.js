// 画布视口操作（缩放/适应） — 扩展 CanvasEngine.prototype
// 依赖: canvas-core.js（需先加载）

(function() {
  const proto = (typeof CanvasEngine !== 'undefined' && CanvasEngine.prototype) || null;
  if (!proto) return;

  // 放大
  proto.zoomIn = function() { this._applyZoom(1.2); };

  // 缩小
  proto.zoomOut = function() { this._applyZoom(0.8); };

  // 适应所有节点
  proto.zoomFit = function() {
    if (!this.nodes.length) return;
    const padding = 80;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    this.nodes.forEach(n => {
      if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
      if (n.x + (n.w||260) > maxX) maxX = n.x + (n.w||260);
      if (n.y + (n.h||120) > maxY) maxY = n.y + (n.h||120);
    });
    const rect = this.board.getBoundingClientRect();
    const rangeX = maxX - minX + padding * 2;
    const rangeY = maxY - minY + padding * 2;
    if (rangeX <= 0 || rangeY <= 0) return;
    const scaleX = (rect.width - padding * 2) / rangeX;
    const scaleY = (rect.height - padding * 2) / rangeY;
    this.view.scale = Math.max(0.1, Math.min(scaleX, scaleY, 2));  // v2.5.55：加 0.1 下限，防止 board 极窄时 scale≤0 导致除零/翻转
    this.view.x = -minX * this.view.scale + padding;
    this.view.y = -minY * this.view.scale + padding;
    this._renderTransform();
  };

  // 打开画布时：把视口聚焦/缩放到"内容包围盒"并居中，
  // 避免遗留在空白原点。空画布不跳，保持默认视口。
  proto._focusContent = function() {
    if (!this.nodes || !this.nodes.length) return;
    const padding = 80;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    this.nodes.forEach(n => {
      if (n.x < minX) minX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.x + (n.w||260) > maxX) maxX = n.x + (n.w||260);
      if (n.y + (n.h||120) > maxY) maxY = n.y + (n.h||120);
    });
    const rangeX = maxX - minX + padding * 2;
    const rangeY = maxY - minY + padding * 2;
    if (rangeX <= 0 || rangeY <= 0) return;
    const rect = this.board.getBoundingClientRect();
    const vw = rect.width || window.innerWidth || 800;
    const vh = rect.height || window.innerHeight || 600;
    if (!vw || !vh) return;
    const scaleX = (vw - padding * 2) / rangeX;
    const scaleY = (vh - padding * 2) / rangeY;
    // 打开时最多放大到 1.25（内容很小时不过度放大），需要缩小则按需缩放
    this.view.scale = Math.max(0.1, Math.min(scaleX, scaleY, 1.25));
    // 将内容包围盒中心对准视口中心
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    this.view.x = vw / 2 - cx * this.view.scale;
    this.view.y = vh / 2 - cy * this.view.scale;
    this._renderTransform();
  };

  // 应用缩放增量（以画布中心为锚点）
  proto._applyZoom = function(delta) {
    const rect = this.board.getBoundingClientRect();
    const mx = rect.width / 2, my = rect.height / 2;
    const newScale = Math.max(0.1, Math.min(5, this.view.scale * delta));
    this.view.x -= (mx - this.view.x) * (newScale / this.view.scale - 1);
    this.view.y -= (my - this.view.y) * (newScale / this.view.scale - 1);
    this.view.scale = newScale;
    this._renderTransform();
  };
})();
