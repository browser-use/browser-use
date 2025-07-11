"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = replaceShorthandObjectMethod;
var util = require("./util.js");
function replaceShorthandObjectMethod(path) {
  const t = util.getTypes();
  if (!path.node || !t.isFunction(path.node)) {
    throw new Error("replaceShorthandObjectMethod can only be called on Function AST node paths.");
  }
  if (!t.isObjectMethod(path.node)) {
    return path;
  }
  if (!path.node.generator) {
    return path;
  }
  const parameters = path.node.params.map(function (param) {
    return t.cloneDeep(param);
  });
  const functionExpression = t.functionExpression(null, parameters, t.cloneDeep(path.node.body), path.node.generator, path.node.async);
  util.replaceWithOrRemove(path, t.objectProperty(t.cloneDeep(path.node.key), functionExpression, path.node.computed, false));
  return path.get("value");
}

//# sourceMappingURL=replaceShorthandObjectMethod.js.map
