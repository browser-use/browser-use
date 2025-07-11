"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.hoist = hoist;
var util = require("./util.js");
const hasOwn = Object.prototype.hasOwnProperty;
function hoist(funPath) {
  const t = util.getTypes();
  t.assertFunction(funPath.node);
  const vars = {};
  function varDeclToExpr({
    node: vdec,
    scope
  }, includeIdentifiers) {
    t.assertVariableDeclaration(vdec);
    const exprs = [];
    vdec.declarations.forEach(function (dec) {
      vars[dec.id.name] = t.identifier(dec.id.name);
      scope.removeBinding(dec.id.name);
      if (dec.init) {
        exprs.push(t.assignmentExpression("=", dec.id, dec.init));
      } else if (includeIdentifiers) {
        exprs.push(dec.id);
      }
    });
    if (exprs.length === 0) return null;
    if (exprs.length === 1) return exprs[0];
    return t.sequenceExpression(exprs);
  }
  funPath.get("body").traverse({
    VariableDeclaration: {
      exit: function (path) {
        const expr = varDeclToExpr(path, false);
        if (expr === null) {
          path.remove();
        } else {
          util.replaceWithOrRemove(path, t.expressionStatement(expr));
        }
        path.skip();
      }
    },
    ForStatement: function (path) {
      const init = path.get("init");
      if (init.isVariableDeclaration()) {
        util.replaceWithOrRemove(init, varDeclToExpr(init, false));
      }
    },
    ForXStatement: function (path) {
      const left = path.get("left");
      if (left.isVariableDeclaration()) {
        util.replaceWithOrRemove(left, varDeclToExpr(left, true));
      }
    },
    FunctionDeclaration: function (path) {
      const node = path.node;
      vars[node.id.name] = node.id;
      const assignment = t.expressionStatement(t.assignmentExpression("=", t.clone(node.id), t.functionExpression(path.scope.generateUidIdentifierBasedOnNode(node), node.params, node.body, node.generator, node.expression)));
      if (path.parentPath.isBlockStatement()) {
        path.parentPath.unshiftContainer("body", assignment);
        path.remove();
      } else {
        util.replaceWithOrRemove(path, assignment);
      }
      path.scope.removeBinding(node.id.name);
      path.skip();
    },
    FunctionExpression: function (path) {
      path.skip();
    },
    ArrowFunctionExpression: function (path) {
      path.skip();
    }
  });
  const paramNames = {};
  funPath.get("params").forEach(function (paramPath) {
    const param = paramPath.node;
    if (t.isIdentifier(param)) {
      paramNames[param.name] = param;
    } else {}
  });
  const declarations = [];
  Object.keys(vars).forEach(function (name) {
    if (!hasOwn.call(paramNames, name)) {
      declarations.push(t.variableDeclarator(vars[name], null));
    }
  });
  return declarations;
}

//# sourceMappingURL=hoist.js.map
