CanvasEngine.prototype._renderNodes = function() {
    // ——— 快速路径：仅位置更新（拖拽后） ———
    // 当只有节点坐标变化、无内容/数量/连线变化时，跳过 DOM 重建，只更新 CSS
    var store = this.store;
    if (store && !store._dirty.all &&
        store._dirty.nodes.size > 0 &&
        store._dirty.connections.size === 0 &&
        store._dirty.groups.size === 0) {
        var positionOnly = true;
        var self = this;
        store._dirty.nodes.forEach(function(id) {
            var el = self.nodesEl.querySelector('[data-id="' + id + '"]');
            if (el) {
                var node = store.getNode(id);
                if (node) {
                    el.style.left = node.x + 'px';
                    el.style.top = node.y + 'px';
                }
            } else {
                positionOnly = false;  // 新节点，需要全量渲染
            }
        });
        if (positionOnly) {
            store.clearDirty();
            // 仍需更新连线（连线端点跟随节点移动）
            this._renderLinks();
            return;  // ← 跳过全量重建！
        }
    }

    // ——— 完整路径：内容变化时走原有逻辑 ———
    this.nodesEl.innerHTML = '';

    this.nodes.forEach(node => {
        const el = document.createElement('div');
        el.className = [
            'node',
            this.selected.has(node.id) ? 'selected' : '',
            node.runState === 'running' ? 'is-running' : '',
            node.runState === 'success' ? 'is-success' : '',
            node.runState === 'error' ? 'is-error' : '',
        ].filter(Boolean).join(' ');
        el.style.left = `${node.x}px`;
        el.style.top = `${node.y}px`;
        el.style.width = `${node.w || 260}px`;
        el.dataset.id = node.id;

        const hasInput = ['image_gen', 'video_gen', 'agent', 'output', 'loop'].includes(node.type);
        const isComfy = node.type === 'comfy';
        const hasOutput = ['image', 'prompt', 'image_gen', 'video_gen', 'agent', 'loop', 'output', 'comfy'].includes(node.type);
        const badge = this._renderNodeStateBadge(node);

        el.innerHTML = `<div class="node-head"><div class="node-head-title"><span>${this._esc(node.label || node.type)}</span>${node.type==='image'?`<span class="node-desc" data-node-desc="${node.id}" title="${_t('node.dblClickDesc','双击添加描述')}">${this._esc(node.desc||_t('node.dblClickDesc','双击添加描述'))}</span>`:''}${badge}</div><button class="node-delete" title="${_t('node.delete','删除')}" data-del="${node.id}">&times;</button></div><div class="node-body" data-body="${node.id}">${this._renderNodeBody(node)}</div>${hasInput && !isComfy?`<div class="port port-in" data-port="in" data-node="${node.id}"></div>`:''}${hasOutput?`<div class="port port-out" data-port="out" data-node="${node.id}"></div>`:''}<div class="resize-handle" data-resize="${node.id}"></div>`;

        el.addEventListener('mousedown', event => {
            if (event.target.closest('.port')||event.target.closest('button')||event.target.closest('textarea')||event.target.closest('input')||event.target.closest('select')||event.target.closest('.resize-handle')||event.target.closest('[data-upload]')||event.target.closest('[data-node-desc]')||event.target.closest('[draggable]')||event.target.closest('img')||event.target.closest('video')||event.target.closest('.node-preview')) return;
            event.preventDefault();
            if ((event.ctrlKey||event.metaKey)&&!event.shiftKey){if(!this.selected.has(node.id)){this.selected.add(node.id);}}
            else if(event.shiftKey){if(this.selected.has(node.id)){this.selected.delete(node.id);this._renderAll();return;}this.selected.add(node.id);}
            else{this.selected.clear();this.selected.add(node.id);}
            this.selectedConnectionId='';
            const ids=Array.from(this.selected);
            const ctrlExtract=event.ctrlKey||event.metaKey;
            if(ctrlExtract){ids.forEach(did=>{this.groups.forEach(g=>{g.childIds=g.childIds.filter(cid=>cid!==did)});});this.groups=this.groups.filter(g=>g.childIds.length>=2);}
            const pointerStart=this._screenToWorld(event.clientX,event.clientY);
            this._dragNodes={pointerStart,items:this.nodes.filter(item=>ids.includes(item.id)).map(item=>({node:item,startX:item.x,startY:item.y}))};
            this._ensureDragListeners();
            this._renderAll();
        });

        el.querySelector('[data-del]')?.addEventListener('click',event=>{event.stopPropagation();this._deleteNode(node.id);});

        el.querySelectorAll('.port').forEach(port=>{port.addEventListener('mousedown',event=>{event.stopPropagation();event.preventDefault();this.selectedConnectionId='';this._linkFrom={nodeId:node.id,portType:port.dataset.port};this._tempPointer=this._screenToWorld(event.clientX,event.clientY);this._ensureDragListeners();this._renderLinks();});});

        el.querySelector('.resize-handle')?.addEventListener('mousedown',event=>{event.stopPropagation();event.preventDefault();this._resizeNode={node,sx:event.clientX,sy:event.clientY,startWidth:node.w||260,startHeight:node.h||120};const onMove=moveEvent=>{node.w=Math.max(180,this._resizeNode.startWidth+(moveEvent.clientX-this._resizeNode.sx)/this.view.scale);el.style.width=`${node.w}px`;if(node.type!=='image_gen'&&node.type!=='video_gen'){node.h=Math.max(80,this._resizeNode.startHeight+(moveEvent.clientY-this._resizeNode.sy)/this.view.scale);el.style.height=`${node.h}px`;const ta=el.querySelector('textarea');if(ta){const headH=el.querySelector('.node-head')?.offsetHeight||44;const taH=Math.max(40,node.h-headH-36);ta.style.height=`${taH}px`;node._taH=taH;}}};const onUp=()=>{window.removeEventListener('mousemove',onMove);window.removeEventListener('mouseup',onUp);this._resizeNode=null;this._renderAll();this._markDirty();};window.addEventListener('mousemove',onMove);window.addEventListener('mouseup',onUp);});

        this.nodesEl.appendChild(el);
        // 收集元素引用，循环结束后批量读取 offsetHeight（避免逐个读取触发多次同步布局）
        // 列队 X 按钮
        el.querySelectorAll('.loop-thumb-x').forEach(btn=>{btn.addEventListener('mousedown',e=>{e.stopPropagation();e.stopImmediatePropagation();e.preventDefault();const nid=btn.dataset.loopRm;const idx=parseInt(btn.dataset.loopRmIdx);if(nid&&!isNaN(idx)){this._removeLoopItem(nid,idx);}});});
        // ComfyUI 多端口动态添加
        if(node.type==='comfy'){const wf=(this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);(wf?._fields||[]).forEach((f,i)=>{const p=document.createElement('div');p.className='port port-in comfy-port';p.dataset.port='in';p.dataset.node=node.id;p.dataset.fieldId=f.id;p.style.cssText='top:'+(48+i*34)+'px;left:-9px;width:18px;height:18px;pointer-events:auto;';p.title=f.name||f.input;p.addEventListener('mousedown',e=>{e.stopPropagation();e.preventDefault();this.selectedConnectionId='';this._linkFrom={nodeId:node.id,portType:'in'};this._tempPointer=this._screenToWorld(e.clientX,e.clientY);this._ensureDragListeners();this._renderLinks();});el.appendChild(p);});}
    });

    // ——— 批量读取 offsetHeight（避免在循环内逐个读取触发多次同步布局） ———
    // 使用 Store 的 Map 索引 O(1) 查找，替代 nodes.find() 的 O(n²)
    var allEls = this.nodesEl.children;
    var nodeMap = this.store._nodeById;
    for (var i = 0; i < allEls.length; i++) {
        var el2 = allEls[i];
        var nid = el2.dataset.id;
        var nd = nodeMap.get(nid);
        if (nd) {
            nd.h = Math.max(el2.offsetHeight || 100, nd.h || 100);
        }
    }
};


// 尺寸标签映射（移入 prototype 避免全局作用域污染）
CanvasEngine.prototype._szMap = {
    '1:1 方形':'size.square','16:9 横版':'size.wide','9:16 竖版':'size.tall',
    '3:2 横版':'size.32w','2:3 竖版':'size.23t','4:3 横版':'size.43w','3:4 竖版':'size.34t',
    '21:9 宽屏':'size.ultrawide'
};
CanvasEngine.prototype._szL = function(cn) { return _t(this._szMap[cn]||'', cn); };
CanvasEngine.prototype._fi = function() { return _t('size.followInput','📎 跟随输入图'); };
CanvasEngine.prototype._au = function() { return _t('size.auto','📎 自动'); };
CanvasEngine.prototype._cu = function() { return _t('size.custom','自定义最长边 →'); };
CanvasEngine.prototype._cw = function() { return _t('size.customWH','自定义 →'); };
CanvasEngine.prototype._wd = function() { return _t('size.width','宽'); };
CanvasEngine.prototype._ht = function() { return _t('size.height','高'); };
CanvasEngine.prototype._me = function() { return _t('size.maxEdge','最长边 px'); };

CanvasEngine.prototype._renderNodeBody = function(node) {
    var meta = this._renderNodeMeta(node);
    var renderers = {
        "image": "_renderNodeBody_image",
        "prompt": "_renderNodeBody_prompt",
        "image_gen": "_renderNodeBody_image_gen",
        "video_gen": "_renderNodeBody_video_gen",
        "agent": "_renderNodeBody_agent",
        "output": "_renderNodeBody_output",
        "loop": "_renderNodeBody_loop",
        "comfy": "_renderNodeBody_comfy"
    };
    var method = renderers[node.type];
    if (method && typeof this[method] === "function") {
        return this[method](node, meta);
    }
    return '<div class="node-meta">' + _t('node.unknownType','未知节点类型') + '</div>';
};

// —— 按节点类型拆分的渲染函数 ——

CanvasEngine.prototype._renderNodeBody_image = function(node, meta) {
    if (node.url) {
                return `
                    <img src="${this._esc(node.url)}" style="max-width:100%;border-radius:12px;display:block" alt="${this._esc(node.label)}" onerror="this.style.display='none'">
                    ${node.imageName ? `<div class="node-meta">${this._esc(node.imageName)}${(node.imageWidth && node.imageHeight) ? ` (${node.imageWidth}×${node.imageHeight})` : ''}</div>` : ''}
                    <div class="node-actions" style="margin-top:6px;">
                        <label class="tool-btn" style="flex:1;cursor:pointer;text-align:center;padding:5px;font-size:11px;" data-upload="${node.id}">
                            ${_t('node.replace','替换')}<input type="file" accept="image/*" style="display:none" onchange="window._canvas._handleImageUpload('${node.id}', this)">
                        </label>
                        <button class="tool-btn" style="flex:1;font-size:11px;padding:5px;" onclick="event.stopPropagation();window._canvas._removeImage('${node.id}')">${_t('node.delete','删除')}</button>
                    </div>
                `;
            }
            return `
                <label style="display:block;text-align:center;padding:20px;color:var(--muted);cursor:pointer" data-upload="${node.id}">
                    ${_t('node.clickUpload','点击上传图片')}<br><span style="font-size:10px;">${_t('node.dragFromAsset','或从右侧资产库拖入')}</span>
                    <input type="file" accept="image/*" style="display:none" onchange="window._canvas._handleImageUpload('${node.id}', this)">
                </label>
            `;
};

CanvasEngine.prototype._renderNodeBody_prompt = function(node, meta) {
    return `
                <textarea class="node-input" placeholder="${_t('node.inputPrompt','输入提示词...')}" oninput="window._canvas._updateNodeProp('${node.id}', 'text', this.value)" style="${node._taH ? 'height:'+node._taH+'px;' : ''}">${this._esc(node.text || '')}</textarea>
                ${meta}
            `;
};

CanvasEngine.prototype._renderGenBody = function(node, gap, h, mod) {
    var inputs = this._collectInputs(node.id);
    var hasRefImg = inputs.images.length > 0;
    var sizes = [['1024x1024','1:1 方形'],['1792x1024','16:9 横版'],['1024x1792','9:16 竖版'],['1536x1024','3:2 横版'],['1024x1536','2:3 竖版'],['1280x896','4:3 横版'],['896x1280','3:4 竖版'],['768x1344','9:16 竖版'],['1344x768','16:9 横版']];
    var selSize = node.size || '1024x1024';
    if (!sizes.some(function(s) { return s[0] === selSize; })) sizes.unshift([selSize, '']);
    var selOpts = 'height:' + h + ';padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';

    // provider + model selects
    var html = '<div style="display:flex;gap:' + gap + ';margin-bottom:' + gap + ';min-width:0;">' +
        '<select onchange="window._canvas._updateNodeProp(\'' + node.id + '\',\'provider_id\',this.value);window._canvas._updateNodeProp(\'' + node.id + '\',\'model\',\'\');window._canvas._renderAllDeferred()" style="flex:1;min-width:0;' + selOpts + '">' +
            this._renderProviderOpts(node.provider_id || '', mod) +
        '</select>' +
        '<select onchange="window._canvas._updateNodeProp(\'' + node.id + '\',\'model\',this.value);window._canvas._renderAllDeferred()" style="flex:1.5;min-width:0;' + selOpts + '">' +
            this._renderModelOpts(node.provider_id || '', node.model || '', mod) +
        '</select>' +
    '</div>';

    // size selector
    if (hasRefImg) {
        // has reference image: show follow-input + upscale options
        html += '<div style="display:flex;gap:' + gap + ';margin-bottom:' + gap + ';">' +
            '<select onchange="window._canvas._updateNodeProp(\'' + node.id + '\',\'size\',this.value);window._canvas._renderAllDeferred()" style="flex:1;height:' + h + ';padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">' +
                '<option value="" ' + (!node.size?'selected':'') + '>' + this._fi() + '</option>' +
                '<option value="x2" ' + (node.size==='x2'?'selected':'') + '>' + _t('size.x2','x2 放大') + '</option>' +
                '<option value="x3" ' + (node.size==='x3'?'selected':'') + '>' + _t('size.x3','x3 放大') + '</option>' +
                '<option value="x4" ' + (node.size==='x4'?'selected':'') + '>' + _t('size.x4','x4 放大') + '</option>' +
                '<option value="x5" ' + (node.size==='x5'?'selected':'') + '>' + _t('size.x5','x5 放大') + '</option>' +
                '<option value="custom" ' + (node.size==='custom'||(node.size||'').startsWith('custom:')?'selected':'') + '>' + this._cu() + '</option>' +
            '</select>' +
            (node.size==='custom' || (node.size||'').startsWith('custom:') ? '<input type="number" value="' + (node._customEdge||((node.size||'').startsWith('custom:')?node.size.split(':')[1]:2048)) + '" min="512" max="8192" step="64" placeholder="' + this._me() + '" onkeydown="if(event.key===\'Enter\'){this.blur()}" onchange="window._canvas._updateNodeProp(\'' + node.id + '\',\'_customEdge\',parseInt(this.value)||2048);window._canvas._updateNodeProp(\'' + node.id + '\',\'size\',\'custom:\'+this.value)" style="flex:1;height:' + h + ';padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);outline:none;width:90px;">' : '') +
        '</div>';
    } else {
        // no reference image: show preset sizes + custom WH option
        html += '<select onchange="window._canvas._setGenSize(\'' + node.id + '\',this.value)" style="width:100%;height:' + h + ';padding:0 6px;margin-bottom:' + (node._customWH?'4px':gap) + ';border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">' +
            sizes.map((s) => '<option value="' + s[0] + '" ' + (!node._customWH && s[0]===selSize?'selected':'') + '>' + s[0] + (s[1]?' · ' + this._szL(s[1]):'') + '</option>').join('') +
            '<option value="custom_wh" ' + (node._customWH?'selected':'') + '>✏️ ' + this._cw() + '</option>' +
        '</select>' +
        (node._customWH ?
            '<div style="display:flex;gap:' + gap + ';margin-bottom:' + gap + ';align-items:center;">' +
                '<span style="font-size:10px;color:var(--muted);flex-shrink:0;">' + this._wd() + '</span>' +
                '<input type="number" value="' + (node._customW || 1024) + '" min="64" max="8192" step="64" placeholder="' + this._wd() + '" oninput="var w=parseInt(this.value)||1024;var h=parseInt(this.nextElementSibling.nextElementSibling&&this.nextElementSibling.nextElementSibling.value)||1024;window._canvas._updateNodeProp(\'' + node.id + '\',\'_customW\',w);window._canvas._updateNodeProp(\'' + node.id + '\',\'size\',w+\'x\'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">' +
                '<span style="font-size:10px;color:var(--muted);flex-shrink:0;">' + this._ht() + '</span>' +
                '<input type="number" value="' + (node._customH || 1024) + '" min="64" max="8192" step="64" placeholder="' + this._ht() + '" oninput="var w=parseInt(this.previousElementSibling.previousElementSibling&&this.previousElementSibling.previousElementSibling.value)||1024;var h=parseInt(this.value)||1024;window._canvas._updateNodeProp(\'' + node.id + '\',\'_customH\',h);window._canvas._updateNodeProp(\'' + node.id + '\',\'size\',w+\'x\'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">' +
            '</div>'
        : '');
    }

    return html;
};

CanvasEngine.prototype._renderNodeBody_image_gen = function(node, meta) {
    {
        return this._renderGenBody(node, '4px', '28px', 'image') +
            (meta || '<div class="node-meta" style="margin-bottom:2px;">' + _t('pipeline.imgGenHint','连接提示词或图片后生成结果') + '</div>') +
            '<div class="node-actions" style="margin-top:0;">' +
                '<button class="tool-btn" style="font-size:11px;padding:4px 8px;" onclick="window._canvas._runPipeline(\'' + node.id + '\')">🖼 ' + _t('nodeType.imageGen','图片生成') + '</button>' +
            '</div>';
    }
};

CanvasEngine.prototype._renderNodeBody_video_gen = function(node, meta) {
    {
            const vidInputs = this._collectInputs(node.id);
            const hasVidRef = vidInputs.images && vidInputs.images.length > 0;
            const curModel = node.model || '';
            const durations = this._getVideoDurations(curModel);
            const selDur = node.duration || 5;
            const resolutions = this._getVideoResolutions(curModel);
            const defaultRes = hasVidRef ? 'auto' : (resolutions[0]?.v || '720p');
            const selRes = node.resolution || defaultRes;
            var autoLabel = hasVidRef ? this._fi() : this._au();
            const selOpts = 'height:28px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            return `
                <div style="display:flex;gap:4px;margin-bottom:4px;min-width:0;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','provider_id',this.value);window._canvas._updateNodeProp('${node.id}','model','');window._canvas._renderAllDeferred()" style="flex:1;min-width:0;${selOpts}">
                        ${this._renderProviderOpts(node.provider_id || '', 'video')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','model',this.value);window._canvas._renderAllDeferred()" style="flex:1.5;min-width:0;${selOpts}">
                        ${this._renderModelOpts(node.provider_id || '', node.model || '', 'video')}
                    </select>
                </div>
                <div style="display:flex;gap:4px;margin-bottom:4px;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','duration',parseInt(this.value))" style="flex:1;height:28px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        ${durations.map(d => `<option value="${d}" ${d===selDur?'selected':''}>⏱ ${d}s</option>`).join('')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','resolution',this.value)" style="flex:1.5;height:28px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        <option value="auto" ${selRes==='auto'?'selected':''}>${autoLabel}</option>
                        ${resolutions.map(r => `<option value="${r.v}" ${r.v===selRes?'selected':''}>${_tt(r.l)}</option>`).join('')}
                    </select>
                </div>
                ${(() => {
                    return `<label style="display:flex;align-items:center;gap:3px;cursor:pointer;font-size:10px;color:var(--muted);margin-bottom:4px;">
                        <input type="checkbox" ${node.generate_audio!==false?'checked':''} onchange="window._canvas._updateNodeProp('${node.id}','generate_audio',this.checked)" style="width:13px;height:13px;accent-color:var(--accent);">${_t('pipeline.audioLabel','🔊 有声')}</label>`;
                })()}
                ${meta || '<div class="node-meta" style="margin-bottom:2px;">' + _t('pipeline.vidGenHint','连接提示词或图片后生成视频') + '</div>'}
                <div class="node-actions" style="margin-top:0;">
                    <button class="tool-btn" style="font-size:11px;padding:4px 8px;" onclick="window._canvas._runPipeline('${node.id}')">🎬 ${_t('nodeType.videoGen','视频生成')}</button>
                </div>
            `;
        }
};

CanvasEngine.prototype._renderNodeBody_agent = function(node, meta) {
    return `
                <select onchange="window._canvas._updateNodeProp('${node.id}','agentId',this.value)" style="width:100%;height:32px;margin-bottom:8px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                    <option value="">${_t('pipeline.selectAgent','选择智能体...')}</option>
                    ${(this._agentList||[]).map(a => `<option value="${a.id}" ${a.id===node.agentId?'selected':''}>${this._esc(a.name||a.id)}</option>`).join('')}
                </select>
                <textarea class="node-input" placeholder="${_t('pipeline.agentPlaceholder','输入任务要求...')}" oninput="window._canvas._updateNodeProp('${node.id}', 'userInput', this.value)" style="${node._taH ? 'height:'+node._taH+'px;' : ''}">${this._esc(node.userInput || '')}</textarea>
                ${meta || `<div class="node-meta">${_t('pipeline.defaultTask','选择已有的智能体并输入任务要求。')}</div>`}
                ${node.lastResult ? `<div class="node-preview" style="max-height:192px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;">${this._esc(node.lastResult)}</div>` : ''}
                <div class="node-actions">
                    <button class="tool-btn" onclick="window._canvas._runAgent('${node.id}')">${_t('common.run','运行')}</button>
                </div>
            `;
};

CanvasEngine.prototype._renderNodeBody_output = function(node, meta) {
    {
            const renderItem = (item, i, type) => {
                const url = typeof item === 'string' ? item : (item.url || '');
                if (!url) return '';
                const isImg = /\.(png|jpg|jpeg|webp|gif)$/i.test(url) || type === 'image';
                const w = (typeof item === 'object' && item._w) || '';
                const h = (typeof item === 'object' && item._h) || '';
                const dim = (w && h) ? `${w}×${h}` : '';
                return `<div style="flex:0 0 auto;width:120px;position:relative;" ondblclick="event.stopPropagation();window._canvas._showLightbox('${this._escJs(url)}','${type}')">
                    <div style="width:120px;height:90px;border-radius:8px;overflow:hidden;position:relative;background:var(--surface-2);">
                        ${isImg
                            ? `<img src="${this._esc(url)}" style="width:100%;height:100%;object-fit:cover;display:block;cursor:pointer;" alt="${_t('nodeType.output','输出')}" onerror="this.style.display='none'" title="${_t('output.clickToCreateImage','单击创建图片节点')}" onclick="event.stopPropagation();window._canvas._onOutputImageClick(event,'${this._escJs(url)}')">`
                            : `<video src="${this._esc(url)}" style="width:100%;height:100%;object-fit:cover;display:block;cursor:pointer;" preload="metadata" disablePictureInPicture muted ondblclick="event.stopPropagation();window._canvas._showLightbox('${this._escJs(url)}','video')"></video>`}
                        <div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;pointer-events:none;${isImg?'display:none;':''}">
                            <span style="font-size:26px;color:#fff;text-shadow:0 2px 6px rgba(0,0,0,.7);">▶</span>
                        </div>
                    </div>
                    ${dim ? `<div class="node-meta" style="font-size:9px;text-align:center;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${dim}</div>` : ''}
                    <button style="position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;border:none;background:rgba(0,0,0,.6);color:#fff;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:0;padding:0;z-index:1;" onclick="event.stopPropagation();window._canvas._removeOutputItem('${node.id}',${i},'${type}')" title="${_t('node.delete','删除')}">×</button>
                </div>`;
            };
            const imgItems = (node.images || []).map((img, i) => renderItem(img, i, 'image')).join('');
            const vidItems = (node.videos || []).map((vid, i) => renderItem(vid, i, 'video')).join('');
            const hasContent = imgItems || vidItems || node.outputText;
            if (hasContent) {
                return `
                    ${node.outputText ? `<div class="node-preview">${this._esc(node.outputText.slice(0, 600))}</div>` : ''}
                    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:4px;justify-content:flex-start;">${imgItems}${vidItems}</div>
                    <div class="node-actions" style="margin-top:8px;">
                        <button class="tool-btn" style="flex:1;font-size:11px;padding:4px;" onclick="event.stopPropagation();window._canvas._clearOutput('${node.id}')">${_t('output.clearAll','清除全部')}</button>
                    </div>
                `;
            }
            return '<div style="text-align:center;padding:20px;color:var(--muted)">' + _t('output.emptyHint','连接上游节点后<br>结果自动显示在这里') + '</div>';
        }
};

CanvasEngine.prototype._renderNodeBody_loop = function(node, meta) {
    {
            const inputs = this._collectInputs(node.id);
            if (!node._queue) node._queue = [];
            // 确保 _removedUrls 是数组（Set 不能 JSON 序列化，加载后变成空对象）
            if (!node._removedUrls || typeof node._removedUrls[Symbol.iterator] !== 'function') node._removedUrls = [];
            const activeUrls = new Set(inputs.images);
            node._removedUrls = node._removedUrls.filter(u => activeUrls.has(u));
            // 追加新连线（跳过用户手动移除的）
            for (const url of inputs.images) {
                if (!node._queue.some(q => q.url === url) && !node._removedUrls.includes(url)) {
                    node._queue.push({ url, id: 'q_' + Date.now() + Math.random() });
                }
            }
            const queue = node._queue;
            return `
                <div style="display:flex;gap:8px;overflow-x:auto;padding:8px 0;min-height:172px;align-items:center;" id="loop-queue-${node.id}">
                    ${queue.length ? queue.map((item, i) => `
                        <div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:4px;">
                            <div style="display:flex;gap:0;">
                                <button style="width:36px;height:28px;border:none;background:var(--surface-2);color:var(--text);font-size:14px;cursor:pointer;border-radius:8px 0 0 8px;padding:0;line-height:1;" onclick="event.stopPropagation();window._canvas._moveLoopItem('${node.id}',${i},-1)" ${i===0?'disabled':''}>◀</button>
                                <button style="width:36px;height:28px;border:none;background:var(--surface-2);color:var(--text);font-size:14px;cursor:pointer;border-radius:0 8px 8px 0;padding:0;line-height:1;" onclick="event.stopPropagation();window._canvas._moveLoopItem('${node.id}',${i},1)" ${i===queue.length-1?'disabled':''}>▶</button>
                            </div>
                            <div style="width:128px;height:128px;border-radius:10px;overflow:hidden;border:1px solid var(--border);position:relative;">
                                <img src="${this._esc(item.url)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display='none'">
                            </div>
                            <button class="loop-thumb-x" onmousedown="event.stopPropagation();event.stopImmediatePropagation();event.preventDefault();window._canvas._removeLoopItem('${node.id}',${i})" title="${_t('output.remove','移除')}">×</button>
                        </div>
                    `).join('') : '<span style="color:var(--muted);font-size:12px;">' + _t('loop.emptyHint','连接图片后显示') + '</span>'}
                </div>
                <div class="node-meta">${_t('loop.segHint','文本分段')}: <code>----</code> / <code>1. 2. 3.</code> · ${_t('loop.count','共 # 张').replace('#',queue.length||0)}</div>
                ${meta}
            `;
        }
};

CanvasEngine.prototype._renderNodeBody_comfy = function(node, meta) {
    {
            const wf = (this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);
            const fields = wf?._fields||[];
            // 节点已选工作流但工作流已被删除：显示警告
            const missingWf = node.comfyWorkflow && !wf;
            return `
                <select onchange="window._canvas._updateNodeProp('${node.id}','comfyWorkflow',this.value);window._canvas._renderAllDeferred()" style="width:100%;height:32px;margin-bottom:8px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                    <option value="">${_t('comfy.selectWorkflow','选择工作流...')}</option>
                    ${(this._comfyWfList||[]).map(w=>`<option value="${w.name}" ${w.name===node.comfyWorkflow?'selected':''}>${this._esc(w.title||w.name)}</option>`).join('')}
                </select>
                ${missingWf ? `<div style="color:#f87171;font-size:10px;margin-bottom:4px;font-weight:600;">⚠ ${_t('comfy.workflowMissing','工作流已删除，请重新选择或上传')}</div>` : ''}
                ${fields.length ? `
                <div style="font-size:10px;font-weight:800;color:var(--muted);margin-bottom:4px;">${_t('comfy.inputPorts','输入端口（连接上游节点）')}</div>
                <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:6px;">
                    ${fields.map(f=>`
                        <div style="display:flex;align-items:center;gap:6px;padding:4px 8px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;">
                            <span style="width:10px;height:10px;border-radius:50%;background:#3b82f6;flex-shrink:0;" title="${this._esc(f.input)}"></span>
                            <span style="color:var(--text);font-weight:700;">${this._esc(f.name||f.input)}</span>
                            <span style="margin-left:auto;font-size:9px;color:var(--muted);">${f.type==='image'?'🖼':'📝'}</span>
                        </div>
                    `).join('')}
                </div>
                ` : ''}
                <div class="node-meta">${_t('comfy.hint','连接上游节点后点运行，自动按类型映射：图片→图片字段，文本→提示词字段。')}</div>
                <div class="node-actions"><button class="tool-btn" onclick="window._canvas._runComfyUI('${node.id}')">${_t('common.run','运行')}</button></div>
                ${meta}
            `;
        }

};

;

