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
  let _langFromParent = false;  // 父窗口是否在 init 完成前已指定语言

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
    // Broadcast to iframes（限制目标源为同源，防止信息泄露）
    const targetOrigin = location.origin;
    document.querySelectorAll('iframe').forEach(f => {
      try { f.contentWindow.postMessage({ type: 'lang', lang: _currentLang }, targetOrigin); } catch(e) {}
    });
    // Dispatch event for parent frame UI updates
    try { window.dispatchEvent(new CustomEvent('lang-applied', { detail: { lang: _currentLang } })); } catch(e) {}
    // 通知所有组件重新渲染（画布节点/菜单等动态内容需重新调用 _t()）
    try { window.dispatchEvent(new CustomEvent('lang-changed', { detail: { lang: _currentLang } })); } catch(e) {}
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
    // 如果父窗口已在 init 完成前通过 postMessage 指定了语言，保留父窗口的选择
    if (!_langFromParent) {
      _currentLang = detectLang();
    }
    document.documentElement.lang = _currentLang;
    await Promise.all([loadLocale('zh-CN'), loadLocale('en')]);
    _loaded = true;
    _applyLang();
  }

  // --- iframe message listener（仅接受同源消息）---
  window.addEventListener('message', function(e) {
    // 验证消息来源，拒绝非同源消息
    if (e.origin !== location.origin) return;
    if (e.data && e.data.type === 'lang' && e.data.lang) {
      if (e.data.lang !== _currentLang) {
        _currentLang = e.data.lang;
        document.documentElement.lang = _currentLang;
        if (_loaded) {
          updateDOM();
          // Also dispatch lang-applied so page-level listeners can refresh JS text
          try { window.dispatchEvent(new CustomEvent('lang-applied', { detail: { lang: _currentLang } })); } catch(ex) {}
        } else {
          // init 尚未完成，记住父窗口已指定语言，防止 detectLang() 覆盖
          _langFromParent = true;
        }
      }
    }
  });

  // --- _tt() 兼容函数：中文文本 → 翻译 ---
  // 用于 JS 动态文本（右键菜单、节点状态徽章等），映射中文到 locale key
  function tt(chineseText) {
    const map = {
      '图片节点': 'nodeType.image',
      '提示词节点': 'nodeType.prompt',
      '图片生成': 'nodeType.imageGen',
      '视频生成': 'nodeType.videoGen',
      'Agent 节点': 'nodeType.agent',
      '列队节点': 'nodeType.loop',
      '输出节点': 'nodeType.output',
      'ComfyUI 节点': 'nodeType.comfy',
      '运行中': 'nodeState.running',
      '成功': 'nodeState.success',
      '失败': 'nodeState.error',
      '选中操作': 'contextMenu.selection',
      '复制 Ctrl+C': 'contextMenu.copy',
      '粘贴 Ctrl+V': 'contextMenu.paste',
      '打组 Ctrl+G': 'contextMenu.group',
      '解组 Ctrl+Shift+G': 'contextMenu.ungroup',
      '删除 Delete': 'contextMenu.deleteSelected',
      '删除连线': 'contextMenu.deleteConnection',
      // 视频分辨率标签
      '9:16 竖版': 'videoRes.portrait_916',
      '16:9 横版': 'videoRes.landscape_169',
      '9:16 高清': 'videoRes.portrait_916_hd',
      '16:9 高清': 'videoRes.landscape_169_hd',
      '720P 横版': 'videoRes.landscape_720p',
      '720P 竖版': 'videoRes.portrait_720p',
      '720P 方形': 'videoRes.square_720p',
      '720P 4:3': 'videoRes.ratio_43_720p',
      '720P 3:4': 'videoRes.ratio_34_720p',
      '1080P 横版': 'videoRes.landscape_1080p',
      '1080P 竖版': 'videoRes.portrait_1080p',
      '1080P 方形': 'videoRes.square_1080p',
      '1080P 4:3': 'videoRes.ratio_43_1080p',
      '1080P 3:4': 'videoRes.ratio_34_1080p',
      '📎 自适应': 'videoRes.adaptive',
    };
    var key = map[chineseText];
    return key ? t(key) : chineseText;
  }

  // --- Public API ---
  window._t = t;
  window._tt = tt;
  window._switchLang = setLang;
  window._getLang = getLang;
  window._i18nUpdate = updateDOM;
  window._i18nLoaded = function() { return _loaded; };

  // --- Auto-init ---
  init();
})();
