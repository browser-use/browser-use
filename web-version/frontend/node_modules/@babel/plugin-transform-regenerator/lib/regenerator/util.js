"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.getTypes = getTypes;
exports.isReference = isReference;
exports.newHelpersAvailable = void 0;
exports.replaceWithOrRemove = replaceWithOrRemove;
exports.runtimeProperty = void 0;
exports.wrapWithTypes = wrapWithTypes;
let currentTypes = null;
function wrapWithTypes(types, fn) {
  return function (...args) {
    const oldTypes = currentTypes;
    currentTypes = types;
    try {
      return fn.apply(this, args);
    } finally {
      currentTypes = oldTypes;
    }
  };
}
function getTypes() {
  return currentTypes;
}
let newHelpersAvailable = exports.newHelpersAvailable = void 0;
{
  exports.newHelpersAvailable = newHelpersAvailable = file => {
    ;
    return file.availableHelper("regenerator") && !getTypes().isIdentifier(file.addHelper("regenerator"), {
      name: "__interal_marker_fallback_regenerator__"
    });
  };
}
let runtimeProperty = exports.runtimeProperty = void 0;
{
  exports.runtimeProperty = runtimeProperty = function (file, name) {
    const t = getTypes();
    const helper = file.addHelper("regeneratorRuntime");
    return t.memberExpression(t.isArrowFunctionExpression(helper) && t.isIdentifier(helper.body) ? helper.body : t.callExpression(helper, []), t.identifier(name), false);
  };
}
function isReference(path) {
  return path.isReferenced() || path.parentPath.isAssignmentExpression({
    left: path.node
  });
}
function replaceWithOrRemove(path, replacement) {
  if (replacement) {
    path.replaceWith(replacement);
  } else {
    path.remove();
  }
}

//# sourceMappingURL=util.js.map
