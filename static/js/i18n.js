// 无限画布 i18n — 轻量国际化模块 (~2KB)
// 架构: 加载 JSON 翻译文件 → data-t 属性绑定 → postMessage 跨 iframe 同步
// 与 888 的自研 StudioI18n 完全不同: 使用 data-t 属性 + fetch JSON + 事件驱动

(function() {
  'use strict';

  const LANG_KEY = 'canvas571_lang';
  const DEFAULT_LANG = 'zh-CN';

  // --- State ---
  let _currentLang = DEFAULT_LANG;
  let _resources = { 'zh-CN': {}, 'en': {} };
  let _loaded = false;

  // --- Language Detection ---
  function detectLang() {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored === 'zh-CN' || stored === 'en') return stored;
    const nav = (navigator.language || '').toLowerCase();
    if (nav.startsWith('zh')) return 'zh-CN';
    if (nav.startsWith('en')) return 'en';
    return DEFAULT_LANG;
  }

  // --- Translation Lookup ---
  function t(key, fallback) {
    if (!_loaded) return fallback || key;
    const parts = key.split('.');
    let val = _resources[_currentLang];
    for (const p of parts) {
      if (val && typeof val === 'object') val = val[p];
      else return fallback || key;
    }
    return (val && typeof val === 'string') ? val : (fallback || key);
  }

  // --- DOM Update ---
  function updateDOM(root) {
    root = root || document;
    // data-t for textContent
    root.querySelectorAll('[data-t]').forEach(el => {
      const key = el.getAttribute('data-t');
      const translated = t(key);
      if (translated && translated !== key) {
        el.textContent = translated;
      }
    });
    // data-t-title for title attribute
    root.querySelectorAll('[data-t-title]').forEach(el => {
      const key = el.getAttribute('data-t-title');
      const translated = t(key);
      if (translated && translated !== key) {
        el.title = translated;
      }
    });
    // data-t-placeholder for input/textarea placeholder
    root.querySelectorAll('[data-t-placeholder]').forEach(el => {
      const key = el.getAttribute('data-t-placeholder');
      const translated = t(key);
      if (translated && translated !== key) {
        el.placeholder = translated;
      }
    });
  }

  // --- Language Switch ---
  function setLang(lang) {
    if (lang !== 'zh-CN' && lang !== 'en') return;
    _currentLang = lang;
    localStorage.setItem(LANG_KEY, lang);
    document.documentElement.lang = lang;
    if (_loaded) {
      _applyLang();
    }
    // else: init hasn't finished yet; init() will call _applyLang() when ready
  }

  function _applyLang() {
    updateDOM();
    // Broadcast to iframes
    document.querySelectorAll('iframe').forEach(f => {
      try { f.contentWindow.postMessage({ type: 'lang', lang: _currentLang }, '*'); } catch(e) {}
    });
    // Dispatch event for parent frame UI updates
    try { window.dispatchEvent(new CustomEvent('lang-applied', { detail: { lang: _currentLang } })); } catch(e) {}
  }

  function getLang() {
    return _currentLang;
  }

  // --- Load Resources ---
  async function loadLocale(lng) {
    try {
      const resp = await fetch('/static/locales/' + lng + '.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      _resources[lng] = await resp.json();
    } catch(e) {
      console.warn('i18n: failed to load', lng, e.message);
    }
  }

  // --- Init ---
  async function init() {
    _currentLang = detectLang();
    document.documentElement.lang = _currentLang;
    await Promise.all([loadLocale('zh-CN'), loadLocale('en')]);
    _loaded = true;
    _applyLang();
  }

  // --- iframe message listener ---
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'lang' && e.data.lang) {
      if (e.data.lang !== _currentLang) {
        _currentLang = e.data.lang;
        document.documentElement.lang = _currentLang;
        if (_loaded) updateDOM();
      }
    }
  });

  // --- Public API ---
  window._t = t;
  window._switchLang = setLang;
  window._getLang = getLang;
  window._i18nUpdate = updateDOM;
  window._i18nLoaded = function() { return _loaded; };

  // --- Auto-init ---
  init();
})();
