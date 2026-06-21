CanvasEngine.prototype._renderProviderOpts = function(currentId, modelType = 'all') {
    try {
        const provs = getCachedProviders();
        // 按节点类型过滤：image_gen 只要图片平台，video_gen 只要视频平台
        let filtered;
        if (modelType === 'image') {
            filtered = provs.filter(p => (p.image_models||[]).length > 0);
        } else if (modelType === 'video') {
            filtered = provs.filter(p => (p.video_models||[]).length > 0);
        } else {
            filtered = provs.filter(p => (p.image_models||[]).length > 0 || (p.video_models||[]).length > 0);
        }
        // 当前 provider 为空时，默认选第一个可用平台
        const selId = currentId || (filtered[0]?.id) || '';
        // 确保当前选择的 provider 在列表中（即使它不满足过滤条件也强制加入）
        if (currentId && !filtered.some(p => p.id === currentId)) {
            const cur = provs.find(p => p.id === currentId);
            if (cur) filtered.unshift(cur);
        }
        return filtered.map(p => `<option value="${this._esc(p.id)}" ${p.id===selId?'selected':''}>${this._esc(p.name||p.id)}</option>`).join('');
    } catch(e) { return ''; }
};


CanvasEngine.prototype._renderModelOpts = function(providerId, currentModel, modelType = 'all') {
    try {
        const provs = getCachedProviders();
        // providerId 为空时回退到第一个按类型匹配的平台
        const pid = providerId || (modelType === 'image'
            ? provs.find(p => (p.image_models||[]).length > 0)?.id
            : modelType === 'video'
            ? provs.find(p => (p.video_models||[]).length > 0)?.id
            : provs.find(p => (p.image_models||[]).length > 0 || (p.video_models||[]).length > 0)?.id) || '';
        const p = provs.find(x => x.id === pid);
        // modelType: 'image'=只图片模型, 'video'=只视频模型, 'all'=合并
        let models;
        if (modelType === 'image') models = p?.image_models || [];
        else if (modelType === 'video') models = p?.video_models || [];
        else models = [...(p?.image_models||[]), ...(p?.video_models||[])];
        if (!models.length) models = [];
        // 大小写不敏感匹配当前模型（后端 fetch_models 统一为小写，但用户可能在设置页手动输入）
        const lowerModel = (currentModel || '').toLowerCase();
        const selModel = (currentModel && models.some(m => m.toLowerCase() === lowerModel)) ? currentModel : models[0];
        return models.map(m => `<option value="${this._esc(m)}" ${m===selModel?'selected':''}>${this._esc(m)}</option>`).join('');
    } catch(e) { return ''; }
};
