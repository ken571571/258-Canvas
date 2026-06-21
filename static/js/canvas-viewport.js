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
    this.view.scale = Math.min(scaleX, scaleY, 2);
    this.view.x = -minX * this.view.scale + padding;
    this.view.y = -minY * this.view.scale + padding;
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
