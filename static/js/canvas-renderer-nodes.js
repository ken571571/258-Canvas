CanvasEngine.prototype._renderNodes = function() {
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

        const hasInput = ['image_gen', 'video_gen', 'generator', 'agent', 'output', 'loop'].includes(node.type);
        const isComfy = node.type === 'comfy';
        const hasOutput = ['image', 'prompt', 'image_gen', 'video_gen', 'generator', 'agent', 'loop', 'output', 'comfy'].includes(node.type);
        const badge = this._renderNodeStateBadge(node);

        el.innerHTML = `<div class="node-head"><div class="node-head-title"><span>${this._esc(node.label || node.type)}</span>${node.type==='image'?`<span class="node-desc" data-node-desc="${node.id}" title="双击编辑描述">${this._esc(node.desc||'')}</span>`:''}${badge}</div><button class="node-delete" title="删除节点" data-del="${node.id}">&times;</button></div><div class="node-body" data-body="${node.id}">${this._renderNodeBody(node)}</div>${hasInput?`<div class="port port-in" data-port="in" data-node="${node.id}"></div>`:''}${isComfy?(()=>{const wf=(this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);const flds=wf?._fields||[];return flds.map((f,i)=>`<div class=\"port port-in comfy-port\" data-port=\"in\" data-node=\"${node.id}\" data-field-id=\"${f.id}\" style=\"top:${48+i*34}px;left:-9px;width:18px;height:18px;pointer-events:auto;background:#3b82f6;border-width:3px;\" title=\"${this._esc(f.name||f.input)}\"></div>`).join('');})():''}${hasOutput?`<div class="port port-out" data-port="out" data-node="${node.id}"></div>`:''}<div class="resize-handle" data-resize="${node.id}"></div>`;

        el.addEventListener('mousedown', event => {
            if (event.target.closest('.port')||event.target.closest('button')||event.target.closest('textarea')||event.target.closest('input')||event.target.closest('select')||event.target.closest('.resize-handle')||event.target.closest('[data-upload]')||event.target.closest('[data-node-desc]')||event.target.closest('[draggable]')||event.target.closest('img')||event.target.closest('video')||event.target.closest('.node-preview')) return;
            event.preventDefault();
            if ((event.ctrlKey||event.metaKey)&&!event.shiftKey){this.selected.clear();this.selected.add(node.id);}
            else if(event.shiftKey){if(this.selected.has(node.id)){this.selected.delete(node.id);this._renderAll();return;}this.selected.add(node.id);}
            else{this.selected.clear();this.selected.add(node.id);}
            this.selectedConnectionId='';
            const ids=Array.from(this.selected);
            const ctrlExtract=event.ctrlKey||event.metaKey;
            if(ctrlExtract){ids.forEach(did=>{this.groups.forEach(g=>{g.childIds=g.childIds.filter(cid=>cid!==did)});});this.groups=this.groups.filter(g=>g.childIds.length>=2);}
            const pointerStart=this._screenToWorld(event.clientX,event.clientY);
            this._dragNodes={pointerStart,items:this.nodes.filter(item=>ids.includes(item.id)).map(item=>({node:item,startX:item.x,startY:item.y}))};
            this._renderAll();
        });

        el.querySelector('[data-del]')?.addEventListener('click',event=>{event.stopPropagation();this._deleteNode(node.id);});

        el.querySelectorAll('.port').forEach(port=>{port.addEventListener('mousedown',event=>{event.stopPropagation();event.preventDefault();this.selectedConnectionId='';this._linkFrom={nodeId:node.id,portType:port.dataset.port};this._tempPointer=this._screenToWorld(event.clientX,event.clientY);this._renderLinks();});});

        el.querySelector('.resize-handle')?.addEventListener('mousedown',event=>{event.stopPropagation();event.preventDefault();this._resizeNode={node,sx:event.clientX,sy:event.clientY,startWidth:node.w||260,startHeight:node.h||120};const onMove=moveEvent=>{node.w=Math.max(180,this._resizeNode.startWidth+(moveEvent.clientX-this._resizeNode.sx)/this.view.scale);el.style.width=`${node.w}px`;if(node.type!=='generator'&&node.type!=='image_gen'&&node.type!=='video_gen'){node.h=Math.max(80,this._resizeNode.startHeight+(moveEvent.clientY-this._resizeNode.sy)/this.view.scale);el.style.height=`${node.h}px`;const ta=el.querySelector('textarea');if(ta){const headH=el.querySelector('.node-head')?.offsetHeight||44;const taH=Math.max(40,node.h-headH-36);ta.style.height=`${taH}px`;node._taH=taH;}}};const onUp=()=>{window.removeEventListener('mousemove',onMove);window.removeEventListener('mouseup',onUp);this._resizeNode=null;this._renderAll();this._markDirty();};window.addEventListener('mousemove',onMove);window.addEventListener('mouseup',onUp);});

        this.nodesEl.appendChild(el);
        const renderedH=el.offsetHeight;
        // 高度取实际内容和手动设置的最大值（不能小于内容）
        node.h=Math.max(renderedH||100,node.h||100);
        // 列队 X 按钮
        el.querySelectorAll('.loop-thumb-x').forEach(btn=>{btn.addEventListener('mousedown',e=>{e.stopPropagation();e.stopImmediatePropagation();e.preventDefault();const nid=btn.dataset.loopRm;const idx=parseInt(btn.dataset.loopRmIdx);if(nid&&!isNaN(idx)){this._removeLoopItem(nid,idx);}});});
        // ComfyUI 多端口动态添加
        if(node.type==='comfy'){const wf=(this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);(wf?._fields||[]).forEach((f,i)=>{const p=document.createElement('div');p.className='port port-in comfy-port';p.dataset.port='in';p.dataset.node=node.id;p.dataset.fieldId=f.id;p.style.cssText='top:'+(48+i*34)+'px;left:-9px;width:18px;height:18px;pointer-events:auto;';p.title=f.name||f.input;p.addEventListener('mousedown',e=>{e.stopPropagation();e.preventDefault();this.selectedConnectionId='';this._linkFrom={nodeId:node.id,portType:'in'};this._tempPointer=this._screenToWorld(e.clientX,e.clientY);this._renderLinks();});el.appendChild(p);});}
    });
};


CanvasEngine.prototype._renderNodeBody = function(node) {
    const meta = this._renderNodeMeta(node);

    switch (node.type) {
        case 'image':
            if (node.url) {
                return `
                    <img src="${this._esc(node.url)}" style="max-width:100%;border-radius:12px;display:block" alt="${this._esc(node.label)}" onerror="this.style.display='none'">
                    ${node.imageName ? `<div class="node-meta">${this._esc(node.imageName)}${(node.imageWidth && node.imageHeight) ? ` (${node.imageWidth}×${node.imageHeight})` : ''}</div>` : ''}
                    <div class="node-actions" style="margin-top:6px;">
                        <label class="tool-btn" style="flex:1;cursor:pointer;text-align:center;padding:5px;font-size:11px;" data-upload="${node.id}">
                            替换<input type="file" accept="image/*" style="display:none" onchange="window._canvas._handleImageUpload('${node.id}', this)">
                        </label>
                        <button class="tool-btn" style="flex:1;font-size:11px;padding:5px;" onclick="event.stopPropagation();window._canvas._removeImage('${node.id}')">删除</button>
                    </div>
                `;
            }
            return `
                <label style="display:block;text-align:center;padding:20px;color:var(--muted);cursor:pointer" data-upload="${node.id}">
                    点击上传图片<br><span style="font-size:10px;">或从右侧资产库拖入</span>
                    <input type="file" accept="image/*" style="display:none" onchange="window._canvas._handleImageUpload('${node.id}', this)">
                </label>
            `;

        case 'prompt':
            return `
                <textarea class="node-input" placeholder="输入提示词..." oninput="window._canvas._updateNodeProp('${node.id}', 'text', this.value)" style="${node._taH ? 'height:'+node._taH+'px;' : ''}">${this._esc(node.text || '')}</textarea>
                ${meta}
            `;

        case 'generator': {
            const inputs = this._collectInputs(node.id);
            const hasRefImg = inputs.images.length > 0;
            const sizes = [['1024x1024','1:1 方形'],['1792x1024','16:9 横版'],['1024x1792','9:16 竖版'],['1536x1024','3:2 横版'],['1024x1536','2:3 竖版'],['1280x896','4:3 横版'],['896x1280','3:4 竖版'],['768x1344','9:16 竖版'],['1344x768','16:9 横版']];
            const selSize = node.size || '1024x1024';
            if (!sizes.some(s => s[0] === selSize)) sizes.unshift([selSize, '']);
            return `
                <div style="display:flex;gap:6px;margin-bottom:6px;min-width:0;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','provider_id',this.value);window._canvas._updateNodeProp('${node.id}','model','');window._canvas._renderAll()" style="flex:1;min-width:0;height:32px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${this._renderProviderOpts(node.provider_id || '')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','model',this.value);window._canvas._renderAll()" style="flex:1.5;min-width:0;height:32px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${this._renderModelOpts(node.provider_id || '', node.model || '')}
                    </select>
                </div>
                ${(() => {
                    const provs2 = getCachedProviders();
                    const prov2 = provs2.find(x => x.id === (node.provider_id || ''));
                    const curModel2 = node.model || '';
                    const isVideo2 = (prov2?.video_models||[]).includes(curModel2);
                    if (!isVideo2) return '';
                    const durations = this._getVideoDurations(curModel2);
                    const selDur = node.duration || 5;
                    const resolutions = this._getVideoResolutions(curModel2);
                    // 有参考图：默认自动跟随，用户也可手动选分辨率
                    const hasRefForVideo = inputs.images && inputs.images.length > 0;
                    const defaultRes = hasRefForVideo ? 'auto' : (resolutions[0]?.v || '720p');
                    const selRes = node.resolution || defaultRes;
                    const autoLabel = hasRefForVideo ? '📎 跟随输入图' : '📎 自动';
                    return `<div style="display:flex;gap:6px;margin-bottom:6px;">
                        <select onchange="window._canvas._updateNodeProp('${node.id}','duration',parseInt(this.value))" style="flex:1;height:30px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                            ${durations.map(d => `<option value="${d}" ${d===selDur?'selected':''}>⏱ ${d}s</option>`).join('')}
                        </select>
                        <select onchange="window._canvas._updateNodeProp('${node.id}','resolution',this.value)" style="flex:1.5;height:30px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                            <option value="auto" ${selRes==='auto'?'selected':''}>${autoLabel}</option>
                            ${resolutions.map(r => `<option value="${r.v}" ${r.v===selRes?'selected':''}>${r.l}</option>`).join('')}
                        </select>
                    </div>`;
                })()}
                ${(() => {
                    const provs3 = getCachedProviders();
                    const prov3 = provs3.find(x => x.id === (node.provider_id || ''));
                    const curModel3 = node.model || '';
                    const isVideo3 = (prov3?.video_models||[]).includes(curModel3);
                    if (!hasRefImg) {
                        // 文生图：预设尺寸 / 自定义
                        return isVideo3 ? '' : `
                    <select onchange="if(this.value==='custom_wh'){window._canvas._updateNodeProp('${node.id}','_customWH',true);window._canvas._updateNodeProp('${node.id}','size','${node._customW || 1024}x${node._customH || 1024}');}else{window._canvas._updateNodeProp('${node.id}','_customWH',false);window._canvas._updateNodeProp('${node.id}','size',this.value);};window._canvas._renderAll()" style="width:100%;height:28px;padding:0 6px;margin-bottom:${node._customWH?'4px':'6px'};border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        ${sizes.map(s => `<option value="${s[0]}" ${!node._customWH && s[0]===selSize?'selected':''}>${s[0]}${s[1]?' · '+s[1]:''}</option>`).join('')}
                        <option value="custom_wh" ${node._customWH?'selected':''}>✏️ 自定义 →</option>
                    </select>
                    ${node._customWH ? `
                        <div style="display:flex;gap:6px;margin-bottom:6px;align-items:center;">
                            <span style="font-size:10px;color:var(--muted);flex-shrink:0;">W</span>
                            <input type="number" value="${node._customW || 1024}" min="64" max="8192" step="64" placeholder="宽" oninput="const w=parseInt(this.value)||1024;const h=parseInt(this.nextElementSibling.nextElementSibling?.value)||1024;window._canvas._updateNodeProp('${node.id}','_customW',w);window._canvas._updateNodeProp('${node.id}','size',w+'x'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">
                            <span style="font-size:10px;color:var(--muted);flex-shrink:0;">H</span>
                            <input type="number" value="${node._customH || 1024}" min="64" max="8192" step="64" placeholder="高" oninput="const w=parseInt(this.previousElementSibling.previousElementSibling?.value)||1024;const h=parseInt(this.value)||1024;window._canvas._updateNodeProp('${node.id}','_customH',h);window._canvas._updateNodeProp('${node.id}','size',w+'x'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">
                        </div>
                    ` : ''}`;
                    }
                    // 图生图：x2/x3/x4 倍率（视频模型不需要）
                    if (isVideo3) return '';
                    return `
                    <div style="display:flex;gap:6px;margin-bottom:6px;">
                        <select onchange="window._canvas._updateNodeProp('${node.id}','size',this.value);window._canvas._renderAll()" style="flex:1;height:30px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                            <option value="" ${!node.size?'selected':''}>📎 跟随输入图</option>
                            <option value="x2" ${node.size==='x2'?'selected':''}>x2 放大</option>
                            <option value="x3" ${node.size==='x3'?'selected':''}>x3 放大</option>
                            <option value="x4" ${node.size==='x4'?'selected':''}>x4 放大</option>
                            <option value="x5" ${node.size==='x5'?'selected':''}>x5 放大</option>
                            <option value="custom" ${node.size==='custom'||(node.size||'').startsWith('custom:')?'selected':''}>自定义最长边 →</option>
                        </select>
                        ${node.size==='custom' || (node.size||'').startsWith('custom:') ? `<input type="number" value="${node._customEdge||((node.size||'').startsWith('custom:')?node.size.split(':')[1]:2048)}" min="512" max="8192" step="64" placeholder="最长边 px" onkeydown="if(event.key==='Enter'){this.blur()}" onchange="window._canvas._updateNodeProp('${node.id}','_customEdge',parseInt(this.value)||2048);window._canvas._updateNodeProp('${node.id}','size','custom:'+this.value)" style="flex:1;height:30px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);outline:none;width:90px;">` : ''}
                    </div>`;
                })()}
                ${meta || '<div class="node-meta">连接提示词或图片后生成结果，并自动写入输出节点。</div>'}
                <div class="node-actions">
                    <button class="tool-btn" onclick="window._canvas._runPipeline('${node.id}')">生成图片</button>
                </div>
            `;
        }

        case 'image_gen': {
            const imgInputs = this._collectInputs(node.id);
            const imgHasRef = imgInputs.images.length > 0;
            const imgSizes = [['1024x1024','1:1 方形'],['1792x1024','16:9 横版'],['1024x1792','9:16 竖版'],['1536x1024','3:2 横版'],['1024x1536','2:3 竖版'],['1280x896','4:3 横版'],['896x1280','3:4 竖版'],['768x1344','9:16 竖版'],['1344x768','16:9 横版']];
            const imgSelSize = node.size || '1024x1024';
            if (!imgSizes.some(s => s[0] === imgSelSize)) imgSizes.unshift([imgSelSize, '']);
            const selOpts = 'height:28px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            return `
                <div style="display:flex;gap:4px;margin-bottom:4px;min-width:0;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','provider_id',this.value);window._canvas._updateNodeProp('${node.id}','model','');window._canvas._renderAll()" style="flex:1;min-width:0;${selOpts}">
                        ${this._renderProviderOpts(node.provider_id || '', 'image')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','model',this.value);window._canvas._renderAll()" style="flex:1.5;min-width:0;${selOpts}">
                        ${this._renderModelOpts(node.provider_id || '', node.model || '', 'image')}
                    </select>
                </div>
                ${imgHasRef ? `
                    <div style="display:flex;gap:4px;margin-bottom:4px;">
                        <select onchange="window._canvas._updateNodeProp('${node.id}','size',this.value);window._canvas._renderAll()" style="flex:1;height:28px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                            <option value="" ${!node.size?'selected':''}>📎 跟随输入图</option>
                            <option value="x2" ${node.size==='x2'?'selected':''}>x2 放大</option>
                            <option value="x3" ${node.size==='x3'?'selected':''}>x3 放大</option>
                            <option value="x4" ${node.size==='x4'?'selected':''}>x4 放大</option>
                            <option value="x5" ${node.size==='x5'?'selected':''}>x5 放大</option>
                            <option value="custom" ${node.size==='custom'||(node.size||'').startsWith('custom:')?'selected':''}>自定义最长边 →</option>
                        </select>
                        ${node.size==='custom' || (node.size||'').startsWith('custom:') ? `<input type="number" value="${node._customEdge||((node.size||'').startsWith('custom:')?node.size.split(':')[1]:2048)}" min="512" max="8192" step="64" placeholder="最长边 px" onkeydown="if(event.key==='Enter'){this.blur()}" onchange="window._canvas._updateNodeProp('${node.id}','_customEdge',parseInt(this.value)||2048);window._canvas._updateNodeProp('${node.id}','size','custom:'+this.value)" style="flex:1;height:28px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);outline:none;width:90px;">` : ''}
                    </div>
                ` : `
                    <select onchange="if(this.value==='custom_wh'){window._canvas._updateNodeProp('${node.id}','_customWH',true);window._canvas._updateNodeProp('${node.id}','size','${node._customW || 1024}x${node._customH || 1024}');}else{window._canvas._updateNodeProp('${node.id}','_customWH',false);window._canvas._updateNodeProp('${node.id}','size',this.value);};window._canvas._renderAll()" style="width:100%;height:28px;padding:0 6px;margin-bottom:${node._customWH?'4px':'4px'};border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        ${imgSizes.map(s => `<option value="${s[0]}" ${!node._customWH && s[0]===imgSelSize?'selected':''}>${s[0]}${s[1]?' · '+s[1]:''}</option>`).join('')}
                        <option value="custom_wh" ${node._customWH?'selected':''}>✏️ 自定义 →</option>
                    </select>
                    ${node._customWH ? `
                        <div style="display:flex;gap:4px;margin-bottom:4px;align-items:center;">
                            <span style="font-size:10px;color:var(--muted);flex-shrink:0;">W</span>
                            <input type="number" value="${node._customW || 1024}" min="64" max="8192" step="64" placeholder="宽" oninput="const w=parseInt(this.value)||1024;const h=parseInt(this.nextElementSibling.nextElementSibling?.value)||1024;window._canvas._updateNodeProp('${node.id}','_customW',w);window._canvas._updateNodeProp('${node.id}','size',w+'x'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">
                            <span style="font-size:10px;color:var(--muted);flex-shrink:0;">H</span>
                            <input type="number" value="${node._customH || 1024}" min="64" max="8192" step="64" placeholder="高" oninput="const w=parseInt(this.previousElementSibling.previousElementSibling?.value)||1024;const h=parseInt(this.value)||1024;window._canvas._updateNodeProp('${node.id}','_customH',h);window._canvas._updateNodeProp('${node.id}','size',w+'x'+h)" style="flex:1;min-width:0;height:22px;padding:0 4px;border-radius:4px;border:1px solid var(--border);background:var(--bg);font-size:10px;color:var(--text);outline:none;">
                        </div>
                    ` : ''}
                `}
                ${meta || '<div class="node-meta" style="margin-bottom:2px;">连接提示词或图片后生成结果</div>'}
                <div class="node-actions" style="margin-top:0;">
                    <button class="tool-btn" style="font-size:11px;padding:4px 8px;" onclick="window._canvas._runPipeline('${node.id}')">🖼 生成图片</button>
                </div>
            `;
        }

        case 'video_gen': {
            const vidInputs = this._collectInputs(node.id);
            const hasVidRef = vidInputs.images && vidInputs.images.length > 0;
            const curModel = node.model || '';
            const durations = this._getVideoDurations(curModel);
            const selDur = node.duration || 5;
            const resolutions = this._getVideoResolutions(curModel);
            const defaultRes = hasVidRef ? 'auto' : (resolutions[0]?.v || '720p');
            const selRes = node.resolution || defaultRes;
            const autoLabel = hasVidRef ? '📎 跟随输入图' : '📎 自动';
            const selOpts = 'height:28px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            return `
                <div style="display:flex;gap:4px;margin-bottom:4px;min-width:0;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','provider_id',this.value);window._canvas._updateNodeProp('${node.id}','model','');window._canvas._renderAll()" style="flex:1;min-width:0;${selOpts}">
                        ${this._renderProviderOpts(node.provider_id || '', 'video')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','model',this.value);window._canvas._renderAll()" style="flex:1.5;min-width:0;${selOpts}">
                        ${this._renderModelOpts(node.provider_id || '', node.model || '', 'video')}
                    </select>
                </div>
                <div style="display:flex;gap:4px;margin-bottom:4px;">
                    <select onchange="window._canvas._updateNodeProp('${node.id}','duration',parseInt(this.value))" style="flex:1;height:28px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        ${durations.map(d => `<option value="${d}" ${d===selDur?'selected':''}>⏱ ${d}s</option>`).join('')}
                    </select>
                    <select onchange="window._canvas._updateNodeProp('${node.id}','resolution',this.value)" style="flex:1.5;height:28px;padding:0 4px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                        <option value="auto" ${selRes==='auto'?'selected':''}>${autoLabel}</option>
                        ${resolutions.map(r => `<option value="${r.v}" ${r.v===selRes?'selected':''}>${r.l}</option>`).join('')}
                    </select>
                </div>
                ${(() => {
                    const audioModels = ['doubao-seedance', 'veo-', 'wan2.5', 'wan2.6'];
                    if (!audioModels.some(k => curModel.includes(k))) return '';
                    return `<label style="display:flex;align-items:center;gap:3px;cursor:pointer;font-size:10px;color:var(--muted);margin-bottom:4px;">
                        <input type="checkbox" ${node.generate_audio!==false?'checked':''} onchange="window._canvas._updateNodeProp('${node.id}','generate_audio',this.checked)" style="width:13px;height:13px;accent-color:var(--accent);">🔊 有声</label>`;
                })()}
                ${meta || '<div class="node-meta" style="margin-bottom:2px;">连接提示词或图片后生成视频</div>'}
                <div class="node-actions" style="margin-top:0;">
                    <button class="tool-btn" style="font-size:11px;padding:4px 8px;" onclick="window._canvas._runPipeline('${node.id}')">🎬 生成视频</button>
                </div>
            `;
        }

        case 'agent':
            return `
                <select onchange="window._canvas._updateNodeProp('${node.id}','agentId',this.value)" style="width:100%;height:32px;margin-bottom:8px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                    <option value="">选择智能体...</option>
                    ${(this._agentList||[]).map(a => `<option value="${a.id}" ${a.id===node.agentId?'selected':''}>${this._esc(a.name||a.id)}</option>`).join('')}
                </select>
                <textarea class="node-input" placeholder="输入任务要求..." oninput="window._canvas._updateNodeProp('${node.id}', 'userInput', this.value)" style="${node._taH ? 'height:'+node._taH+'px;' : ''}">${this._esc(node.userInput || '')}</textarea>
                ${meta || '<div class="node-meta">选择已有的智能体并输入任务要求。</div>'}
                ${node.lastResult ? `<div class="node-preview" style="max-height:192px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;">${this._esc(node.lastResult)}</div>` : ''}
                <div class="node-actions">
                    <button class="tool-btn" onclick="window._canvas._runAgent('${node.id}')">运行</button>
                </div>
            `;

        case 'output': {
            const renderItem = (item, i, type) => {
                const url = typeof item === 'string' ? item : (item.url || '');
                if (!url) return '';
                const isImg = /\.(png|jpg|jpeg|webp|gif)$/i.test(url) || type === 'image';
                const w = (typeof item === 'object' && item._w) || '';
                const h = (typeof item === 'object' && item._h) || '';
                const dim = (w && h) ? `${w}×${h}` : '';
                return `<div style="flex:0 0 auto;width:120px;position:relative;" ondblclick="event.stopPropagation();window._canvas._showLightbox('${this._esc(url)}','${type}')">
                    <div style="width:120px;height:90px;border-radius:8px;overflow:hidden;position:relative;background:var(--surface-2);">
                        ${isImg
                            ? `<img src="${this._esc(url)}" style="width:100%;height:100%;object-fit:cover;display:block;cursor:pointer;" alt="输出" onerror="this.style.display='none'" ondblclick="event.stopPropagation();window._canvas._showLightbox('${this._esc(url)}','image')">`
                            : `<video src="${this._esc(url)}" style="width:100%;height:100%;object-fit:cover;display:block;cursor:pointer;" preload="metadata" disablePictureInPicture muted ondblclick="event.stopPropagation();window._canvas._showLightbox('${this._esc(url)}','video')"></video>`}
                        <div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;pointer-events:none;${isImg?'display:none;':''}">
                            <span style="font-size:26px;color:#fff;text-shadow:0 2px 6px rgba(0,0,0,.7);">▶</span>
                        </div>
                    </div>
                    ${dim ? `<div class="node-meta" style="font-size:9px;text-align:center;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${dim}</div>` : ''}
                    <button style="position:absolute;top:2px;right:2px;width:20px;height:20px;border-radius:50%;border:none;background:rgba(0,0,0,.6);color:#fff;font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;line-height:0;padding:0;z-index:1;" onclick="event.stopPropagation();window._canvas._removeOutputItem('${node.id}',${i},'${type}')" title="删除">×</button>
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
                        <button class="tool-btn" style="flex:1;font-size:11px;padding:4px;" onclick="event.stopPropagation();window._canvas._clearOutput('${node.id}')">清除全部</button>
                    </div>
                `;
            }
            return '<div style="text-align:center;padding:20px;color:var(--muted)">连接上游节点后<br>结果自动显示在这里</div>';
        }

        case 'loop': {
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
                                <img src="${this._esc(item.url)}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.remove()">
                            </div>
                            <button class="loop-thumb-x" onmousedown="event.stopPropagation();event.stopImmediatePropagation();event.preventDefault();window._canvas._removeLoopItem('${node.id}',${i})" title="移除">×</button>
                        </div>
                    `).join('') : '<span style="color:var(--muted);font-size:12px;">连接图片后显示</span>'}
                </div>
                <div class="node-meta">文本分段: <code>----</code> 或 <code>1. 2. 3.</code> 分割 · 共<span style="font-weight:800;">${queue.length||0}</span>张</div>
                ${meta}
            `;
        }

        case 'comfy': {
            const wf = (this._comfyWfList||[]).find(w=>w.name===node.comfyWorkflow);
            const fields = wf?._fields||[];
            return `
                <select onchange="window._canvas._updateNodeProp('${node.id}','comfyWorkflow',this.value);window._canvas._renderAll()" style="width:100%;height:32px;margin-bottom:8px;padding:0 6px;border-radius:6px;border:1px solid var(--border);background:var(--bg);font-size:11px;color:var(--text);">
                    <option value="">选择工作流...</option>
                    ${(this._comfyWfList||[]).map(w=>`<option value="${w.name}" ${w.name===node.comfyWorkflow?'selected':''}>${this._esc(w.title||w.name)}</option>`).join('')}
                </select>
                ${fields.length ? `
                <div style="font-size:10px;font-weight:800;color:var(--muted);margin-bottom:4px;">输入端口（连接上游节点）</div>
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
                <div class="node-meta">连接上游节点后点运行，自动按类型映射：图片→图片字段，文本→提示词字段。</div>
                <div class="node-actions"><button class="tool-btn" onclick="window._canvas._runComfyUI('${node.id}')">运行</button></div>
                ${meta}
            `;
        }

        default:
            return '<div class="node-meta">未知节点类型</div>';
    }
};

