"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.hasSideEffects = exports.containsLeap = void 0;
var _assert = require("assert");
var _util = require("./util.js");
const mMap = new WeakMap();
function m(node) {
  if (!mMap.has(node)) {
    mMap.set(node, {});
  }
  return mMap.get(node);
}
const hasOwn = Object.prototype.hasOwnProperty;
function makePredicate(propertyName, knownTypes) {
  function onlyChildren(node) {
    const t = (0, _util.getTypes)();
    t.assertNode(node);
    let result = false;
    function check(child) {
      if (result) {} else if (Array.isArray(child)) {
        child.some(check);
      } else if (t.isNode(child)) {
        _assert.strictEqual(result, false);
        result = predicate(child);
      }
      return result;
    }
    const keys = t.VISITOR_KEYS[node.type];
    if (keys) {
      for (let i = 0; i < keys.length; i++) {
        const key = keys[i];
        const child = node[key];
        check(child);
      }
    }
    return result;
  }
  function predicate(node) {
    (0, _util.getTypes)().assertNode(node);
    const meta = m(node);
    if (hasOwn.call(meta, propertyName)) return meta[propertyName];
    if (hasOwn.call(opaqueTypes, node.type)) return meta[propertyName] = false;
    if (hasOwn.call(knownTypes, node.type)) return meta[propertyName] = true;
    return meta[propertyName] = onlyChildren(node);
  }
  predicate.onlyChildren = onlyChildren;
  return predicate;
}
const opaqueTypes = {
  FunctionExpression: true,
  ArrowFunctionExpression: true
};
const sideEffectTypes = {
  CallExpression: true,
  ForInStatement: true,
  UnaryExpression: true,
  BinaryExpression: true,
  AssignmentExpression: true,
  UpdateExpression: true,
  NewExpression: true
};
const leapTypes = {
  YieldExpression: true,
  BreakStatement: true,
  ContinueStatement: true,
  ReturnStatement: true,
  ThrowStatement: true
};
for (const type in leapTypes) {
  if (hasOwn.call(leapTypes, type)) {
    sideEffectTypes[type] = leapTypes[type];
  }
}
const hasSideEffects = exports.hasSideEffects = makePredicate("hasSideEffects", sideEffectTypes);
const containsLeap = exports.containsLeap = makePredicate("containsLeap", leapTypes);

//# sourceMappingURL=meta.js.map
