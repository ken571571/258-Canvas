// <ui-nav-btn> — 侧边栏导航按钮 Web Component (Light DOM)
// 用法: <ui-nav-btn icon="sparkle" page="generate" label="nav.generate" fallback="API生图"></ui-nav-btn>
// 自动生成标准 .nav-btn 按钮结构，内部集成 <ui-icon> + i18n data-t
// Light DOM 确保全局 CSS (.nav-btn, .nav-label 等) 正常生效

class UINavBtn extends HTMLElement {
  connectedCallback() {
    if (this._rendered) return;
    this._rendered = true;

    const icon = this.getAttribute('icon') || '';
    const page = this.getAttribute('page') || '';
    const label = this.getAttribute('label') || '';
    const fallback = this.getAttribute('fallback') || label;
    const title = this.getAttribute('title') || '';
    const isLogo = this.hasAttribute('logo');
    const hidden = this.hasAttribute('hidden-initially');

    const cls = isLogo ? 'sidebar-logo-btn' : 'nav-btn';
    const iconSize = isLogo ? '20' : '20';

    this.innerHTML = '' +
      '<button class="' + cls + '" data-page="' + page + '"' +
      ' onclick="navTo(\'' + page + '\', this)"' +
      (title ? ' title="' + title + '"' : '') +
      (hidden ? ' style="display:none"' : '') + '>' +
      '<ui-icon name="' + icon + '" size="' + iconSize + '"></ui-icon>' +
      '<span class="nav-label" data-t="' + label + '">' + fallback + '</span>' +
      '</button>';
  }
}
customElements.define('ui-nav-btn', UINavBtn);
