CanvasEngine.prototype._toggleAssetPanel = function() {
    const panel = document.getElementById('asset-panel');
    const isOpen = panel.classList.contains('open');
    panel.classList.toggle('open', !isOpen);
    if (!isOpen) this._loadAssets('input');
};

CanvasEngine.prototype._loadAssets = async function(dir) {
    document.querySelectorAll('.asset-tab').forEach(t => t.classList.toggle('active', t.textContent.trim() === (dir === 'input' ? '输入' : '输出')));
    try {
        const resp = await apiFetch(`/api/assets/list?dir=${dir}`);
        const data = await resp.json();
        this._assetFiles = data.files || [];
        this._renderAssetGrid();
    } catch(e) { console.error('load assets failed', e); }
    this._assetDir = dir;
};

CanvasEngine.prototype._refreshAssetLibrary = function() {
    if (this._assetDir === 'output') this._loadAssets('output');
};

CanvasEngine.prototype._filterAssets = function() {
    this._renderAssetGrid();
};

CanvasEngine.prototype._renderAssetGrid = function() {
    const grid = document.getElementById('asset-grid');
    if (!grid) return;
    const q = (document.getElementById('asset-search')?.value || '').toLowerCase();
    const files = (this._assetFiles || []).filter(f => !q || f.name.toLowerCase().includes(q));
    grid.innerHTML = files.map(f => {
        const isImg = /\.(png|jpg|jpeg|webp|gif)$/i.test(f.name);
        return `<div class="asset-thumb" draggable="true"
            data-asset-url="${this._esc(f.url)}"
            data-asset-name="${this._esc(f.name)}"
            ondragstart="window._canvas._onAssetDragStart(event)"
            ondragend="window._canvas._onAssetDragEnd(event)"
            onclick="window._canvas._onAssetClick(event)">
            ${isImg ? `<img src="${this._esc(f.url)}" alt="${this._esc(f.name)}" onerror="this.parentElement.innerHTML='📁'">` : '📁'}
            <span class="asset-name">${this._esc(f.name)}</span>
            <button class="asset-del" onclick="event.stopPropagation();event.preventDefault();window._canvas._deleteAsset('${this._esc(f.url)}')" title="删除">×</button>
        </div>`;
    }).join('') || '<div style="grid-column:1/-1;text-align:center;padding:30px;color:var(--muted);font-size:12px;">暂无媒体文件</div>';
};

CanvasEngine.prototype._onAssetDragStart = function(event) {
    const thumb = event.target.closest('.asset-thumb');
    if (!thumb) return;
    const url = thumb.dataset.assetUrl;
    const name = thumb.dataset.assetName;
    event.dataTransfer.setData('text/plain', JSON.stringify({url, name}));
    event.dataTransfer.effectAllowed = 'copy';
    // 创建拖拽跟随图
    const ghost = document.createElement('div');
    ghost.className = 'asset-drag-ghost';
    ghost.style.display = 'block';
    ghost.innerHTML = `<img src="${url}" alt="${name}">`;
    document.body.appendChild(ghost);
    event.dataTransfer.setDragImage(ghost, 40, 40);
    this._dragGhost = ghost;
};

CanvasEngine.prototype._deleteAsset = async function(url) {
    if (!confirm('确定删除此文件？')) return;
    try {
        await apiFetch(`/api/assets/delete?url=${encodeURIComponent(url)}`, { method: 'DELETE' });
        // 从缓存中移除
        this._assetFiles = (this._assetFiles || []).filter(f => f.url !== url);
        this._renderAssetGrid();
    } catch(e) { /* ignore */ }
};

CanvasEngine.prototype._onAssetDragEnd = function() {
    if (this._dragGhost) { this._dragGhost.remove(); this._dragGhost = null; }
};

CanvasEngine.prototype._onAssetClick = function(event) {
    const thumb = event.target.closest('.asset-thumb');
    if (!thumb) return;
    const url = thumb.dataset.assetUrl;
    const name = thumb.dataset.assetName;
    if (event.detail === 1) {
        // 单击：在视口中心创建图片节点
        const center = this._screenToWorld(window.innerWidth / 2, window.innerHeight / 2);
        const node = this.createNode('image', center);
        node.url = url;
        node.imageName = name || '';
        node.imageWidth = 0;
        node.imageHeight = 0;
        this._renderAll();
        this._markDirty();
        // 异步加载尺寸
        this._loadImageSize(url).then(size => {
            if (node.url === url && size.w) {
                node.imageWidth = size.w;
                node.imageHeight = size.h;
                this._renderAll();
            }
        });
    }
};
