// <ui-tool-btn> — 画布工具栏按钮 Web Component (Light DOM)
// 用法: <ui-tool-btn icon="image" label="toolbar.image" fallback="图片" action="createNode('image')"></ui-tool-btn>
// 用法: <ui-tool-btn divider></ui-tool-btn>  — 分隔线
// 自动生成标准 .tool-btn 按钮结构，内部集成 <ui-icon> + i18n data-t
// Light DOM 确保全局 CSS (.tool-btn, .toolbar-divider 等) 正常生效

class UIToolBtn extends HTMLElement {
  connectedCallback() {
    if (this._rendered) return;
    this._rendered = true;

    // Divider mode
    if (this.hasAttribute('divider')) {
      this.innerHTML = '<div class="toolbar-divider"></div>';
      return;
    }

    const icon = this.getAttribute('icon') || '';
    const label = this.getAttribute('label') || '';
    const fallback = this.getAttribute('fallback') || label;
    const action = this.getAttribute('action') || '';

    // action 包含 JS 代码，通过 addEventListener 绑定（避免 setAttribute('onclick') 不编译的问题）
    const btn = document.createElement('button');
    btn.className = 'tool-btn';
    var actionMap = {
        "createNode('image')":    function() { window._canvas.createNode('image'); },
        "createNode('prompt')":   function() { window._canvas.createNode('prompt'); },
        "createNode('image_gen')": function() { window._canvas.createNode('image_gen'); },
        "createNode('video_gen')": function() { window._canvas.createNode('video_gen'); },
        "createNode('agent')":    function() { window._canvas.createNode('agent'); },
        "createNode('loop')":     function() { window._canvas.createNode('loop'); },
        "createNode('output')":   function() { window._canvas.createNode('output'); },
        "createNode('comfy')":    function() { window._canvas.createNode('comfy'); },
        "saveCanvas()":           function() { window._canvas.save(); },
        "engine._toggleAssetPanel()": function() { window._canvas._toggleAssetPanel(); },
    };
    if (action) {
        var handler = actionMap[action];
        if (handler) {
            btn.addEventListener('click', handler);
        } else {
            console.error('ui-tool-btn: unknown action "' + action + '"');
        }
    }
    // icon
    const iconEl = document.createElement('ui-icon');
    iconEl.setAttribute('name', icon);
    iconEl.setAttribute('size', '14');
    btn.appendChild(iconEl);
    // label
    if (label) {
      const span = document.createElement('span');
      span.setAttribute('data-t', label);
      span.textContent = fallback;
      btn.appendChild(span);
    }
    this.appendChild(btn);
  }
}
customElements.define('ui-tool-btn', UIToolBtn);
