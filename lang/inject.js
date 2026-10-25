/*!
 * MongoDB Compass 简体中文语言包 - 渲染层注入引擎
 * 由 CompassZhCn 工具在构建时填充词典、规则与元信息。
 *
 * 设计原则:
 *  1. 只改「界面文案」，绝不改动代码编辑器、输入框内容与可编辑文档；
 *  2. 精确匹配 + 动态文本规则，命中才替换，未命中保持英文原文；
 *  3. MutationObserver 跟随 React 重渲染，避免被框架重置为英文；
 *  4. 不触碰 data-testid / class / 事件，因此不会影响 Compass 的自动化测试与业务逻辑。
 */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : null;
  if (!root || root.__COMPASS_ZH_CN__) return;

  var META = __META__;
  var DICT = __DICT__;
  var RULES = __RULES__;
  var ATTRS = ['placeholder', 'title', 'aria-label', 'aria-description', 'aria-placeholder', 'data-tooltip', 'alt'];

  // 这些标签内部是代码/用户输入，永远不翻译（INPUT/TEXTAREA 只翻译属性，见 walk）
  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, CODE: 1, PRE: 1, KBD: 1, SAMP: 1,
    OPTION: 1, SVG: 1, CANVAS: 1, IFRAME: 1,
    OBJECT: 1, VIDEO: 1, AUDIO: 1
  };

  // 代码编辑器、文档编辑区、用户数据表格：整块跳过
  var SKIP_SELECTOR = [
    '[contenteditable="true"]',
    '.monaco-editor',
    '.ace_editor',
    '.CodeMirror',
    '[data-testid="editable-document"]',
    '[data-testid="document-list"]',
    '[data-testid="documents-table"]',
    '[data-testid*="json-view"]',
    '[data-testid*="code-editor"]',
    '[data-testid*="query-bar"]',
    '[data-testid*="export-modal"] textarea'
  ].join(',');

  var LOWER = Object.create(null);
  for (var k in DICT) {
    if (!Object.prototype.hasOwnProperty.call(DICT, k)) continue;
    var lk = k.toLowerCase();
    // 仅当小写键唯一时才启用大小写不敏感回退，避免歧义
    if (LOWER[lk] === undefined) LOWER[lk] = DICT[k];
    else if (LOWER[lk] !== DICT[k]) LOWER[lk] = null;
  }

  var COMPILED = [];
  for (var i = 0; i < RULES.length; i++) {
    try { COMPILED.push([new RegExp(RULES[i][0]), RULES[i][1]]); } catch (e) { /* ignore */ }
  }

  var ATTR_MAP = Object.create(null);
  for (var a = 0; a < ATTRS.length; a++) ATTR_MAP[ATTRS[a]] = 1;

  function skipped(el) {
    if (!el) return true;
    if (el.closest && el.closest(SKIP_SELECTOR)) return true;
    var node = el;
    var depth = 0;
    while (node && node.nodeType === 1 && depth < 40) {
      if (SKIP_TAGS[node.tagName]) return true;
      if (node.isContentEditable) return true;
      if (node.getAttribute && node.getAttribute('data-compass-zh-skip') === '1') return true;
      node = node.parentElement;
      depth++;
    }
    return false;
  }

  function lookup(text) {
    if (DICT[text] !== undefined) return DICT[text];
    var low = text.toLowerCase();
    var hit = LOWER[low];
    if (hit) return hit;
    for (var j = 0; j < COMPILED.length; j++) {
      if (COMPILED[j][0].test(text)) return text.replace(COMPILED[j][0], COMPILED[j][1]);
    }
    // 表单标签常带冒号："Filter:" -> "筛选："；只回退一次，避免递归
    var m = /^(.{1,120}?)([:：])\s*$/.exec(text);
    if (m) {
      var base = m[1];
      var baseHit = DICT[base] !== undefined ? DICT[base] : LOWER[base.toLowerCase()];
      if (baseHit) return baseHit + '：';
    }
    return null;
  }

  function translateValue(raw) {
    if (!raw) return null;
    var t = raw.trim();
    if (t.length < 2 || t.length > 160) return null;
    // 纯数字/纯符号不处理
    if (!/[A-Za-z\u4e00-\u9fa5]/.test(t)) return null;
    // 已经包含中文则视为已翻译
    if (/[\u4e00-\u9fa5]/.test(t) && !/[A-Za-z]{3,}/.test(t)) return null;
    var v = lookup(t);
    if (v === null || v === undefined || v === t) return null;
    var lead = raw.match(/^\s*/)[0];
    var trail = raw.match(/\s*$/)[0];
    return lead + v + trail;
  }

  function doText(node) {
    var parent = node.parentElement;
    if (!parent) return;
    if (parent.tagName === 'TEXTAREA' || parent.tagName === 'SELECT') return;
    if (skipped(parent)) return;
    var next = translateValue(node.nodeValue);
    if (next === null) return;
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  function doAttrs(el) {
    if (!el.getAttribute) return;
    if (skipped(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var name = ATTRS[i];
      var val = el.getAttribute(name);
      if (!val) continue;
      if (/[\u4e00-\u9fa5]/.test(val)) continue;
      var next = translateValue(val);
      if (next === null) continue;
      el.setAttribute(name, next.trim());
    }
  }

  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) { doText(node); return; }
    if (node.nodeType !== 1) return;
    if (SKIP_TAGS[node.tagName] || node.isContentEditable) return;
    if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA' || node.tagName === 'SELECT') {
      doAttrs(node);
      return;
    }
    doAttrs(node);
    var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: function (n) {
        if (n.nodeType === 1) {
          if (SKIP_TAGS[n.tagName] || n.isContentEditable) return NodeFilter.FILTER_REJECT;
          if (n.matches && n.matches(SKIP_SELECTOR)) return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var cur = walker.nextNode();
    while (cur) {
      if (cur.nodeType === 1) doAttrs(cur);
      else doText(cur);
      cur = walker.nextNode();
    }
  }

  var queue = [];
  var scheduled = false;

  function flush() {
    scheduled = false;
    var batch = queue;
    queue = [];
    for (var i = 0; i < batch.length; i++) {
      try { walk(batch[i]); } catch (e) { /* 单个节点失败不影响整体 */ }
    }
    try { translateTitle(); } catch (e) { /* ignore */ }
  }

  function enqueue(node) {
    queue.push(node);
    if (scheduled) return;
    scheduled = true;
    root.setTimeout(flush, 16);
  }

  function translateTitle() {
    var current = document.title;
    if (!current) return;
    var next = translateValue(current);
    if (next !== null && next.trim() !== current) {
      document.title = next.trim();
    }
  }

  function applyAll() {
    if (!document.body) return;
    walk(document.body);
    translateTitle();
  }

  var observer = null;

  function start() {
    applyAll();
    observer = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var r = records[i];
        if (r.type === 'childList') {
          for (var j = 0; j < r.addedNodes.length; j++) {
            var n = r.addedNodes[j];
            if (n.nodeType === 1 || n.nodeType === 3) enqueue(n);
          }
        } else if (r.type === 'characterData') {
          enqueue(r.target);
        } else if (r.type === 'attributes') {
          enqueue(r.target);
        }
      }
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRS
    });
  }

  root.__COMPASS_ZH_CN__ = {
    version: META.version,
    entries: META.entries,
    applied: 0,
    rescan: applyAll,
    stop: function () { if (observer) observer.disconnect(); observer = null; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
