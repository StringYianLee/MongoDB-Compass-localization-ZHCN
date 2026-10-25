/*!
 * MongoDB Compass 简体中文语言包 - 主进程菜单钩子
 * 由 CompassZhCn 工具注入到主进程 chunk 顶部，仅包装 Electron Menu，
 * 不改变任何业务逻辑；加载失败时静默退出，不影响 Compass 启动。
 */
'use strict';

try {
  const { Menu } = require('electron');
  const fs = require('fs');
  const path = require('path');

  const dictPath = path.join(__dirname, 'menu-zh-CN.json');
  const dict = JSON.parse(fs.readFileSync(dictPath, 'utf8'));

  const strip = (s) => s.replace(/&/g, '');
  const translate = (label) => {
    if (typeof label !== 'string') return label;
    const key = strip(label).trim();
    if (!Object.prototype.hasOwnProperty.call(dict, key)) return label;
    return (label.startsWith('&') ? '&' : '') + dict[key];
  };

  const walk = (items) => {
    if (!Array.isArray(items)) return;
    for (const item of items) {
      if (!item) continue;
      if (typeof item.label === 'string') item.label = translate(item.label);
      if (Array.isArray(item.submenu)) walk(item.submenu);
      else if (item.submenu && Array.isArray(item.submenu.items)) walk(item.submenu.items);
    }
  };

  if (typeof Menu.buildFromTemplate === 'function') {
    const originalBuild = Menu.buildFromTemplate;
    Menu.buildFromTemplate = function (template) {
      walk(template);
      return originalBuild.call(this, template);
    };
  }

  if (typeof Menu.setApplicationMenu === 'function') {
    const originalSet = Menu.setApplicationMenu;
    Menu.setApplicationMenu = function (menu) {
      if (menu && Array.isArray(menu.items)) walk(menu.items);
      return originalSet.call(this, menu);
    };
  }
} catch (e) {
  /* 菜单汉化失败不应影响 Compass 启动 */
}
