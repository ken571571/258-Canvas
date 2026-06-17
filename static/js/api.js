const APP_API_KEY_STORAGE = "canvas571_api_key";

function getStoredApiKey() {
    return sessionStorage.getItem(APP_API_KEY_STORAGE) || "";
}

function setStoredApiKey(value) {
    const key = String(value || "").trim();
    if (key) {
        sessionStorage.setItem(APP_API_KEY_STORAGE, key);
    } else {
        sessionStorage.removeItem(APP_API_KEY_STORAGE);
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
    const response = await fetch(url, withAuthHeaders(options));
    if (response.status !== 401 || retrying || silent) {
        return response;
    }

    const key = prompt(_t('auth.enterPassword','请输入访问密码'));
    if (!key) {
        return response;
    }

    setStoredApiKey(key);
    return apiFetch(url, options, true);
}

async function apiJson(url, options = {}) {
    const response = await apiFetch(url, options);
    const data = await response.json().catch(() => ({}));
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
