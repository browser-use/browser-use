/**
 * WebMCP bridge for the agent
 *
 * Injected via Page.addScriptToEvaluateOnNewDocument so it runs before page
 * scripts. Provides the W3C navigator.modelContext API and captures tool
 * registrations so browser-use can discover and invoke them via CDP
 *
 * Spec: https://github.com/webmachinelearning/webmcp/blob/main/docs/proposal.md
 *
 * Exposed to browser-use:
 *   window.__buWebMCP.listTools()          -> JSON string of tool metadata
 *   window.__buWebMCP.callTool(name, json) -> JSON string of execute() result
 */
(function () {
  'use strict';

  // Tool registry: name -> { name, description, inputSchema, _execute }
  var tools = {};

  // API (called via CDP Runtime.evaluate)

  window.__buWebMCP = {
    version: 1,
    tools: tools,

    /** Return JSON metadata for all registered tools (no execute refs). */
    listTools: function () {
      var list = [];
      for (var name in tools) {
        var t = tools[name];
        list.push({
          name: t.name,
          description: t.description || '',
          inputSchema: t.inputSchema || {},
        });
      }
      return JSON.stringify({ tools: list });
    },

    /** Call a tool's execute callback. Returns a JSON string of the result. */
    callTool: function (toolName, argsJSON) {
      var tool = tools[toolName];
      if (!tool)
        return Promise.resolve(JSON.stringify({
          error: 'WebMCP tool "' + toolName + '" not found',
        }));

      var args;
      try {
        args = typeof argsJSON === 'string' ? JSON.parse(argsJSON) : argsJSON || {};
      } catch (e) {
        return Promise.resolve(JSON.stringify({ error: 'Invalid JSON args: ' + e.message }));
      }

      // The agent object passed as second arg to execute(), per the spec.
      var agent = {
        requestUserInteraction: function (fn) {
          return Promise.resolve().then(function () {
            return fn();
          });
        },
      };

      try {
        return Promise.resolve(tool._execute(args, agent)).then(function (r) {
          return JSON.stringify(r != null ? r : { content: [] });
        }).catch(function (err) {
          return JSON.stringify({ error: err.message || 'Tool execution failed' });
        });
      } catch (err) {
        // Catch synchronous throws before Promise.resolve runs
        return Promise.resolve(JSON.stringify({ error: err.message || 'Tool execution failed' }));
      }
    },
  };

  // navigator.modelContext implementation

  function createModelContext() {
    return {
      provideContext: function (ctx) {
        // provideContext clears all previous tools and registers new ones
        for (var k in tools) delete tools[k];
        var ts = (ctx && ctx.tools) || [];
        for (var i = 0; i < ts.length; i++) {
          var t = ts[i];
          tools[t.name] = {
            name: t.name,
            description: t.description || '',
            inputSchema: t.inputSchema || {},
            _execute: t.execute,
          };
        }
      },

      registerTool: function (tool) {
        tools[tool.name] = {
          name: tool.name,
          description: tool.description || '',
          inputSchema: tool.inputSchema || {},
          _execute: tool.execute,
        };
        return {
          unregister: function () {
            delete tools[tool.name];
          },
        };
      },

      unregisterTool: function (name) {
        delete tools[name];
      },
    };
  }

  /**
   * Hook an existing modelContext object (e.g. from a polyfill) by wrapping
   * its provideContext / registerTool / unregisterTool methods so we also
   * capture tool registrations in our registry
   */
  function hookModelContext(mc) {
    var origProvide = mc.provideContext
      ? mc.provideContext.bind(mc)
      : null;
    var origRegister = mc.registerTool
      ? mc.registerTool.bind(mc)
      : null;
    var origUnregister = mc.unregisterTool
      ? mc.unregisterTool.bind(mc)
      : null;

    if (origProvide) {
      mc.provideContext = function (ctx) {
        // Clear our registry then re-populate
        for (var k in tools) delete tools[k];
        var ts = (ctx && ctx.tools) || [];
        for (var i = 0; i < ts.length; i++) {
          var t = ts[i];
          tools[t.name] = {
            name: t.name,
            description: t.description || '',
            inputSchema: t.inputSchema || {},
            _execute: t.execute,
          };
        }
        return origProvide(ctx);
      };
    }

    if (origRegister) {
      mc.registerTool = function (tool) {
        tools[tool.name] = {
          name: tool.name,
          description: tool.description || '',
          inputSchema: tool.inputSchema || {},
          _execute: tool.execute,
        };
        var result = origRegister(tool);
        if (result && result.unregister) {
          var origUn = result.unregister;
          result.unregister = function () {
            delete tools[tool.name];
            return origUn();
          };
        }
        return result;
      };
    }

    if (origUnregister) {
      mc.unregisterTool = function (name) {
        delete tools[name];
        return origUnregister(name);
      };
    }
  }

  // Install navigator.modelContext

  if (navigator.modelContext) {
    // A polyfill or native implementation already exists — hook into it
    hookModelContext(navigator.modelContext);
  } else {
    // Provide our own implementation
    var _mc = createModelContext();

    try {
      Object.defineProperty(navigator, 'modelContext', {
        get: function () {
          return _mc;
        },
        set: function (val) {
          // A polyfill is replacing modelContext — hook into it and keep ours
          _mc = val;
          hookModelContext(_mc);
        },
        configurable: true,
        enumerable: true,
      });
    } catch (e) {
      // Fallback if defineProperty fails (shouldn't happen)
      navigator.modelContext = _mc;
    }
  }
})();
