import { blockUrls, commons, commonJSHandlers, rules } from "./rules.js";
// Vars
let initialized = false;
let cachedRules = {};
let tabList = {};
const xmlTabs = {};
let lastDeclarativeNetRuleId = 1;
let settings = { statusIndicators: true, whitelistedDomains: {} };
const isManifestV3 = chrome.runtime.getManifest().manifest_version == 3;

// Badges
function setBadge(tabId, text) {
  const chromeAction = chrome?.browserAction ?? chrome?.action;

  if (!chromeAction || !settings.statusIndicators) return;

  chromeAction.setBadgeText({ text: text || "", tabId: tabId });

  if (chromeAction.setBadgeBackgroundColor)
    chromeAction.setBadgeBackgroundColor({
      color: "#646464",
      tabId: tabId,
    });
}

function setSuccessBadge(tabId) {
  setBadge(tabId, "✅");
}

function setDisabledBadge(tabId) {
  setBadge(tabId, "⛔");
}

// Common functions
function getHostname(url, cleanup) {
  try {
    if (url.indexOf("http") != 0) {
      throw true;
    }

    const a = new URL(url);

    return typeof cleanup == "undefined"
      ? a.hostname
      : a.hostname.replace(/^w{2,3}\d*\./i, "");
  } catch (error) {
    return false;
  }
}

// Whitelisting
function updateSettings() {
  return new Promise((resolve) => {
    lastDeclarativeNetRuleId = 1;
    chrome.storage.local.get(
      { settings: { whitelistedDomains: {}, statusIndicators: true } },
      async ({ settings: storedSettings }) => {
        settings = storedSettings;

        if (isManifestV3) {
          await updateWhitelistRules();
        }
        resolve();
      }
    );
  });
}

async function updateWhitelistRules() {
  if (!isManifestV3) {
    console.warn("Called unsupported function");
    return;
  }
  const previousRules = (
    await chrome.declarativeNetRequest.getDynamicRules()
  ).map((v) => {
    return v.id;
  });
  const addRules = Object.entries(settings.whitelistedDomains)
    .filter((element) => element[1])
    .map((v) => {
      return {
        id: lastDeclarativeNetRuleId++,
        priority: 1,
        action: { type: "allow" },
        condition: {
          urlFilter: "*",
          resourceTypes: ["script", "stylesheet", "xmlhttprequest", "image"],
          initiatorDomains: [v[0]],
        },
      };
    });

  chrome.declarativeNetRequest.updateDynamicRules({
    addRules,
    removeRuleIds: previousRules,
  });
}

function isWhitelisted(tab) {
  if (typeof settings.whitelistedDomains[tab.hostname] != "undefined") {
    return true;
  }

  for (const i in tab.host_levels) {
    if (typeof settings.whitelistedDomains[tab.host_levels[i]] != "undefined") {
      return true;
    }
  }

  return false;
}

function getWhitelistedDomain(tab) {
  if (typeof settings.whitelistedDomains[tab.hostname] != "undefined") {
    return tab.hostname;
  }

  for (const i in tab.host_levels) {
    if (typeof settings.whitelistedDomains[tab.host_levels[i]] != "undefined") {
      return tab.host_levels[i];
    }
  }

  return false;
}

async function toggleWhitelist(tab) {
  if (tab.url.indexOf("http") != 0 || !tabList[tab.id]) {
    return;
  }

  if (tabList[tab.id].whitelisted) {
    // const hostname = getWhitelistedDomain(tabList[tab.id]);
    delete settings.whitelistedDomains[tabList[tab.id].hostname];
  } else {
    settings.whitelistedDomains[tabList[tab.id].hostname] = true;
  }
  chrome.storage.local.set({ settings }, function () {
    for (const i in tabList) {
      if (tabList[i].hostname == tabList[tab.id].hostname) {
        tabList[i].whitelisted = !tabList[tab.id].whitelisted;
      }
    }
  });
  if (isManifestV3) {
    await updateWhitelistRules();
  }
}

// Maintain tab list

function getPreparedTab(tab) {
  tab.hostname = false;
  tab.whitelisted = false;
  tab.host_levels = [];

  if (tab.url) {
    tab.hostname = getHostname(tab.url, true);

    if (tab.hostname) {
      const parts = tab.hostname.split(".");

      for (let i = parts.length; i >= 2; i--) {
        tab.host_levels.push(parts.slice(-1 * i).join("."));
      }

      tab.whitelisted = isWhitelisted(tab);
    }
  }

  return tab;
}

function onCreatedListener(tab) {
  tabList[tab.id] = getPreparedTab(tab);
}

function onUpdatedListener(tabId, changeInfo, tab) {
  if (changeInfo.status) {
    tabList[tab.id] = getPreparedTab(tab);
  }
}

function onRemovedListener(tabId) {
  if (tabList[tabId]) {
    delete tabList[tabId];
  }
}

async function recreateTabList(magic) {
  tabList = {};
  let results;
  if (isManifestV3) {
    results = await chrome.tabs.query({});
  } else {
    results = await new Promise((resolve, reject) => {
      chrome.tabs.query({}, (result) => {
        if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
        resolve(result);
      });
    });
  }
  results.forEach(onCreatedListener);

  if (magic) {
    for (const i in tabList) {
      if (tabList.hasOwnProperty(i)) {
        doTheMagic(tabList[i].id);
      }
    }
  }
}

chrome.tabs.onCreated.addListener(onCreatedListener);
chrome.tabs.onUpdated.addListener(onUpdatedListener);
chrome.tabs.onRemoved.addListener(onRemovedListener);

// chrome.runtime.onStartup.addListener(async () => await initialize(true));
chrome.runtime.onInstalled.addListener(
  async () => await initialize(false, true)
);

// URL blocking

function blockUrlCallback(d) {
  // Cached request: find the appropriate tab
  // TODO: parse rules.json for this function.

  if (d.tabId == -1 && d.initiator) {
    // const hostname = getHostname(d.initiator, true);
    for (const tabId in tabList) {
      if (tabList[tabId].hostname == getHostname(d.initiator, true)) {
        d.tabId = parseInt(tabId);
        break;
      }
    }
  }

  if (tabList[d.tabId]?.whitelisted ?? false) {
    setDisabledBadge(d.tabId);
    return { cancel: false };
  }

  if (tabList[d.tabId] && d.url) {
    const cleanURL = d.url.split("?")[0];

    // To shorten the checklist, many filters are grouped by keywords

    for (const group in blockUrls.common_groups) {
      if (d.url.indexOf(group) > -1) {
        const groupFilters = blockUrls.common_groups[group];

        for (const i in groupFilters) {
          if (
            (groupFilters[i].q && d.url.indexOf(groupFilters[i].r) > -1) ||
            (!groupFilters[i].q && cleanURL.indexOf(groupFilters[i].r) > -1)
          ) {
            // Check for exceptions

            if (groupFilters[i].e && tabList[d.tabId].host_levels.length > 0) {
              for (const level in tabList[d.tabId].host_levels) {
                for (const exception in groupFilters[i].e) {
                  if (
                    groupFilters[i].e[exception] ==
                    tabList[d.tabId].host_levels[level]
                  ) {
                    return { cancel: false };
                  }
                }
              }
            }
            setSuccessBadge(d.tabId);
            return { cancel: true };
          }
        }
      }
    }

    // Check ungrouped filters

    const groupFilters = blockUrls.common;

    for (const i in groupFilters) {
      if (
        (groupFilters[i].q && d.url.indexOf(groupFilters[i].r) > -1) ||
        (!groupFilters[i].q && cleanURL.indexOf(groupFilters[i].r) > -1)
      ) {
        // Check for exceptions

        if (groupFilters[i].e && tabList[d.tabId].host_levels.length > 0) {
          for (const level in tabList[d.tabId].host_levels) {
            for (const exception in groupFilters[i].e) {
              if (
                groupFilters[i].e[exception] ==
                tabList[d.tabId].host_levels[level]
              ) {
                return { cancel: false };
              }
            }
          }
        }
        setSuccessBadge(d.tabId);
        return { cancel: true };
      }
    }

    // Site specific filters

    if (d.tabId > -1 && tabList[d.tabId].host_levels.length > 0) {
      for (const level in tabList[d.tabId].host_levels) {
        if (blockUrls.specific[tabList[d.tabId].host_levels[level]]) {
          const rules = blockUrls.specific[tabList[d.tabId].host_levels[level]];

          for (const i in rules) {
            if (d.url.indexOf(rules[i]) > -1) {
              setSuccessBadge(d.tabId);
              return { cancel: true };
            }
          }
        }
      }
    }
  }

  return { cancel: false };
}
if (!isManifestV3) {
  chrome.webRequest.onBeforeRequest.addListener(
    blockUrlCallback,
    {
      urls: ["http://*/*", "https://*/*"],
      types: ["script", "stylesheet", "xmlhttprequest"],
    },
    ["blocking"]
  );

  chrome.webRequest.onHeadersReceived.addListener(
    function (d) {
      if (tabList[d.tabId]) {
        d.responseHeaders.forEach(function (h) {
          if (h.name == "Content-Type" || h.name == "content-type") {
            xmlTabs[d.tabId] = h.value.indexOf("/xml") > -1;
          }
        });
      }

      return { cancel: false };
    },
    { urls: ["http://*/*", "https://*/*"], types: ["main_frame"] },
    ["blocking", "responseHeaders"]
  );
}
// Reporting

function reportWebsite(info, tab, anon, issueType, notes, callback) {
  if (tab.url.indexOf("http") != 0 || !tabList[tab.id]) {
    return;
  }

  const hostname = getHostname(tab.url);

  if (hostname.length == 0) {
    return;
  }

  if (tabList[tab.id].whitelisted) {
    return chrome.notifications.create("report", {
      type: "basic",
      title: chrome.i18n.getMessage("reportSkippedTitle", hostname),
      message: chrome.i18n.getMessage("reportSkippedMessage"),
      iconUrl: "icons/48.png",
    });
  }
  if (!anon) {
    chrome.tabs.create({
      url: `https://github.com/OhMyGuus/I-Dont-Care-About-Cookies/issues/new?assignees=OhMyGuus&labels=Website+request&template=website_request.yml&title=%5BREQ%5D%3A+${encodeURIComponent(
        hostname
      )}&url=${encodeURIComponent(hostname)}&version=${encodeURIComponent(
        chrome.runtime.getManifest().version
      )}&browser=${encodeURIComponent(getBrowserAndVersion())}`,
    });
  } else {
    fetch("https://api.istilldontcareaboutcookies.com/api/report", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        issueType,
        notes,
        url: tab.url,
        browser: getBrowserAndVersion(),
        extensionVersion: chrome.runtime.getManifest().version,
      }),
    })
      .then((response) => response.json())
      .then((response) => {
        if (
          response &&
          !response.error &&
          !response.errors &&
          response.responseURL
        ) {
          chrome.tabs.create({
            url: response.responseURL,
          });
          callback({ error: false });
        } else {
          callback({ error: true });
        }
      })
      .catch(() => {
        callback({ error: true });
      });
  }
}

function getBrowserAndVersion() {
  const useragent = navigator.userAgent;
  if (useragent.includes("Firefox")) {
    return useragent.match(/Firefox\/([0-9]+[\S]+)/)[0].replace("/", " ");
  } else if (useragent.includes("Chrome")) {
    if (navigator.userAgentData.brands.length > 2) {
      const { brand, version } = navigator.userAgentData.brands[1];
      return brand + " " + version;
    }
  }
  return "Other";
}

// Adding custom CSS/JS

function activateDomain(hostname, tabId, frameId) {
  if (!cachedRules[hostname]) {
    cachedRules[hostname] = rules[hostname] || {};
  }

  if (!cachedRules[hostname]) {
    return false;
  }

  const cachedRule = cachedRules[hostname];
  let status = false;

  // cached_rule.s = Custom css for webpage
  // cached_rule.c = Common css for webpage
  // cached_rule.j = Common js  for webpage

  if (typeof cachedRule.s != "undefined") {
    insertCSS({ tabId, frameId: frameId || 0, css: cachedRule.s });
    status = true;
  }

  if (typeof cachedRule.c != "undefined") {
    insertCSS({ tabId, frameId: frameId || 0, css: commons[cachedRule.c] });
    status = true;
  }

  if (typeof cachedRule.j != "undefined") {
    executeScript({
      tabId,
      frameId,
      file: `/data/js/${commonJSHandlers[cachedRule.j]}.js`,
    });
    status = true;
  }

  if (status) {
    setSuccessBadge(tabId);
  }

  return status;
}

function doTheMagic(tabId, frameId, anotherTry) {
  if (!tabList[tabId] || tabList[tabId].url.indexOf("http") != 0) {
    return;
  }

  if (tabList[tabId].whitelisted) {
    setDisabledBadge(tabId);
    return;
  }

  // Common CSS rules
  insertCSS(
    { tabId, frameId: frameId || 0, file: "/data/css/common.css" },
    function () {
      // A failure? Retry.
      if (chrome.runtime.lastError) {
        console.log(chrome.runtime.lastError);

        const currentTry = anotherTry || 1;

        if (currentTry == 10) {
          return;
        }
        if (currentTry > 5) {
          setTimeout(() => doTheMagic(tabId, frameId || 0, currentTry + 1));
        } else {
          doTheMagic(tabId, frameId || 0, currentTry + 1);
        }
        return;
      }

      // Common social embeds
      executeScript({ tabId, frameId, file: "/data/js/embedsHandler.js" });

      if (activateDomain(tabList[tabId].hostname, tabId, frameId || 0)) {
        return;
      }

      for (const level in tabList[tabId].host_levels) {
        if (
          activateDomain(tabList[tabId].host_levels[level], tabId, frameId || 0)
        ) {
          return true;
        }
      }

      // Common JS rules when custom rules don't exist
      executeScript({
        tabId,
        frameId,
        file: "/data/js/0_defaultClickHandler.js",
      });
    }
  );
}

chrome.webNavigation.onCommitted.addListener(async (tab) => {
  if (tab.frameId > 0) {
    return;
  }
  if (!initialized) {
    await initialize();
  }

  tabList[tab.tabId] = getPreparedTab(tab);

  doTheMagic(tab.tabId);
});

chrome.webNavigation.onCompleted.addListener(async function (tab) {
  if (!initialized) {
    await initialize();
  }
  if (tab.frameId > 0 && tab.url != "about:blank") {
    doTheMagic(tab.tabId, tab.frameId);
  }
});

// Toolbar menu

chrome.runtime.onMessage.addListener((request, info, sendResponse) => {
  initialize().then(() => {
    let responseSend = false;
    if (typeof request == "object") {
      if (request.tabId && tabList[request.tabId]) {
        if (request.command == "get_active_tab") {
          const response = { tab: tabList[request.tabId] };

          if (response.tab.whitelisted) {
            response.tab.hostname = getWhitelistedDomain(
              tabList[request.tabId]
            );
          }
          sendResponse(response);
          responseSend = true;
        } else if (request.command == "toggle_extension") {
          toggleWhitelist(tabList[request.tabId]);
        } else if (request.command == "report_website") {
          reportWebsite(
            info,
            tabList[request.tabId],
            request.anon,
            request.issueType,
            request.notes,
            sendResponse
          );
          responseSend = true;
        } else if (request.command == "refresh_page") {
          executeScript({
            tabId: request.tabId,
            func: () => {
              window.location.reload();
            },
          });
        }
      } else {
        if (request.command == "open_options_page") {
          chrome.tabs.create({
            url: chrome.runtime.getURL("/data/options.html"),
          });
        }
      }
    } else if (request == "update_settings") {
      updateSettings();
    }
    if (!responseSend) {
      sendResponse();
    }
  });

  return true;
});

function insertCSS(injection, callback) {
  const { tabId, css, file, frameId } = injection;

  if (isManifestV3) {
    chrome.scripting.insertCSS(
      {
        target: { tabId: tabId, frameIds: [frameId || 0] },
        css: css,
        files: file ? [file] : undefined,
        origin: "USER",
      },
      callback
    );
  } else {
    chrome.tabs.insertCSS(
      tabId,
      {
        file,
        code: css,
        frameId: frameId || 0,
        runAt: xmlTabs[tabId] ? "document_idle" : "document_start",
        cssOrigin: "user",
      },
      callback
    );
  }
}

function executeScript(injection, callback) {
  const { tabId, func, file, frameId } = injection;
  if (isManifestV3) {
    // manifest v3
    chrome.scripting.executeScript(
      {
        target: { tabId, frameIds: [frameId || 0] },
        files: file ? [file] : undefined,
        func,
      },
      callback
    );
  } else {
    // manifest v2
    chrome.tabs.executeScript(
      tabId,
      {
        file,
        frameId: frameId || 0,
        code: func == undefined ? undefined : "(" + func.toString() + ")();",
        runAt: xmlTabs[tabId] ? "document_idle" : "document_end",
      },
      callback
    );
  }
}

async function loadCachedRules() {
  // TODO: Load cached rules for V3 to improve speed (Requires testing to see if this actually is faster for v3)
  cachedRules = {};
}

// Pre-populate storage with configurable domain whitelist if empty
async function ensureWhitelistStorage() {
  const result = await chrome.storage.local.get({ settings: null });
  if (!result.settings) {
    const defaultSettings = {
      statusIndicators: true,
      whitelistedDomains: {
        "nature.com": true,
        "qatarairways.com": true
      }
    };
    await chrome.storage.local.set({ settings: defaultSettings });
  }
}

async function initialize(checkInitialized, magic) {
  if (checkInitialized && initialized) {
    return;
  }
  loadCachedRules();
  await ensureWhitelistStorage(); // Add storage initialization
  await updateSettings();
  await recreateTabList(magic);
  initialized = true;
}

initialize();
