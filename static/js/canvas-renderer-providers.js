CanvasEngine.prototype._renderProviderOpts = function(currentId, modelType = 'all') {
    try {
        const provs = getCachedProviders();
        // 显示所有有生图/视频模型的平台（含 openai），不严格过滤——模型列表下拉会按类型过滤
        const filtered = provs.filter(p => (p.image_models||[]).length > 0 || (p.video_models||[]).length > 0 || p.id === 'openai');
        // 当前 provider 为空时，默认选第一个可用平台
        const selId = currentId || (filtered[0]?.id) || 'openai';
        // 确保当前选择的 provider 在列表中
        if (currentId && !filtered.some(p => p.id === currentId)) {
            const cur = provs.find(p => p.id === currentId);
            if (cur) filtered.unshift(cur);
        }
        return filtered.map(p => `<option value="${p.id}" ${p.id===selId?'selected':''}>${this._esc(p.name||p.id)}</option>`).join('') || '<option value="openai">OpenAI</option>';
    } catch(e) { return '<option value="openai">OpenAI</option>'; }
};


CanvasEngine.prototype._renderModelOpts = function(providerId, currentModel, modelType = 'all') {
    try {
        const provs = getCachedProviders();
        // providerId 为空时回退到第一个可用平台
        const pid = providerId || provs.find(p => (p.image_models||[]).length > 0 || (p.video_models||[]).length > 0)?.id || 'openai';
        const p = provs.find(x => x.id === pid);
        // modelType: 'image'=只图片模型, 'video'=只视频模型, 'all'=合并
        let models;
        if (modelType === 'image') models = p?.image_models || [];
        else if (modelType === 'video') models = p?.video_models || [];
        else models = [...(p?.image_models||[]), ...(p?.video_models||[])];
        if (!models.length) models = [modelType==='video'?'veo3-fast':'dall-e-3'];
        // 如果当前模型不在该平台的模型列表中，且平台有模型 → 选平台第一个
        // 不再强制 prepend，避免把 dall-e-3 等默认值硬塞进 modelscope 等平台
        const selModel = (currentModel && models.includes(currentModel)) ? currentModel : models[0];
        return models.map(m => `<option value="${m}" ${m===selModel?'selected':''}>${m}</option>`).join('');
    } catch(e) { return '<option value="dall-e-3">dall-e-3</option>'; }
};

