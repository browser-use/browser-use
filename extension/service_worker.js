/**
 * Service Worker for Browser Use Extension Bridge
 * Generic JSON-RPC bridge for all chrome.* APIs
 */

// Logging utility
function log(...args) {
  console.log('[Browser Use Bridge]', ...args);
}

// Utility to get nested properties from a path like "tabs.query"
function getNestedProperty(obj, path) {
  return path.split('.').reduce((curr, prop) => curr?.[prop], obj);
}

// Utility to set nested properties
function setNestedProperty(obj, path, value) {
  const parts = path.split('.');
  const last = parts.pop();
  const target = parts.reduce((curr, prop) => {
    if (!curr[prop]) curr[prop] = {};
    return curr[prop];
  }, obj);
  target[last] = value;
}

// Convert chrome async APIs to promises
function promisifyChrome(path, method, args) {
  return new Promise((resolve, reject) => {
    // Handle special cases where last argument might be options object
    const lastArg = args[args.length - 1];
    const hasCallbackParam = typeof lastArg === 'function';
    
    // Add callback to args if not already present
    const callback = (...callbackArgs) => {
      if (chrome.runtime.lastError) {
        reject({
          error: chrome.runtime.lastError.message,
          chromeError: chrome.runtime.lastError
        });
      } else {
        // Return single value if only one callback arg, otherwise return array
        resolve(callbackArgs.length <= 1 ? callbackArgs[0] : callbackArgs);
      }
    };

    // Call the Chrome API method
    try {
      const result = method(...args, callback);
      
      // Some newer Chrome APIs return promises directly
      if (result && typeof result.then === 'function') {
        result.then(resolve).catch(reject);
      }
    } catch (error) {
      reject({ error: error.message, stack: error.stack });
    }
  });
}

// Event listener management
const eventListeners = new Map();
let listenerIdCounter = 0;

// Generic JSON-RPC handler
async function handleJsonRpc(request) {
  const { id, method, params = [] } = request;
  
  try {
    // Handle special methods
    if (method === 'addListener') {
      // params: [eventPath, ...eventParams]
      const [eventPath, ...eventParams] = params;
      const listenerId = listenerIdCounter++;
      
      const chromeEvent = getNestedProperty(chrome, eventPath);
      if (!chromeEvent || typeof chromeEvent.addListener !== 'function') {
        throw new Error(`Event ${eventPath} not found or not listenable`);
      }

      const listener = (...args) => {
        // Send event notification
        chrome.runtime.sendMessage({
          jsonrpc: '2.0',
          method: 'event',
          params: {
            listenerId,
            eventPath,
            args
          }
        }).catch(err => log('Failed to send event:', err));
      };

      chromeEvent.addListener(listener);
      eventListeners.set(listenerId, {
        event: chromeEvent,
        listener,
        eventPath
      });

      return { id, result: listenerId };
    }

    if (method === 'removeListener') {
      const [listenerId] = params;
      const entry = eventListeners.get(listenerId);
      
      if (entry) {
        entry.event.removeListener(entry.listener);
        eventListeners.delete(listenerId);
        return { id, result: true };
      }
      
      return { id, result: false };
    }

    // Handle chrome.* API calls
    if (method.startsWith('chrome.')) {
      const path = method.substring(7); // Remove 'chrome.' prefix
      const parts = path.split('.');
      const methodName = parts.pop();
      const apiPath = parts.join('.');
      
      const api = getNestedProperty(chrome, apiPath);
      if (!api) {
        throw new Error(`Chrome API ${apiPath} not found`);
      }

      const apiMethod = api[methodName];
      if (typeof apiMethod !== 'function') {
        throw new Error(`${method} is not a function`);
      }

      // Call the method with promise wrapper
      const result = await promisifyChrome(apiPath + '.' + methodName, apiMethod.bind(api), params);
      return { id, result };
    }

    // Handle direct property access (e.g., "chrome.runtime.id")
    if (method.startsWith('get:chrome.')) {
      const path = method.substring(11); // Remove 'get:chrome.' prefix
      const value = getNestedProperty(chrome, path);
      return { id, result: value };
    }

    throw new Error(`Unknown method: ${method}`);
    
  } catch (error) {
    return {
      id,
      error: {
        code: -32603,
        message: error.message || 'Internal error',
        data: error.stack
      }
    };
  }
}

// Message listener for CDP communication
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only handle JSON-RPC messages
  if (!message.jsonrpc || message.jsonrpc !== '2.0') {
    return false;
  }

  log('JSON-RPC request:', message);

  handleJsonRpc(message)
    .then(response => {
      response.jsonrpc = '2.0';
      log('JSON-RPC response:', response);
      sendResponse(response);
    })
    .catch(error => {
      sendResponse({
        jsonrpc: '2.0',
        id: message.id,
        error: {
          code: -32603,
          message: error.message || 'Internal error'
        }
      });
    });

  // Return true to indicate async response
  return true;
});

// Also listen for external messages (from web pages)
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  // Same handling as internal messages
  if (!message.jsonrpc || message.jsonrpc !== '2.0') {
    return false;
  }

  handleJsonRpc(message)
    .then(response => {
      response.jsonrpc = '2.0';
      sendResponse(response);
    })
    .catch(error => {
      sendResponse({
        jsonrpc: '2.0',
        id: message.id,
        error: {
          code: -32603,
          message: error.message || 'Internal error'
        }
      });
    });

  return true;
});

// Log when service worker starts
log('Service worker initialized with generic JSON-RPC bridge');

// Keep service worker alive by responding to alarms
chrome.alarms.create('keepAlive', { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepAlive') {
    // Just being active keeps the service worker alive
    log('Keep alive ping');
  }
});

// Log extension details on install/update
chrome.runtime.onInstalled.addListener((details) => {
  log('Extension installed/updated:', details);
  log('Extension ID:', chrome.runtime.id);
});

// Expose some metadata
chrome.runtime.getPlatformInfo().then(info => {
  log('Platform:', info);
});

// Export for testing (if needed)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { handleJsonRpc };
}
