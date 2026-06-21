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

    // 使用 DOM API 构建，避免字符串拼接 XSS
    const btn = document.createElement('button');
    btn.className = cls;
    btn.setAttribute('data-page', page);
    btn.onclick = function() { navTo(page, this); };
    if (title) btn.setAttribute('title', title);
    if (hidden) btn.style.display = 'none';

    const iconEl = document.createElement('ui-icon');
    iconEl.setAttribute('name', icon);
    iconEl.setAttribute('size', iconSize);
    btn.appendChild(iconEl);

    const span = document.createElement('span');
    span.className = 'nav-label';
    span.setAttribute('data-t', label);
    span.textContent = fallback;
    btn.appendChild(span);

    this.appendChild(btn);
  }
}
customElements.define('ui-nav-btn', UINavBtn);
