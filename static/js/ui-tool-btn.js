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

    this.innerHTML = '' +
      '<button class="tool-btn"' + (action ? ' onclick="' + action + '"' : '') + '>' +
      '<ui-icon name="' + icon + '" size="14"></ui-icon>' +
      (label ? '<span data-t="' + label + '">' + fallback + '</span>' : '') +
      '</button>';
  }
}
customElements.define('ui-tool-btn', UIToolBtn);
