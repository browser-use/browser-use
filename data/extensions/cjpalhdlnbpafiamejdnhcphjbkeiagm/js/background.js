/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-present Raymond Hill

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see {http://www.gnu.org/licenses/}.

    Home: https://github.com/gorhill/uBlock
*/

/******************************************************************************/

import {
    domainFromHostname,
    hostnameFromURI,
    originFromURI,
} from './uri-utils.js';

import { FilteringContext } from './filtering-context.js';
import logger from './logger.js';
import { ubologSet } from './console.js';

/******************************************************************************/

// Not all platforms may have properly declared vAPI.webextFlavor.

if ( vAPI.webextFlavor === undefined ) {
    vAPI.webextFlavor = { major: 0, soup: new Set([ 'ublock' ]) };
}

/******************************************************************************/

const hiddenSettingsDefault = {
    allowGenericProceduralFilters: false,
    assetFetchTimeout: 30,
    autoCommentFilterTemplate: '{{date}} {{origin}}',
    autoUpdateAssetFetchPeriod: 5,
    autoUpdateDelayAfterLaunch: 37,
    autoUpdatePeriod: 1,
    benchmarkDatasetURL: 'unset',
    blockingProfiles: '11111/#F00 11010/#C0F 11001/#00F 00001',
    cacheStorageCompression: true,
    cacheStorageCompressionThreshold: 65536,
    cacheStorageMultithread: 2,
    cacheControlForFirefox1376932: 'unset',
    cloudStorageCompression: true,
    cnameIgnoreList: 'unset',
    cnameIgnore1stParty: true,
    cnameIgnoreExceptions: true,
    cnameIgnoreRootDocument: true,
    cnameReplayFullURL: false,
    consoleLogLevel: 'unset',
    debugAssetsJson: false,
    debugScriptlets: false,
    debugScriptletInjector: false,
    differentialUpdate: true,
    disableWebAssembly: false,
    dnsCacheTTL: 600,
    dnsResolveEnabled: true,
    extensionUpdateForceReload: false,
    filterAuthorMode: false,
    loggerPopupType: 'popup',
    manualUpdateAssetFetchPeriod: 500,
    modifyWebextFlavor: 'unset',
    noScriptingCSP: 'script-src http: https:',
    popupFontSize: 'unset',
    popupPanelDisabledSections: 0,
    popupPanelHeightMode: 0,
    popupPanelLockedSections: 0,
    popupPanelOrientation: 'unset',
    requestJournalProcessPeriod: 1000,
    requestStatsDisabled: false,
    selfieDelayInSeconds: 53,
    strictBlockingBypassDuration: 120,
    toolbarWarningTimeout: 60,
    trustedListPrefixes: 'ublock-',
    uiPopupConfig: 'unset',
    uiStyles: 'unset',
    updateAssetBypassBrowserCache: false,
    userResourcesLocation: 'unset',
};

if ( vAPI.webextFlavor.soup.has('devbuild') ) {
    hiddenSettingsDefault.consoleLogLevel = 'info';
    hiddenSettingsDefault.cacheStorageAPI = 'unset';
    ubologSet(true);
}

const userSettingsDefault = {
    advancedUserEnabled: false,
    alwaysDetachLogger: true,
    autoUpdate: true,
    cloudStorageEnabled: false,
    cnameUncloakEnabled: true,
    collapseBlocked: true,
    colorBlindFriendly: false,
    contextMenuEnabled: true,
    uiAccentCustom: false,
    uiAccentCustom0: '#aca0f7',
    uiTheme: 'auto',
    externalLists: '',
    firewallPaneMinimized: true,
    hyperlinkAuditingDisabled: true,
    ignoreGenericCosmeticFilters: false,
    importedLists: [],
    largeMediaSize: 50,
    parseAllABPHideFilters: true,
    popupPanelSections: 0b111,
    prefetchingDisabled: true,
    requestLogMaxEntries: 1000,
    showIconBadge: true,
    suspendUntilListsAreLoaded: vAPI.Net.canSuspend(),
    tooltipsDisabled: false,
    userFiltersTrusted: false,
    webrtcIPAddressHidden: false,
};

const dynamicFilteringDefault = [
    'behind-the-scene * * noop',
    'behind-the-scene * image noop',
    'behind-the-scene * 3p noop',
    'behind-the-scene * inline-script noop',
    'behind-the-scene * 1p-script noop',
    'behind-the-scene * 3p-script noop',
    'behind-the-scene * 3p-frame noop',
];

const hostnameSwitchesDefault = [
    'no-large-media: behind-the-scene false',
];
// https://github.com/LiCybora/NanoDefenderFirefox/issues/196
if ( vAPI.webextFlavor.soup.has('firefox') ) {
    hostnameSwitchesDefault.push('no-csp-reports: * true');
}

const µBlock = {  // jshint ignore:line
    alarmQueue: [],

    userSettingsDefault,
    userSettings: Object.assign({}, userSettingsDefault),

    hiddenSettingsDefault,
    hiddenSettingsAdmin: {},
    hiddenSettings: Object.assign({}, hiddenSettingsDefault),

    dynamicFilteringDefault,
    hostnameSwitchesDefault,

    noDashboard: false,

    // Features detection.
    privacySettingsSupported: vAPI.browserSettings instanceof Object,
    cloudStorageSupported: vAPI.cloud instanceof Object,
    canFilterResponseData: typeof browser.webRequest.filterResponseData === 'function',

    // https://github.com/chrisaljoudi/uBlock/issues/180
    // Whitelist directives need to be loaded once the PSL is available
    netWhitelist: new Map(),
    netWhitelistModifyTime: 0,
    netWhitelistDefault: [
        'chrome-extension-scheme',
        'moz-extension-scheme',
    ],

    requestStats: {
        blockedCount: 0,
        allowedCount: 0,
    },

    // Read-only
    systemSettings: {
        compiledMagic: 60,  // Increase when compiled format changes
        selfieMagic: 60,    // Increase when selfie format changes
    },

    // https://github.com/uBlockOrigin/uBlock-issues/issues/759#issuecomment-546654501
    //   The assumption is that cache storage state reflects whether
    //   compiled or selfie assets are available or not. The properties
    //   below is to no longer rely on this assumption -- though it's still
    //   not clear how the assumption could be wrong, and it's still not
    //   clear whether relying on those properties will really solve the
    //   issue. It's just an attempt at hardening.
    compiledFormatChanged: false,
    selfieIsInvalid: false,

    restoreBackupSettings: {
        lastRestoreFile: '',
        lastRestoreTime: 0,
        lastBackupFile: '',
        lastBackupTime: 0,
    },

    commandShortcuts: new Map(),

    // Allows to fully customize uBO's assets, typically set through admin
    // settings. The content of 'assets.json' will also tell which filter
    // lists to enable by default when uBO is first installed.
    assetsBootstrapLocation: undefined,

    assetsJsonPath: vAPI.webextFlavor.soup.has('devbuild')
        ? '/assets/assets.dev.json'
        : '/assets/assets.json',
    userFiltersPath: 'user-filters',
    pslAssetKey: 'public_suffix_list.dat',

    selectedFilterLists: [],
    availableFilterLists: {},
    badLists: new Map(),

    inMemoryFilters: [],
    inMemoryFiltersCompiled: '',

    // https://github.com/uBlockOrigin/uBlock-issues/issues/974
    //   This can be used to defer filtering decision-making.
    readyToFilter: false,

    supportStats: {
        allReadyAfter: '?',
        maxAssetCacheWait: '?',
    },

    pageStores: new Map(),
    pageStoresToken: 0,

    storageQuota: vAPI.storage.QUOTA_BYTES,
    storageUsed: 0,

    noopFunc: function(){},

    apiErrorCount: 0,

    maybeGoodPopup: {
        tabId: 0,
        url: '',
    },

    epickerArgs: {
        eprom: null,
        mouse: false,
        target: '',
        zap: false,
    },

    scriptlets: {},

    cspNoInlineScript: "script-src 'unsafe-eval' * blob: data:",
    cspNoInlineFont: 'font-src *',

    liveBlockingProfiles: [],
    blockingProfileColorCache: new Map(),
    parsedTrustedListPrefixes: [],
    uiAccentStylesheet: '',
};

µBlock.isReadyPromise = new Promise(resolve => {
    µBlock.isReadyResolve = resolve;
});

µBlock.domainFromHostname = domainFromHostname;
µBlock.hostnameFromURI = hostnameFromURI;

µBlock.FilteringContext = class extends FilteringContext {
    duplicate() {
        return (new µBlock.FilteringContext(this));
    }

    fromTabId(tabId) {
        const tabContext = µBlock.tabContextManager.mustLookup(tabId);
        this.tabOrigin = tabContext.origin;
        this.tabHostname = tabContext.rootHostname;
        this.tabDomain = tabContext.rootDomain;
        this.tabId = tabContext.tabId;
        return this;
    }

    maybeFromDocumentURL(documentUrl) {
        if ( documentUrl === undefined ) { return; }
        if ( documentUrl.startsWith(this.tabOrigin) ) { return; }
        this.tabOrigin = originFromURI(µBlock.normalizeTabURL(0, documentUrl));
        this.tabHostname = hostnameFromURI(this.tabOrigin);
        this.tabDomain = domainFromHostname(this.tabHostname);
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/459
    //   In case of a request for frame and if ever no context is specified,
    //   assume the origin of the context is the same as the request itself.
    fromWebrequestDetails(details) {
        const tabId = details.tabId;
        this.type = details.type;
        const isMainFrame = this.itype === this.MAIN_FRAME;
        if ( isMainFrame && tabId > 0 ) {
            µBlock.tabContextManager.push(tabId, details.url);
        }
        this.fromTabId(tabId); // Must be called AFTER tab context management
        this.realm = '';
        this.setMethod(details.method);
        this.setURL(details.url);
        this.setIPAddress(details.ip);
        this.aliasURL = details.aliasURL || undefined;
        this.redirectURL = undefined;
        this.filter = undefined;
        if ( this.itype !== this.SUB_FRAME ) {
            this.docId = details.frameId;
            this.frameId = -1;
        } else {
            this.docId = details.parentFrameId;
            this.frameId = details.frameId;
        }
        if ( this.tabId > 0 ) {
            if ( this.docId === 0 ) {
                if ( isMainFrame === false ) {
                    this.maybeFromDocumentURL(details.documentUrl);
                }
                this.docOrigin = this.tabOrigin;
                this.docHostname = this.tabHostname;
                this.docDomain = this.tabDomain;
                return this;
            }
            if ( details.documentUrl !== undefined ) {
                this.setDocOriginFromURL(details.documentUrl);
                return this;
            }
            const pageStore = µBlock.pageStoreFromTabId(this.tabId);
            const docStore = pageStore && pageStore.getFrameStore(this.docId);
            if ( docStore ) {
                this.setDocOriginFromURL(docStore.rawURL);
            } else {
                this.setDocOrigin(this.tabOrigin);
            }
            return this;
        }
        if ( details.documentUrl !== undefined ) {
            const origin = originFromURI(
                µBlock.normalizeTabURL(0, details.documentUrl)
            );
            this.setDocOrigin(origin).setTabOrigin(origin);
            return this;
        }
        const origin = this.isDocument()
            ? originFromURI(this.url)
            : this.tabOrigin;
        this.setDocOrigin(origin).setTabOrigin(origin);
        return this;
    }

    getTabOrigin() {
        if ( this.tabOrigin === undefined ) {
            const tabContext = µBlock.tabContextManager.mustLookup(this.tabId);
            this.tabOrigin = tabContext.origin;
            this.tabHostname = tabContext.rootHostname;
            this.tabDomain = tabContext.rootDomain;
        }
        return super.getTabOrigin();
    }

    toLogger() {
        const details = {
            tstamp: 0,
            realm: this.realm,
            method: this.getMethodName(),
            type: this.stype,
            tabId: this.tabId,
            tabDomain: this.getTabDomain(),
            tabHostname: this.getTabHostname(),
            docDomain: this.getDocDomain(),
            docHostname: this.getDocHostname(),
            domain: this.getDomain(),
            hostname: this.getHostname(),
            url: this.url,
            aliasURL: this.aliasURL,
            filter: undefined,
        };
        // Many filters may have been applied to the current context
        if ( Array.isArray(this.filter) === false ) {
            details.filter = this.filter;
            return logger.writeOne(details);
        }
        for ( const filter of this.filter ) {
            details.filter = filter;
            logger.writeOne(details);
        }
    }
};

µBlock.filteringContext = new µBlock.FilteringContext();

self.µBlock = µBlock;

/******************************************************************************/

export default µBlock;
