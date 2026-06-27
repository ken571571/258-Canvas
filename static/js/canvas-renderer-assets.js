CanvasEngine.prototype._toggleAssetPanel = function() {
    const panel = document.getElementById('asset-panel');
    const isOpen = panel.classList.contains('open');
    panel.classList.toggle('open', !isOpen);
    if (!isOpen) this._loadAssets('input');
};

CanvasEngine.prototype._loadAssets = async function(dir) {
    const expectedText = dir === 'input' ? _t('assets.input','输入') : _t('assets.output','输出');
    document.querySelectorAll('.asset-tab').forEach(t => t.classList.toggle('active', t.textContent.trim() === expectedText));
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

CanvasEngine.prototype._renderAssetGrid = function() {
    const grid = document.getElementById('asset-grid');
    if (!grid) return;
    const files = this._assetFiles || [];
    grid.innerHTML = files.map(f => {
        const isImg = /\.(png|jpg|jpeg|webp|gif)$/i.test(f.name);
        const isVideo = /\.(mp4|webm|mov)$/i.test(f.name);
        var thumbHtml;
        if (isImg) {
            thumbHtml = `<img src="${this._esc(f.url)}" alt="${this._esc(f.name)}" onerror="this.style.display='none'">`;
        } else if (isVideo) {
            thumbHtml = `<div style="width:100%;height:100%;position:relative;">
                <video src="${this._esc(f.url)}" preload="metadata" muted disablePictureInPicture onerror="this.style.display='none'" style="width:100%;height:100%;object-fit:cover;display:block;"></video>
                <div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;pointer-events:none;">
                    <span style="font-size:22px;color:#fff;text-shadow:0 2px 6px rgba(0,0,0,.7);opacity:.9;">▶</span>
                </div>
            </div>`;
        } else {
            thumbHtml = '📁';
        }
        return `<div class="asset-thumb" draggable="true"
            data-asset-url="${this._esc(f.url)}"
            data-asset-name="${this._esc(f.name)}"
            ondragstart="window._canvas._onAssetDragStart(event)"
            ondragend="window._canvas._onAssetDragEnd(event)"
            onclick="window._canvas._onAssetClick(event)">
            ${thumbHtml}
            <span class="asset-name">${this._esc(f.name)}</span>
            <button class="asset-del" onclick="event.stopPropagation();event.preventDefault();window._canvas._deleteAsset('${this._escJs(f.url)}')" title="${_t('node.delete','删除')}">×</button>
        </div>`;
    }).join('') || '<div style="grid-column:1/-1;text-align:center;padding:30px;color:var(--muted);font-size:12px;">' + _t('assets.empty','暂无媒体文件') + '</div>';
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
    // v2.5.50：DOM API 代替 innerHTML，消除 XSS 攻击面
    var ghostImg = document.createElement('img');
    ghostImg.src = url;
    ghostImg.alt = name;
    ghost.appendChild(ghostImg);
    document.body.appendChild(ghost);
    event.dataTransfer.setDragImage(ghost, 40, 40);
    this._dragGhost = ghost;
};

CanvasEngine.prototype._deleteAsset = async function(url) {
    if (!confirm(_t('assets.deleteConfirm','确定删除此文件？'))) return;
    var deletedItem = (this._assetFiles || []).find(function(f) { return f.url === url; });
    try {
        await apiFetch(`/api/assets/delete?url=${encodeURIComponent(url)}`, { method: 'DELETE' });
        // 从缓存中移除
        this._assetFiles = (this._assetFiles || []).filter(function(f) { return f.url !== url; });
        this._renderAssetGrid();
    } catch(e) {
        console.warn('删除资产失败:', url, e);
        // 恢复缓存，避免 UI 与实际状态不一致
        if (deletedItem && this._assetFiles && !this._assetFiles.some(function(f) { return f.url === url; })) {
            this._assetFiles.push(deletedItem);
            this._renderAssetGrid();
        }
    }
};

CanvasEngine.prototype._onAssetDragEnd = function() {
    if (this._dragGhost) { this._dragGhost.remove(); this._dragGhost = null; }
};

CanvasEngine.prototype._onAssetClick = function(event) {
    const thumb = event.target.closest('.asset-thumb');
    if (!thumb) return;
    const url = thumb.dataset.assetUrl;
    const name = thumb.dataset.assetName;
    const isVideo = /\.(mp4|webm|mov)$/i.test(name);

    // 视频只响应双击灯箱
    if (isVideo) {
        if (event.detail === 2) this._showLightbox(url, 'video');
        return;
    }

    if (event.detail === 2) {
        // 双击：取消待定的创建 + 打开灯箱
        clearTimeout(this._assetClickTimer);
        if (this._assetClickPending) {
            // 节点已创建 → 删掉
            this._deleteNode(this._assetClickPending);
            this._assetClickPending = null;
        }
        this._assetClickTimer = null;
        this._showLightbox(url, 'image');
        return;
    }

    // 单击：立即创建节点，设 300ms 窗口 — 若期间双击则回滚
    var self = this;
    // 清理上次单击的待定节点（快速连点不同资产时）
    clearTimeout(self._assetClickTimer);
    if (self._assetClickPending) {
        self._deleteNode(self._assetClickPending);
        self._assetClickPending = null;
    }
    var center = self._screenToWorld(window.innerWidth / 2, window.innerHeight / 2);
    var node = self.createNode('image', center, { url, imageName: name || '', imageWidth: 0, imageHeight: 0 });
    self._assetClickPending = node.id;
    self._assetClickTimer = setTimeout(function() {
        // 300ms 后无双击 → 确认保留
        self._assetClickTimer = null;
        self._assetClickPending = null;
        self._loadImageSize(url).then(function(size) {
            if (node.url === url && size.w) {
                self._syncImageNodeSize(node, size.w, size.h);
                self._renderAll();
            }
        });
    }, 300);
};
