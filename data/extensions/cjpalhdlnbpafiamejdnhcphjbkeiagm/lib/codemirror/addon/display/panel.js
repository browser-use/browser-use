// CodeMirror, copyright (c) by Marijn Haverbeke and others
// Distributed under an MIT license: https://codemirror.net/LICENSE

(function (mod) {
  if (typeof exports == "object" && typeof module == "object") // CommonJS
    mod(require("../../lib/codemirror"));
  else if (typeof define == "function" && define.amd) // AMD
    define(["../../lib/codemirror"], mod);
  else // Plain browser env
    mod(CodeMirror);
})(function (CodeMirror) {
  CodeMirror.defineExtension("addPanel", function (node, options) {
    options = options || {};

    if (!this.state.panels) initPanels(this);

    var info = this.state.panels;
    var wrapper = info.wrapper;
    var cmWrapper = this.getWrapperElement();
    var replace = options.replace instanceof Panel && !options.replace.cleared;

    if (options.after instanceof Panel && !options.after.cleared) {
      wrapper.insertBefore(node, options.before.node.nextSibling);
    } else if (options.before instanceof Panel && !options.before.cleared) {
      wrapper.insertBefore(node, options.before.node);
    } else if (replace) {
      wrapper.insertBefore(node, options.replace.node);
      options.replace.clear(true);
    } else if (options.position == "bottom") {
      wrapper.appendChild(node);
    } else if (options.position == "before-bottom") {
      wrapper.insertBefore(node, cmWrapper.nextSibling);
    } else if (options.position == "after-top") {
      wrapper.insertBefore(node, cmWrapper);
    } else {
      wrapper.insertBefore(node, wrapper.firstChild);
    }

    var height = (options && options.height) || node.offsetHeight;

    var panel = new Panel(this, node, options, height);
    info.panels.push(panel);

    this.setSize();
    if (options.stable && isAtTop(this, node))
      this.scrollTo(null, this.getScrollInfo().top + height);

    return panel;
  });

  function Panel(cm, node, options, height) {
    this.cm = cm;
    this.node = node;
    this.options = options;
    this.height = height;
    this.cleared = false;
  }

  /* when skipRemove is true, clear() was called from addPanel().
   * Thus removePanels() should not be called (issue 5518) */
  Panel.prototype.clear = function (skipRemove) {
    if (this.cleared) return;
    this.cleared = true;
    var info = this.cm.state.panels;
    info.panels.splice(info.panels.indexOf(this), 1);
    this.cm.setSize();
    if (this.options.stable && isAtTop(this.cm, this.node))
      this.cm.scrollTo(null, this.cm.getScrollInfo().top - this.height)
    info.wrapper.removeChild(this.node);
    if (info.panels.length == 0 && !skipRemove) removePanels(this.cm);
  };

  Panel.prototype.changed = function () {
    this.height = this.node.getBoundingClientRect().height;
    this.cm.setSize();
  };

  function initPanels(cm) {
    var wrap = cm.getWrapperElement()
    var style = window.getComputedStyle ? window.getComputedStyle(wrap) : wrap.currentStyle;
    var height = parseInt(style.height);
    var info = cm.state.panels = {
      setHeight: wrap.style.height,
      panels: [],
      wrapper: document.createElement("div")
    };
    var hasFocus = cm.hasFocus(), scrollPos = cm.getScrollInfo()
    wrap.parentNode.insertBefore(info.wrapper, wrap);
    info.wrapper.appendChild(wrap);
    cm.scrollTo(scrollPos.left, scrollPos.top)
    if (hasFocus) cm.focus();

    cm._setSize = cm.setSize;
    if (height != null) cm.setSize = function (width, newHeight) {
      if (!newHeight) newHeight = info.wrapper.offsetHeight;
      info.setHeight = newHeight;
      if (typeof newHeight != "number") {
        var px = /^(\d+\.?\d*)px$/.exec(newHeight);
        if (px) {
          newHeight = Number(px[1]);
        } else {
          info.wrapper.style.height = newHeight;
          newHeight = info.wrapper.offsetHeight;
        }
      }
      var editorheight = newHeight - info.panels
        .map(function (p) { return p.node.getBoundingClientRect().height; })
        .reduce(function (a, b) { return a + b; }, 0);
      cm._setSize(width, editorheight);
      height = newHeight;
    };
  }

  function removePanels(cm) {
    var info = cm.state.panels;
    cm.state.panels = null;

    var wrap = cm.getWrapperElement()
    var hasFocus = cm.hasFocus(), scrollPos = cm.getScrollInfo()
    info.wrapper.parentNode.replaceChild(wrap, info.wrapper);
    cm.scrollTo(scrollPos.left, scrollPos.top)
    if (hasFocus) cm.focus();
    wrap.style.height = info.setHeight;
    cm.setSize = cm._setSize;
    cm.setSize();
  }

  function isAtTop(cm, dom) {
    for (var sibling = dom.nextSibling; sibling; sibling = sibling.nextSibling)
      if (sibling == cm.getWrapperElement()) return true
    return false
  }
});
