// 通用 DOM 翻译引擎 — 自动翻译页面上所有中文文本
// 加载后，语言切换时自动扫描 DOM 中所有文本节点，查找并翻译已知的中文字符串
// 原理：利用 _tt_helper.js 的映射表，遍历所有文本节点，替换匹配的中文文本

(function() {
  'use strict';

  // 中文文本 → 翻译后文本 的缓存
  var _transCache = {};

  // 翻译单个文本节点
  function translateTextNode(node) {
    var text = node.textContent;
    if (!text || !text.trim()) return;
    // 检查是否包含中文
    if (!/[一-鿿]/.test(text)) return;

    // 先检查缓存
    if (_transCache.hasOwnProperty(text)) {
      if (_transCache[text] !== text) {
        node.textContent = _transCache[text];
      }
      return;
    }

    // 尝试用 _tt 翻译
    if (typeof _tt === 'function') {
      var translated = _tt(text);
      if (translated !== text) {
        _transCache[text] = translated;
        node.textContent = translated;
        return;
      }
    }

    // 尝试用 _t 通过 key 查找（text 本身就是 key 的情况，如 "nav.about"）
    if (typeof _t === 'function') {
      var t2 = _t(text, text);
      if (t2 !== text) {
        _transCache[text] = t2;
        node.textContent = t2;
        return;
      }
    }

    _transCache[text] = text; // 标记为已处理（无法翻译）
  }

  // 遍历 DOM 树中所有文本节点
  function walkTextNodes(root) {
    var walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function(node) {
          // 跳过 <script> 和 <style> 中的文本
          var parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          var tag = parent.tagName;
          if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') {
            return NodeFilter.FILTER_REJECT;
          }
          // 跳过已经是 data-t 元素的子节点（它们由 updateDOM 处理）
          if (parent.hasAttribute && parent.hasAttribute('data-t')) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    var node;
    while ((node = walker.nextNode())) {
      translateTextNode(node);
    }
  }

  // 翻译整个页面
  function translatePage() {
    _transCache = {}; // 清缓存（语言已切换）
    walkTextNodes(document.body);
    // 也翻译 title
    var title = document.querySelector('title');
    if (title && title.textContent && /[一-鿿]/.test(title.textContent)) {
      if (typeof _tt === 'function') {
        var t = _tt(title.textContent);
        if (t !== title.textContent) title.textContent = t;
      }
    }
  }

  // 暴露为全局函数
  window._translatePage = translatePage;

  // 语言切换时自动翻译
  window.addEventListener('lang-applied', function() {
    translatePage();
  });

  // 初始翻译（等待资源加载）
  (function retry() {
    if (typeof _i18nLoaded === 'function' && _i18nLoaded()) {
      translatePage();
    } else {
      setTimeout(retry, 100);
    }
  })();
})();
