CanvasEngine.prototype._showLightbox = function(url, type) {
    // 移除已有 lightbox
    const old = document.querySelector('.canvas-lightbox');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.className = 'canvas-lightbox';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.92);display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';
    overlay.onclick = () => overlay.remove();

    // 查找尺寸信息
    let dimText = '';
    for (const n of this.nodes) {
        if (n.type !== 'output') continue;
        const arr = type === 'image' ? (n.images || []) : (n.videos || []);
        for (const item of arr) {
            const u = typeof item === 'string' ? item : (item.url || '');
            if (u === url && typeof item === 'object' && item._w && item._h) {
                dimText = `${item._w}×${item._h}`;
                break;
            }
        }
        if (dimText) break;
    }

    // 顶部按钮栏
    const topBar = document.createElement('div');
    topBar.style.cssText = 'position:fixed;top:16px;right:20px;z-index:10001;display:flex;align-items:center;gap:8px;';

    // 尺寸标签
    if (dimText) {
        const dimLabel = document.createElement('span');
        dimLabel.textContent = dimText;
        dimLabel.style.cssText = 'color:rgba(255,255,255,.7);font-size:12px;font-weight:600;pointer-events:none;';
        topBar.appendChild(dimLabel);
    }

    // 下载按钮（仅图片）
    if (type === 'image') {
        const dlBtn = document.createElement('a');
        dlBtn.href = url; dlBtn.download = url.split('/').pop() || 'image.png'; dlBtn.target = '_blank';
        dlBtn.innerHTML = _t('lightbox.download','⬇ 下载');
        dlBtn.style.cssText = 'height:36px;padding:0 14px;border-radius:8px;border:none;background:rgba(255,255,255,.12);color:#fff;font-size:12px;font-weight:800;cursor:pointer;display:flex;align-items:center;gap:6px;text-decoration:none;transition:background .15s;';
        dlBtn.onmouseenter = () => dlBtn.style.background = 'rgba(255,255,255,.25)';
        dlBtn.onmouseleave = () => dlBtn.style.background = 'rgba(255,255,255,.12)';
        dlBtn.onclick = (e) => e.stopPropagation();
        topBar.appendChild(dlBtn);
    }

    // 关闭按钮
    const closeBtn = document.createElement('button');
    closeBtn.textContent = '×';
    closeBtn.style.cssText = 'width:36px;height:36px;border-radius:8px;border:none;background:rgba(255,255,255,.12);color:#fff;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;';
    closeBtn.onmouseenter = () => closeBtn.style.background = 'rgba(255,255,255,.25)';
    closeBtn.onmouseleave = () => closeBtn.style.background = 'rgba(255,255,255,.12)';
    closeBtn.onclick = (e) => { e.stopPropagation(); overlay.remove(); };
    topBar.appendChild(closeBtn);
    overlay.appendChild(topBar);

    if (type === 'video') {
        const vid = document.createElement('video');
        vid.src = url;
        vid.controls = true;
        vid.autoplay = true;
        vid.style.cssText = 'max-width:90vw;max-height:90vh;border-radius:12px;cursor:default;';
        vid.onclick = (e) => e.stopPropagation();
        // 视频加载后补充尺寸
        if (!dimText) {
            vid.onloadedmetadata = () => {
                if (vid.videoWidth && vid.videoHeight) {
                    const dl = topBar.querySelector('span');
                    if (dl) dl.textContent = `${vid.videoWidth}×${vid.videoHeight}`;
                    else {
                        const dimLabel = document.createElement('span');
                        dimLabel.textContent = `${vid.videoWidth}×${vid.videoHeight}`;
                        dimLabel.style.cssText = 'color:rgba(255,255,255,.7);font-size:12px;font-weight:600;pointer-events:none;';
                        topBar.insertBefore(dimLabel, topBar.firstChild);
                    }
                }
            };
        }
        overlay.appendChild(vid);
    } else {
        const wrapper = document.createElement('div');
        wrapper.style.cssText = 'display:flex;align-items:center;justify-content:center;max-width:90vw;max-height:90vh;overflow:hidden;';
        const img = document.createElement('img');
        img.src = url;
        img.alt = url.split('/').pop() || 'image';
        img.style.cssText = 'max-width:94vw;max-height:94vh;object-fit:contain;border-radius:6px;cursor:grab;user-select:none;';
        img.onclick = (e) => e.stopPropagation();
        // 缩放 + 拖拽
        let scale = 1, posX = 0, posY = 0;
        let dragging = false, startX = 0, startY = 0;
        let zoomPct = null;
        let transitionTimer = 0;
        const noTransition = () => {
            img.style.transition = 'none';
            clearTimeout(transitionTimer);
        };
        const restoreTransition = () => {
            clearTimeout(transitionTimer);
            transitionTimer = setTimeout(() => { img.style.transition = ''; }, 150);
        };
        const clampAndApply = () => {
            // 边界约束：确保图片至少 25% 可见
            if (scale > 1) {
                var rect = img.getBoundingClientRect();
                var maxX = (rect.width * scale - rect.width) / 2;
                var maxY = (rect.height * scale - rect.height) / 2;
                posX = Math.max(-maxX, Math.min(maxX, posX));
                posY = Math.max(-maxY, Math.min(maxY, posY));
            }
            img.style.transform = `scale(${scale}) translate(${posX / scale}px, ${posY / scale}px)`;
            img.style.cursor = scale > 1 ? 'grab' : 'default';
            if (zoomPct) zoomPct.textContent = Math.round(scale * 100) + '%';
        };
        // 滚轮缩放（以鼠标位置为锚点）
        wrapper.addEventListener('wheel', (e) => {
            e.preventDefault(); e.stopPropagation();
            noTransition();
            var rect = img.getBoundingClientRect();
            var fx = rect.width ? (e.clientX - rect.left) / rect.width : 0.5;
            var fy = rect.height ? (e.clientY - rect.top) / rect.height : 0.5;
            var oldScale = scale;
            var delta = e.deltaY > 0 ? -0.15 : 0.15;
            scale = Math.max(0.3, Math.min(8, scale + delta));
            // 保持鼠标指向的图片区域不动
            if (oldScale !== scale) {
                var dw = rect.width * (scale / oldScale - 1);
                var dh = rect.height * (scale / oldScale - 1);
                posX -= (fx - 0.5) * dw;
                posY -= (fy - 0.5) * dh;
            }
            clampAndApply();
            restoreTransition();
        }, { passive: false });
        // 双击缩放
        img.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            noTransition();
            if (scale === 1) {
                // 以双击点为中心放大到 1.5x
                var rect = img.getBoundingClientRect();
                var fx = rect.width ? (e.clientX - rect.left) / rect.width : 0.5;
                var fy = rect.height ? (e.clientY - rect.top) / rect.height : 0.5;
                var dw = rect.width * (1.5 - 1);
                var dh = rect.height * (1.5 - 1);
                posX = -(fx - 0.5) * dw;
                posY = -(fy - 0.5) * dh;
                scale = 1.5;
            } else {
                scale = 1; posX = 0; posY = 0;
            }
            clampAndApply();
            restoreTransition();
        });
        // 拖拽平移（缩放 > 1 时）
        const onDragMove = (e) => {
            if (!dragging) return;
            noTransition();
            posX = e.clientX - startX; posY = e.clientY - startY;
            clampAndApply();
        };
        const onDragUp = () => {
            if (dragging) { dragging = false; restoreTransition(); }
        };
        img.addEventListener('mousedown', (e) => {
            if (scale <= 1) return;
            e.stopPropagation(); e.preventDefault();
            noTransition();
            dragging = true; startX = e.clientX - posX; startY = e.clientY - posY;
            img.style.cursor = 'grabbing';
        });
        window.addEventListener('mousemove', onDragMove);
        window.addEventListener('mouseup', onDragUp);
        // ESC 关闭
        const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); } };
        document.addEventListener('keydown', onKey);
        // 关闭时清理所有监听器
        const origRemove = overlay.remove.bind(overlay);
        overlay.remove = () => {
            window.removeEventListener('mousemove', onDragMove);
            window.removeEventListener('mouseup', onDragUp);
            document.removeEventListener('keydown', onKey);
            clearTimeout(transitionTimer);
            origRemove();
        };
        wrapper.appendChild(img);
        overlay.appendChild(wrapper);

        // 底部缩放控制栏
        const zoomBar = document.createElement('div');
        zoomBar.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:10001;display:flex;align-items:center;gap:2px;background:rgba(0,0,0,.65);border-radius:10px;padding:5px;backdrop-filter:blur(8px);';
        zoomBar.onclick = (e) => e.stopPropagation();
        const mkZoomBtn = (label, action) => {
            const b = document.createElement('button');
            b.textContent = label;
            b.style.cssText = 'width:34px;height:34px;border-radius:7px;border:none;background:transparent;color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;line-height:1;';
            b.onmouseenter = () => b.style.background = 'rgba(255,255,255,.18)';
            b.onmouseleave = () => b.style.background = 'transparent';
            b.onclick = action;
            return b;
        };
        zoomPct = document.createElement('span');
        zoomPct.textContent = '100%';
        zoomPct.style.cssText = 'color:rgba(255,255,255,.7);font-size:11px;font-weight:800;min-width:44px;text-align:center;font-family:ui-monospace,monospace;';
        zoomBar.appendChild(mkZoomBtn('−', () => { noTransition(); scale = Math.max(0.3, scale - 0.25); clampAndApply(); restoreTransition(); }));
        zoomBar.appendChild(zoomPct);
        zoomBar.appendChild(mkZoomBtn('+', () => { noTransition(); scale = Math.min(8, scale + 0.25); clampAndApply(); restoreTransition(); }));
        zoomBar.appendChild(mkZoomBtn('⟲', () => { noTransition(); scale = 1; posX = 0; posY = 0; clampAndApply(); restoreTransition(); }));
        overlay.appendChild(zoomBar);
    }
    document.body.appendChild(overlay);
};

