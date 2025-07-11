"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.getVisitor = void 0;
var _assert = require("assert");
var _hoist = require("./hoist.js");
var _emit = require("./emit.js");
var _replaceShorthandObjectMethod = require("./replaceShorthandObjectMethod.js");
var util = require("./util.js");
const getVisitor = t => ({
  Method(path, state) {
    const node = path.node;
    if (!shouldRegenerate(node, state)) return;
    const container = t.functionExpression(null, [], t.cloneNode(node.body, false), node.generator, node.async);
    path.get("body").set("body", [t.returnStatement(t.callExpression(container, []))]);
    node.async = false;
    node.generator = false;
    path.get("body.body.0.argument.callee").unwrapFunctionEnvironment();
  },
  Function: {
    exit: util.wrapWithTypes(t, function (path, state) {
      let node = path.node;
      if (!shouldRegenerate(node, state)) return;
      path = (0, _replaceShorthandObjectMethod.default)(path);
      node = path.node;
      const contextId = path.scope.generateUidIdentifier("context");
      const argsId = path.scope.generateUidIdentifier("args");
      path.ensureBlock();
      const bodyBlockPath = path.get("body");
      if (node.async) {
        bodyBlockPath.traverse(awaitVisitor, this);
      }
      bodyBlockPath.traverse(functionSentVisitor, {
        context: contextId,
        pluginPass: this
      });
      const outerBody = [];
      const innerBody = [];
      bodyBlockPath.get("body").forEach(function (childPath) {
        const node = childPath.node;
        if (t.isExpressionStatement(node) && t.isStringLiteral(node.expression)) {
          outerBody.push(node);
        } else if ((node == null ? void 0 : node._blockHoist) != null) {
          outerBody.push(node);
        } else {
          innerBody.push(node);
        }
      });
      if (outerBody.length > 0) {
        bodyBlockPath.node.body = innerBody;
      }
      const outerFnExpr = getOuterFnExpr(this, path);
      t.assertIdentifier(node.id);
      const vars = (0, _hoist.hoist)(path);
      const context = {
        usesThis: false,
        usesArguments: false,
        getArgsId: () => t.clone(argsId)
      };
      path.traverse(argumentsThisVisitor, context);
      if (context.usesArguments) {
        vars.push(t.variableDeclarator(t.clone(argsId), t.identifier("arguments")));
      }
      const emitter = new _emit.Emitter(contextId, path.scope, vars, this);
      emitter.explode(path.get("body"));
      if (vars.length > 0) {
        outerBody.push(t.variableDeclaration("var", vars));
      }
      const wrapArgs = [emitter.getContextFunction()];
      const tryLocsList = emitter.getTryLocsList();
      if (node.generator) {
        wrapArgs.push(outerFnExpr);
      } else if (context.usesThis || tryLocsList || node.async) {
        wrapArgs.push(t.nullLiteral());
      }
      if (context.usesThis) {
        wrapArgs.push(t.thisExpression());
      } else if (tryLocsList || node.async) {
        wrapArgs.push(t.nullLiteral());
      }
      if (tryLocsList) {
        wrapArgs.push(tryLocsList);
      } else if (node.async) {
        wrapArgs.push(t.nullLiteral());
      }
      if (node.async) {
        let currentScope = path.scope;
        do {
          if (currentScope.hasOwnBinding("Promise")) currentScope.rename("Promise");
        } while (currentScope = currentScope.parent);
        wrapArgs.push(t.identifier("Promise"));
      }
      const wrapCall = t.callExpression(util.newHelpersAvailable(this) ? !node.async ? t.memberExpression(t.callExpression(this.addHelper("regenerator"), []), t.identifier("w")) : node.generator ? this.addHelper("regeneratorAsyncGen") : this.addHelper("regeneratorAsync") : util.runtimeProperty(this, node.async ? "async" : "wrap"), wrapArgs);
      outerBody.push(t.returnStatement(wrapCall));
      node.body = t.blockStatement(outerBody);
      path.get("body.body").forEach(p => p.scope.registerDeclaration(p));
      const oldDirectives = bodyBlockPath.node.directives;
      if (oldDirectives) {
        node.body.directives = oldDirectives;
      }
      const wasGeneratorFunction = node.generator;
      if (wasGeneratorFunction) {
        node.generator = false;
      }
      if (node.async) {
        node.async = false;
      }
      if (wasGeneratorFunction && t.isExpression(node)) {
        util.replaceWithOrRemove(path, t.callExpression(util.newHelpersAvailable(this) ? t.memberExpression(t.callExpression(this.addHelper("regenerator"), []), t.identifier("m")) : util.runtimeProperty(this, "mark"), [node]));
        path.addComment("leading", "#__PURE__");
      }
      const insertedLocs = emitter.getInsertedLocs();
      path.traverse({
        NumericLiteral(path) {
          if (!insertedLocs.has(path.node)) {
            return;
          }
          path.replaceWith(t.numericLiteral(path.node.value));
        }
      });
      path.requeue();
    })
  }
});
exports.getVisitor = getVisitor;
function shouldRegenerate(node, state) {
  if (node.generator) {
    if (node.async) {
      return state.opts.asyncGenerators !== false;
    } else {
      return state.opts.generators !== false;
    }
  } else if (node.async) {
    return state.opts.async !== false;
  } else {
    return false;
  }
}
function getOuterFnExpr(state, funPath) {
  const t = util.getTypes();
  const node = funPath.node;
  t.assertFunction(node);
  if (!node.id) {
    node.id = funPath.scope.parent.generateUidIdentifier("callee");
  }
  if (node.generator && t.isFunctionDeclaration(node)) {
    return getMarkedFunctionId(state, funPath);
  }
  return t.clone(node.id);
}
const markInfo = new WeakMap();
function getMarkInfo(node) {
  if (!markInfo.has(node)) {
    markInfo.set(node, {});
  }
  return markInfo.get(node);
}
function getMarkedFunctionId(state, funPath) {
  const t = util.getTypes();
  const node = funPath.node;
  t.assertIdentifier(node.id);
  const blockPath = funPath.findParent(function (path) {
    return path.isProgram() || path.isBlockStatement();
  });
  if (!blockPath) {
    return node.id;
  }
  const block = blockPath.node;
  _assert.ok(Array.isArray(block.body));
  const info = getMarkInfo(block);
  if (!info.decl) {
    info.decl = t.variableDeclaration("var", []);
    blockPath.unshiftContainer("body", info.decl);
    info.declPath = blockPath.get("body.0");
  }
  _assert.strictEqual(info.declPath.node, info.decl);
  const markedId = blockPath.scope.generateUidIdentifier("marked");
  const markCallExp = t.callExpression(util.newHelpersAvailable(state) ? t.memberExpression(t.callExpression(state.addHelper("regenerator"), []), t.identifier("m")) : util.runtimeProperty(state, "mark"), [t.clone(node.id)]);
  const index = info.decl.declarations.push(t.variableDeclarator(markedId, markCallExp)) - 1;
  const markCallExpPath = info.declPath.get("declarations." + index + ".init");
  _assert.strictEqual(markCallExpPath.node, markCallExp);
  markCallExpPath.addComment("leading", "#__PURE__");
  return t.clone(markedId);
}
const argumentsThisVisitor = {
  "FunctionExpression|FunctionDeclaration|Method": function (path) {
    path.skip();
  },
  Identifier: function (path, state) {
    if (path.node.name === "arguments" && util.isReference(path)) {
      util.replaceWithOrRemove(path, state.getArgsId());
      state.usesArguments = true;
    }
  },
  ThisExpression: function (path, state) {
    state.usesThis = true;
  }
};
const functionSentVisitor = {
  MetaProperty(path, state) {
    const {
      node
    } = path;
    if (node.meta.name === "function" && node.property.name === "sent") {
      const t = util.getTypes();
      util.replaceWithOrRemove(path, t.memberExpression(t.clone(this.context), t.identifier(util.newHelpersAvailable(state.pluginPass) ? "v" : "_sent")));
    }
  }
};
const awaitVisitor = {
  Function: function (path) {
    path.skip();
  },
  AwaitExpression: function (path) {
    const t = util.getTypes();
    const argument = path.node.argument;
    const helper = util.newHelpersAvailable(this) ? this.addHelper("awaitAsyncGenerator") : util.runtimeProperty(this, "awrap");
    util.replaceWithOrRemove(path, t.yieldExpression(t.callExpression(helper, [argument]), false));
  }
};

//# sourceMappingURL=visit.js.map
