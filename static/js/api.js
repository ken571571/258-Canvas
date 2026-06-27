const APP_API_KEY_STORAGE = "canvas571_api_key";

function getStoredApiKey() {
    return localStorage.getItem(APP_API_KEY_STORAGE) || "";
}

function setStoredApiKey(value) {
    const key = String(value || "").trim();
    if (key) {
        localStorage.setItem(APP_API_KEY_STORAGE, key);
    } else {
        localStorage.removeItem(APP_API_KEY_STORAGE);
    }
}

function withAuthHeaders(options = {}) {
    const next = { ...options };
    const headers = new Headers(next.headers || {});
    const key = getStoredApiKey();
    if (key && !headers.has("X-API-Key") && !headers.has("Authorization")) {
        headers.set("X-API-Key", key);
    }
    next.headers = headers;
    return next;
}

async function apiFetch(url, options = {}, retrying = false) {
    const silent = options.silent === true;
    // v2.5.51：构建 fetch 专用 options 副本，不修改调用方原始对象
    // 默认 60s 超时（仅当调用方未传 AbortController/signal 时注入）
    var fetchOpts = { ...options };
    if (!fetchOpts.signal) {
        fetchOpts.signal = AbortSignal.timeout(60000);
    }
    const response = await fetch(url, withAuthHeaders(fetchOpts));
    if (response.status !== 401 || retrying || silent) {
        return response;
    }

    // 使用密码遮罩的自定义对话框（替代明文 prompt）
    const key = await (new Promise(function(resolve) {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99999;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = '<div style="background:var(--bg,#fff);border-radius:12px;padding:24px;box-shadow:0 16px 48px rgba(0,0,0,.3);min-width:320px;max-width:90vw;">' +
            '<div style="margin-bottom:12px;font-size:14px;font-weight:600;color:var(--text,#202124);">' + (_t('auth.enterPassword','请输入访问密码') || '请输入访问密码') + '</div>' +
            '<input type="password" style="width:100%;padding:8px 12px;border:1px solid var(--border,#ddd);border-radius:8px;font-size:14px;margin-bottom:12px;outline:none;" autofocus>' +
            '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
            '<button style="padding:6px 16px;border:1px solid var(--border,#ccc);border-radius:8px;background:var(--surface-2,#f3f4f1);cursor:pointer;font-size:13px;">' + (_t('common.cancel','取消') || '取消') + '</button>' +
            '<button style="padding:6px 16px;border:none;border-radius:8px;background:var(--accent,#2563eb);color:var(--accent-ink,#fff);cursor:pointer;font-size:13px;">' + (_t('common.confirm','确认') || '确认') + '</button>' +
            '</div></div>';
        document.body.appendChild(overlay);
        var input = overlay.querySelector('input');
        var btns = overlay.querySelectorAll('button');
        function done(val) { overlay.remove(); resolve(val); }
        btns[0].onclick = function() { done(''); };
        btns[1].onclick = function() { done(input.value); };
        input.onkeydown = function(e) { if (e.key === 'Enter') done(input.value); if (e.key === 'Escape') done(''); };
        input.focus();
    }));
    if (!key) {
        return response;
    }

    setStoredApiKey(key);
    // v2.5.51：重试时去掉原有 signal，避免复用已超时的 AbortSignal 导致立即失败
    var retryOpts = { ...options };
    delete retryOpts.signal;
    const retryResponse = await apiFetch(url, retryOpts, true);
    // 密码验证成功后通知父窗口刷新所有 iframe
    if (retryResponse.status !== 401) {
        try { window.parent.postMessage({type: 'auth-ready'}, location.origin); } catch(e) {}
    }
    return retryResponse;
}

async function apiJson(url, options = {}) {
    const response = await apiFetch(url, options);
    let data;
    try {
        data = await response.json();
    } catch (e) {
        console.warn('apiJson: JSON 解析失败', url, e);
        data = {};
    }
    if (!response.ok) {
        throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    }
    return data;
}

// ——— Provider 内存缓存 ———
// 前端统一从后端 /api/providers 获取 Provider 列表，缓存在模块级变量中。
// 所有页面通过 getCachedProviders() 同步读取，通过 refreshProviders() 异步刷新。
let _providersCache = null;
let _providersCachePromise = null;

async function refreshProviders() {
    // 去重：并发调用共享同一个 Promise
    if (_providersCachePromise) return _providersCachePromise;
    _providersCachePromise = (async () => {
        try {
            const data = await apiJson('/api/providers');
            _providersCache = data.providers || [];
        } catch (e) {
            console.warn('刷新 Provider 列表失败，使用缓存数据', e);
            if (!_providersCache) _providersCache = [];
        } finally {
            _providersCachePromise = null;
        }
        return _providersCache;
    })();
    return _providersCachePromise;
}

function getCachedProviders() {
    return _providersCache || [];
}

window.apiFetch = apiFetch;
window.apiJson = apiJson;
window.setStoredApiKey = setStoredApiKey;
window.getStoredApiKey = getStoredApiKey;
window.refreshProviders = refreshProviders;
window.getCachedProviders = getCachedProviders;
