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
    isNetworkURI,
} from './uri-utils.js';

import {
    sessionFirewall,
    sessionSwitches,
    sessionURLFiltering,
} from './filtering-engines.js';

import contextMenu from './contextmenu.js';
import logger from './logger.js';
import { orphanizeString } from './text-utils.js';
import { redirectEngine } from './redirect-engine.js';
import staticNetFilteringEngine from './static-net-filtering.js';
import webext from './webext.js';
import µb from './background.js';

/*******************************************************************************

A PageRequestStore object is used to store net requests in two ways:

To record distinct net requests
To create a log of net requests

**/

/******************************************************************************/

const NetFilteringResultCache = class {
    shelfLife = 15000;
    extensionOriginURL = vAPI.getURL('/');

    constructor() {
        this.pruneTimer = vAPI.defer.create(( ) => {
            this.prune();
        });
        this.init();
    }

    init() {
        this.blocked = new Map();
        this.results = new Map();
        this.hash = 0;
        return this;
    }

    // https://github.com/gorhill/uBlock/issues/3619
    //   Don't collapse redirected resources
    rememberResult(fctxt, result) {
        if ( fctxt.tabId <= 0 ) { return; }
        if ( this.results.size === 0 ) {
            this.pruneAsync();
        }
        const key = `${fctxt.getDocHostname()} ${fctxt.type} ${fctxt.url}`;
        this.results.set(key, {
            result,
            redirectURL: fctxt.redirectURL,
            logData: fctxt.filter,
            tstamp: Date.now()
        });
        if ( result !== 1 || fctxt.redirectURL !== undefined ) { return; }
        const now = Date.now();
        this.blocked.set(key, now);
        this.hash = now;
    }

    rememberBlock(fctxt) {
        if ( fctxt.tabId <= 0 ) { return; }
        if ( this.blocked.size === 0 ) {
            this.pruneAsync();
        }
        if ( fctxt.redirectURL !== undefined ) { return; }
        const now = Date.now();
        this.blocked.set(
            `${fctxt.getDocHostname()} ${fctxt.type} ${fctxt.url}`,
            now
        );
        this.hash = now;
    }

    forgetResult(docHostname, type, url) {
        const key = `${docHostname} ${type} ${url}`;
        this.results.delete(key);
        this.blocked.delete(key);
    }

    empty() {
        this.blocked.clear();
        this.results.clear();
        this.hash = 0;
        this.pruneTimer.off();
    }

    prune() {
        const obsolete = Date.now() - this.shelfLife;
        for ( const entry of this.blocked ) {
            if ( entry[1] <= obsolete ) {
                this.results.delete(entry[0]);
                this.blocked.delete(entry[0]);
            }
        }
        for ( const entry of this.results ) {
            if ( entry[1].tstamp <= obsolete ) {
                this.results.delete(entry[0]);
            }
        }
        if ( this.blocked.size !== 0 || this.results.size !== 0 ) {
            this.pruneAsync();
        }
    }

    pruneAsync() {
        this.pruneTimer.on(this.shelfLife);
    }

    lookupResult(fctxt) {
        const entry = this.results.get(
            fctxt.getDocHostname() + ' ' +
            fctxt.type + ' ' +
            fctxt.url
        );
        if ( entry === undefined ) { return; }
        // We need to use a new WAR secret if one is present since WAR secrets
        // can only be used once.
        if (
            entry.redirectURL !== undefined &&
            entry.redirectURL.startsWith(this.extensionOriginURL)
        ) {
            const redirectURL = new URL(entry.redirectURL);
            redirectURL.searchParams.set('secret', vAPI.warSecret.short());
            entry.redirectURL = redirectURL.href;
        }
        return entry;
    }

    lookupAllBlocked(hostname) {
        const result = [];
        for ( const entry of this.blocked ) {
            const pos = entry[0].indexOf(' ');
            if ( entry[0].slice(0, pos) === hostname ) {
                result[result.length] = entry[0].slice(pos + 1);
            }
        }
        return result;
    }

    static factory() {
        return new NetFilteringResultCache();
    }
};

/******************************************************************************/

// Frame stores are used solely to associate a URL with a frame id.

const FrameStore = class {
    constructor(frameURL, parentId) {
        this.init(frameURL, parentId);
    }

    init(frameURL, parentId) {
        this.t0 = Date.now();
        this.parentId = parentId;
        this.exceptCname = undefined;
        this.clickToLoad = false;
        this.rawURL = frameURL;
        if ( frameURL !== undefined ) {
            this.hostname = hostnameFromURI(frameURL);
            this.domain = domainFromHostname(this.hostname) || this.hostname;
        }
        // Evaluated on-demand
        // - 0b01: specific cosmetic filtering
        // - 0b10: generic cosmetic filtering
        this._cosmeticFilteringBits = undefined;
        return this;
    }

    dispose() {
        this.rawURL = this.hostname = this.domain = '';
        if ( FrameStore.junkyard.length < FrameStore.junkyardMax ) {
            FrameStore.junkyard.push(this);
        }
        return null;
    }

    updateURL(url) {
        if ( typeof url !== 'string' ) { return; }
        this.rawURL = url;
        this.hostname = hostnameFromURI(url);
        this.domain = domainFromHostname(this.hostname) || this.hostname;
        this._cosmeticFilteringBits = undefined;
    }

    getCosmeticFilteringBits(tabId) {
        if ( this._cosmeticFilteringBits !== undefined ) {
            return this._cosmeticFilteringBits;
        }
        this._cosmeticFilteringBits = 0b11;
        {
            const result = staticNetFilteringEngine.matchRequestReverse(
                'specifichide',
                this.rawURL
            );
            if ( result !== 0 && logger.enabled ) {
                µb.filteringContext
                    .duplicate()
                    .fromTabId(tabId)
                    .setURL(this.rawURL)
                    .setDocOriginFromURL(this.rawURL)
                    .setRealm('network')
                    .setType('specifichide')
                    .setFilter(staticNetFilteringEngine.toLogData())
                    .toLogger();
            }
            if ( result === 2 ) {
                this._cosmeticFilteringBits &= ~0b01;
            }
        }
        {
            const result = staticNetFilteringEngine.matchRequestReverse(
                'generichide',
                this.rawURL
            );
            if ( result !== 0 && logger.enabled ) {
                µb.filteringContext
                    .duplicate()
                    .fromTabId(tabId)
                    .setURL(this.rawURL)
                    .setDocOriginFromURL(this.rawURL)
                    .setRealm('network')
                    .setType('generichide')
                    .setFilter(staticNetFilteringEngine.toLogData())
                    .toLogger();
            }
            if ( result === 2 ) {
                this._cosmeticFilteringBits &= ~0b10;
            }
        }
        return this._cosmeticFilteringBits;
    }

    shouldApplySpecificCosmeticFilters(tabId) {
        return (this.getCosmeticFilteringBits(tabId) & 0b01) !== 0;
    }

    shouldApplyGenericCosmeticFilters(tabId) {
        return (this.getCosmeticFilteringBits(tabId) & 0b10) !== 0;
    }

    static factory(frameURL, parentId = -1) {
        const FS = FrameStore;
        if ( FS.junkyard.length !== 0 ) {
            return FS.junkyard.pop().init(frameURL, parentId);
        }
        return new FS(frameURL, parentId);
    }
    static junkyard = [];
    static junkyardMax = 50;
};

/******************************************************************************/

const CountDetails = class {
    constructor() {
        this.allowed = { any: 0, frame: 0, script: 0 };
        this.blocked = { any: 0, frame: 0, script: 0 };
    }
    reset() {
        const { allowed, blocked } = this;
        blocked.any = blocked.frame = blocked.script =
        allowed.any = allowed.frame = allowed.script = 0;
    }
    inc(blocked, type = undefined) {
        const stat = blocked ? this.blocked : this.allowed;
        if ( type !== undefined ) { stat[type] += 1; }
        stat.any += 1;
    }
};

const HostnameDetails = class {
    constructor(hostname) {
        this.counts = new CountDetails();
        this.init(hostname);
    }
    init(hostname) {
        this.hostname = hostname;
        this.cname = vAPI.net.canonicalNameFromHostname(hostname);
        this.counts.reset();
        return this;
    }
    dispose() {
        const HD = HostnameDetails;
        if ( HD.junkyard.length >= HD.junkyardMax ) { return; }
        HD.junkyard.push(this);
    }
    static factory(hostname) {
        const HD = HostnameDetails;
        if ( HD.junkyard.length !== 0 ) {
            return HD.junkyard.pop().init(hostname);
        }
        return new HD(hostname);
    }
    static junkyard = [];
    static junkyardMax = 100;
};

const HostnameDetailsMap = class extends Map {
    reset() {
        this.clear();
    }
    dispose() {
        for ( const item of this.values() ) {
            item.dispose();
        }
        this.reset();
    }
};

/******************************************************************************/

const PageStore = class {
    constructor(tabId, details) {
        this.extraData = new Map();
        this.journal = [];
        this.journalLastCommitted = this.journalLastUncommitted = -1;
        this.journalLastUncommittedOrigin = undefined;
        this.netFilteringCache = NetFilteringResultCache.factory();
        this.hostnameDetailsMap = new HostnameDetailsMap();
        this.counts = new CountDetails();
        this.journalTimer = vAPI.defer.create(( ) => {
            this.journalProcess();
        });
        this.largeMediaTimer = vAPI.defer.create(( ) => {
            this.injectLargeMediaElementScriptlet();
        });
        this.init(tabId, details);
    }

    static factory(tabId, details) {
        let entry = PageStore.junkyard.pop();
        if ( entry === undefined ) {
            entry = new PageStore(tabId, details);
        } else {
            entry.init(tabId, details);
        }
        return entry;
    }

    // https://github.com/gorhill/uBlock/issues/3201
    //   The context is used to determine whether we report behavior change
    //   to the logger.

    init(tabId, details) {
        const tabContext = µb.tabContextManager.mustLookup(tabId);
        this.tabId = tabId;

        // If we are navigating from-to same site, remember whether large
        // media elements were temporarily allowed.
        const now = Date.now();
        if ( typeof this.allowLargeMediaElementsUntil !== 'number' ) {
            this.allowLargeMediaElementsUntil = now;
        } else if ( tabContext.rootHostname !== this.tabHostname ) {
            if ( this.tabHostname.endsWith('about-scheme') === false ) {
                this.allowLargeMediaElementsUntil = now;
            }
        }

        this.tabHostname = tabContext.rootHostname;
        this.rawURL = tabContext.rawURL;
        this.hostnameDetailsMap.reset();
        this.contentLastModified = 0;
        this.logData = undefined;
        this.counts.reset();
        this.remoteFontCount = 0;
        this.popupBlockedCount = 0;
        this.largeMediaCount = 0;
        this.allowLargeMediaElementsRegex = undefined;
        this.extraData.clear();

        this.frameAddCount = 0;
        this.frames = new Map();
        this.setFrameURL({ url: tabContext.rawURL });

        if ( this.titleFromDetails(details) === false ) {
            this.title = tabContext.rawURL;
        }

        // Evaluated on-demand
        this._noCosmeticFiltering = undefined;

        // Remember if the webpage was potentially improperly filtered, for
        // reporting purpose.
        this.hasUnprocessedRequest = vAPI.net.hasUnprocessedRequest(tabId);

        return this;
    }

    reuse(context, details) {
        // When force refreshing a page, the page store data needs to be reset.

        // If the hostname changes, we can't merely just update the context.
        const tabContext = µb.tabContextManager.mustLookup(this.tabId);
        if ( tabContext.rootHostname !== this.tabHostname ) {
            context = '';
        }

        // If URL changes without a page reload (more and more common), then
        // we need to keep all that we collected for reuse. In particular,
        // not doing so was causing a problem in `videos.foxnews.com`:
        // clicking a video thumbnail would not work, because the frame
        // hierarchy structure was flushed from memory, while not really being
        //  flushed on the page.
        if ( context === 'tabUpdated' ) {
            // As part of https://github.com/chrisaljoudi/uBlock/issues/405
            // URL changed, force a re-evaluation of filtering switch
            this.rawURL = tabContext.rawURL;
            this.setFrameURL({ url: this.rawURL });
            this.titleFromDetails(details);
            return this;
        }

        // A new page is completely reloaded from scratch, reset all.
        this.largeMediaTimer.off();
        this.disposeFrameStores();
        this.init(this.tabId, details);
        return this;
    }

    dispose() {
        this.tabHostname = '';
        this.title = '';
        this.rawURL = '';
        this.hostnameDetailsMap.dispose();
        this.netFilteringCache.empty();
        this.allowLargeMediaElementsUntil = Date.now();
        this.allowLargeMediaElementsRegex = undefined;
        this.largeMediaTimer.off();
        this.disposeFrameStores();
        this.journalTimer.off();
        this.journal = [];
        this.journalLastUncommittedOrigin = undefined;
        this.journalLastCommitted = this.journalLastUncommitted = -1;
        if ( PageStore.junkyard.length < PageStore.junkyardMax ) {
            PageStore.junkyard.push(this);
        }
        return null;
    }

    titleFromDetails(details) {
        if (
            details instanceof Object === false ||
            details.title === undefined
        ) {
            return false;
        }
        this.title = orphanizeString(details.title.slice(0, 128));
        return true;
    }

    disposeFrameStores() {
        for ( const frameStore of this.frames.values() ) {
            frameStore.dispose();
        }
        this.frames.clear();
    }

    getFrameStore(frameId) {
        return this.frames.get(frameId) || null;
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1858
    //   Mind that setFrameURL() can be called from navigation event handlers.
    setFrameURL(details) {
        let { frameId, url, parentFrameId } = details;
        if ( frameId === undefined ) { frameId = 0; }
        if ( parentFrameId === undefined ) { parentFrameId = -1; }
        let frameStore = this.frames.get(frameId);
        if ( frameStore !== undefined ) {
            if ( url === frameStore.rawURL ) {
                frameStore.parentId = parentFrameId;
            } else {
                frameStore.init(url, parentFrameId);
            }
            return frameStore;
        }
        frameStore = FrameStore.factory(url, parentFrameId);
        this.frames.set(frameId, frameStore);
        this.frameAddCount += 1;
        if ( url.startsWith('about:') ) {
            frameStore.updateURL(this.getEffectiveFrameURL({ frameId }));
        }
        if ( (this.frameAddCount & 0b111111) === 0 ) {
            this.pruneFrames();
        }
        return frameStore;
    }

    getEffectiveFrameURL(sender) {
        let { frameId } = sender;
        for (;;) {
            const frameStore = this.getFrameStore(frameId);
            if ( frameStore === null ) { break; }
            if ( frameStore.rawURL.startsWith('about:') === false ) {
                return frameStore.rawURL;
            }
            frameId = frameStore.parentId;
            if ( frameId === -1 ) { break; }
        }
        return sender.frameURL;
    }

    getFrameAncestorDetails(frameId) {
        if ( frameId === 0 ) { return []; }
        const out = [];
        for (;;) {
            const frameStore = this.getFrameStore(frameId);
            if ( frameStore === null ) { break; }
            const { domain, hostname } = frameStore;
            if ( hostname !== undefined ) {
                out.push({ domain, hostname });
            }
            frameId = frameStore.parentId;
        }
        return out.slice(1);
    }

    // There is no event to tell us a specific subframe has been removed from
    // the main document. The code below will remove subframes which are no
    // longer present in the root document. Removing obsolete subframes is
    // not a critical task, so this is executed just once on a while, to avoid
    // bloated dictionary of subframes.
    // A TTL is used to avoid race conditions when new iframes are added
    // through the webRequest API but still not yet visible through the
    // webNavigation API.
    async pruneFrames() {
        let entries;
        try {
            entries = await webext.webNavigation.getAllFrames({
                tabId: this.tabId
            });
        } catch {
        }
        if ( Array.isArray(entries) === false ) { return; }
        const toKeep = new Set();
        for ( const { frameId } of entries ) {
            toKeep.add(frameId);
        }
        const obsolete = Date.now() - 60000;
        for ( const [ frameId, { t0 } ] of this.frames ) {
            if ( toKeep.has(frameId) || t0 >= obsolete ) { continue; }
            this.frames.delete(frameId);
        }
    }

    getNetFilteringSwitch() {
        return µb.tabContextManager
                 .mustLookup(this.tabId)
                 .getNetFilteringSwitch();
    }

    toggleNetFilteringSwitch(url, scope, state) {
        µb.toggleNetFilteringSwitch(url, scope, state);
        this.netFilteringCache.empty();
    }

    shouldApplyCosmeticFilters(frameId = 0) {
        if ( this._noCosmeticFiltering === undefined ) {
            this._noCosmeticFiltering = this.getNetFilteringSwitch() === false;
            if ( this._noCosmeticFiltering === false ) {
                this._noCosmeticFiltering = sessionSwitches.evaluateZ(
                    'no-cosmetic-filtering',
                    this.tabHostname
                ) === true;
                if ( this._noCosmeticFiltering && logger.enabled ) {
                    µb.filteringContext
                        .duplicate()
                        .fromTabId(this.tabId)
                        .setURL(this.rawURL)
                        .setRealm('cosmetic')
                        .setType('dom')
                        .setFilter(sessionSwitches.toLogData())
                        .toLogger();
                }
            }
        }
        if ( this._noCosmeticFiltering ) { return false; }
        if ( frameId === -1 ) { return true; }
        // Cosmetic filtering can be effectively disabled when both specific
        // and generic cosmetic filters are disabled.
        return this.shouldApplySpecificCosmeticFilters(frameId) ||
               this.shouldApplyGenericCosmeticFilters(frameId);
    }

    shouldApplySpecificCosmeticFilters(frameId) {
        if ( this.shouldApplyCosmeticFilters(-1) === false ) { return false; }
        const frameStore = this.getFrameStore(frameId);
        if ( frameStore === null ) { return false; }
        return frameStore.shouldApplySpecificCosmeticFilters(this.tabId);
    }

    shouldApplyGenericCosmeticFilters(frameId) {
        if ( this.shouldApplyCosmeticFilters(-1) === false ) { return false; }
        const frameStore = this.getFrameStore(frameId);
        if ( frameStore === null ) { return false; }
        return frameStore.shouldApplyGenericCosmeticFilters(this.tabId);
    }

    // https://github.com/gorhill/uBlock/issues/2105
    //   Be sure to always include the current page's hostname -- it might not
    //   be present when the page itself is pulled from the browser's
    //   short-term memory cache.
    getAllHostnameDetails() {
        if (
            this.hostnameDetailsMap.has(this.tabHostname) === false &&
            isNetworkURI(this.rawURL)
        ) {
            this.hostnameDetailsMap.set(
                this.tabHostname,
                HostnameDetails.factory(this.tabHostname)
            );
        }
        return this.hostnameDetailsMap;
    }

    injectLargeMediaElementScriptlet() {
        vAPI.tabs.executeScript(this.tabId, {
            file: '/js/scriptlets/load-large-media-interactive.js',
            allFrames: true,
            runAt: 'document_idle',
        });
        contextMenu.update(this.tabId);
    }

    temporarilyAllowLargeMediaElements(state) {
        this.largeMediaCount = 0;
        contextMenu.update(this.tabId);
        if ( state ) {
            this.allowLargeMediaElementsUntil = 0;
            this.allowLargeMediaElementsRegex = undefined;
        } else {
            this.allowLargeMediaElementsUntil = Date.now();
        }
        vAPI.tabs.executeScript(this.tabId, {
            file: '/js/scriptlets/load-large-media-all.js',
            allFrames: true,
        });
    }

    // https://github.com/gorhill/uBlock/issues/2053
    //   There is no way around using journaling to ensure we deal properly with
    //   potentially out of order navigation events vs. network request events.
    journalAddRequest(fctxt, result) {
        const hostname = fctxt.getHostname();
        if ( hostname === '' ) { return; }
        this.journal.push(hostname, result, fctxt.itype);
        this.journalTimer.on(µb.hiddenSettings.requestJournalProcessPeriod);
    }

    journalAddRootFrame(type, url) {
        if ( type === 'committed' ) {
            this.journalLastCommitted = this.journal.length;
            if (
                this.journalLastUncommitted !== -1 &&
                this.journalLastUncommitted < this.journalLastCommitted &&
                this.journalLastUncommittedOrigin === hostnameFromURI(url)
            ) {
                this.journalLastCommitted = this.journalLastUncommitted;
            }
        } else if ( type === 'uncommitted' ) {
            const newOrigin = hostnameFromURI(url);
            if (
                this.journalLastUncommitted === -1 ||
                this.journalLastUncommittedOrigin !== newOrigin
            ) {
                this.journalLastUncommitted = this.journal.length;
                this.journalLastUncommittedOrigin = newOrigin;
            }
        }
        this.journalTimer.offon(µb.hiddenSettings.requestJournalProcessPeriod);
    }

    journalProcess() {
        this.journalTimer.off();

        const journal = this.journal;
        const pivot = Math.max(0, this.journalLastCommitted);
        const now = Date.now();
        const { SCRIPT, SUB_FRAME, OBJECT } = µb.FilteringContext;
        let aggregateAllowed = 0;
        let aggregateBlocked = 0;

        // Everything after pivot originates from current page.
        for ( let i = pivot; i < journal.length; i += 3 ) {
            const hostname = journal[i+0];
            let hnDetails = this.hostnameDetailsMap.get(hostname);
            if ( hnDetails === undefined ) {
                hnDetails = HostnameDetails.factory(hostname);
                this.hostnameDetailsMap.set(hostname, hnDetails);
                this.contentLastModified = now;
            }
            const blocked = journal[i+1] === 1;
            const itype = journal[i+2];
            if ( itype === SCRIPT ) {
                hnDetails.counts.inc(blocked, 'script');
                this.counts.inc(blocked, 'script');
            } else if ( itype === SUB_FRAME || itype === OBJECT ) {
                hnDetails.counts.inc(blocked, 'frame');
                this.counts.inc(blocked, 'frame');
            } else {
                hnDetails.counts.inc(blocked);
                this.counts.inc(blocked);
            }
            if ( blocked ) {
                aggregateBlocked += 1;
            } else {
                aggregateAllowed += 1;
            }
        }
        this.journalLastUncommitted = this.journalLastCommitted = -1;

        // https://github.com/chrisaljoudi/uBlock/issues/905#issuecomment-76543649
        //   No point updating the badge if it's not being displayed.
        if ( aggregateBlocked !== 0 && µb.userSettings.showIconBadge ) {
            µb.updateToolbarIcon(this.tabId, 0x02);
        }

        // Everything before pivot does not originate from current page -- we
        // still need to bump global blocked/allowed counts.
        for ( let i = 0; i < pivot; i += 3 ) {
            if ( journal[i+1] === 1 ) {
                aggregateBlocked += 1;
            } else {
                aggregateAllowed += 1;
            }
        }
        if ( aggregateAllowed || aggregateBlocked ) {
            µb.incrementRequestStats(aggregateBlocked, aggregateAllowed);
        }
        journal.length = 0;
    }

    filterRequest(fctxt) {
        fctxt.filter = undefined;
        fctxt.redirectURL = undefined;

        if ( this.getNetFilteringSwitch(fctxt) === false ) {
            return 0;
        }

        if (
            fctxt.itype === fctxt.CSP_REPORT &&
            this.filterCSPReport(fctxt) === 1
        ) {
            return 1;
        }

        if (
            (fctxt.itype & fctxt.FONT_ANY) !== 0 &&
            this.filterFont(fctxt) === 1 )
        {
            return 1;
        }

        if (
            fctxt.itype === fctxt.SCRIPT &&
            this.filterScripting(fctxt, true) === 1
        ) {
            return 1;
        }

        const cacheableResult =
            this.cacheableResults.has(fctxt.itype) &&
            fctxt.aliasURL === undefined;

        if ( cacheableResult ) {
            const entry = this.netFilteringCache.lookupResult(fctxt);
            if ( entry !== undefined ) {
                fctxt.redirectURL = entry.redirectURL;
                fctxt.filter = entry.logData;
                return entry.result;
            }
        }

        const requestType = fctxt.type;
        const loggerEnabled = logger.enabled;

        // Dynamic URL filtering.
        let result = sessionURLFiltering.evaluateZ(
            fctxt.getTabHostname(),
            fctxt.url,
            requestType
        );
        if ( result !== 0 && loggerEnabled ) {
            fctxt.filter = sessionURLFiltering.toLogData();
        }

        // Dynamic hostname/type filtering.
        if ( result === 0 && µb.userSettings.advancedUserEnabled ) {
            result = sessionFirewall.evaluateCellZY(
                fctxt.getTabHostname(),
                fctxt.getHostname(),
                requestType
            );
            if ( result !== 0 && result !== 3 && loggerEnabled ) {
                fctxt.filter = sessionFirewall.toLogData();
            }
        }

        // Static filtering has lowest precedence.
        const snfe = staticNetFilteringEngine;
        if ( result === 0 || result === 3 ) {
            result = snfe.matchRequest(fctxt);
            if ( result !== 0 ) {
                if ( loggerEnabled ) {
                    fctxt.setFilter(snfe.toLogData());
                }
                // https://github.com/uBlockOrigin/uBlock-issues/issues/943
                //   Blanket-except blocked aliased canonical hostnames?
                if (
                    result === 1 &&
                    fctxt.aliasURL !== undefined &&
                    snfe.isBlockImportant() === false &&
                    this.shouldExceptCname(fctxt)
                ) {
                    return 2;
                }
            }
        }

        // Click-to-load?
        // When frameId is not -1, the resource is always sub_frame.
        if ( result === 1 && fctxt.frameId !== -1 ) {
            const frameStore = this.getFrameStore(fctxt.frameId);
            if ( frameStore !== null && frameStore.clickToLoad ) {
                result = 2;
                if ( loggerEnabled ) {
                    fctxt.pushFilter({
                        result,
                        source: 'network',
                        raw: 'click-to-load',
                    });
                }
            }
        }

        // Modifier(s)?
        // A modifier is an action which transform the original network request.
        // https://github.com/gorhill/uBlock/issues/949
        //   Redirect blocked request?
        // https://github.com/uBlockOrigin/uBlock-issues/issues/760
        //   Redirect non-blocked request?
        if ( (fctxt.itype & fctxt.INLINE_ANY) === 0 ) {
            if ( result === 1 ) {
                this.redirectBlockedRequest(fctxt);
            } else {
                this.redirectNonBlockedRequest(fctxt);
            }
        }

        if ( cacheableResult ) {
            this.netFilteringCache.rememberResult(fctxt, result);
        } else if ( result === 1 && this.collapsibleResources.has(fctxt.itype) ) {
            this.netFilteringCache.rememberBlock(fctxt);
        }

        return result;
    }

    filterOnHeaders(fctxt, headers) {
        fctxt.filter = undefined;

        if ( this.getNetFilteringSwitch(fctxt) === false ) { return 0; }

        let result = staticNetFilteringEngine.matchHeaders(fctxt, headers);
        if ( result === 0 ) { return 0; }

        const loggerEnabled = logger.enabled;
        if ( loggerEnabled ) {
            fctxt.filter = staticNetFilteringEngine.toLogData();
        }

        // Dynamic filtering allow rules
        // URL filtering
        if (
            result === 1 &&
            sessionURLFiltering.evaluateZ(
                fctxt.getTabHostname(),
                fctxt.url,
                fctxt.type
            ) === 2
        ) {
            result = 2;
            if ( loggerEnabled ) {
                fctxt.filter = sessionURLFiltering.toLogData();
            }
        }
        // Hostname filtering
        if (
            result === 1 &&
            µb.userSettings.advancedUserEnabled &&
            sessionFirewall.evaluateCellZY(
                fctxt.getTabHostname(),
                fctxt.getHostname(),
                fctxt.type
            ) === 2
        ) {
            result = 2;
            if ( loggerEnabled ) {
                fctxt.filter = sessionFirewall.toLogData();
            }
        }

        return result;
    }

    redirectBlockedRequest(fctxt) {
        const directives = staticNetFilteringEngine.redirectRequest(redirectEngine, fctxt) || [];
        if ( this.urlSkippableResources.has(fctxt.itype) ) {
            staticNetFilteringEngine.urlSkip(fctxt, true, directives);
        }
        if ( directives.length === 0 ) { return; }
        if ( logger.enabled !== true ) { return; }
        fctxt.pushFilters(directives.map(a => a.logData()));
        if ( fctxt.redirectURL === undefined ) { return; }
        fctxt.pushFilter({
            source: 'redirect',
            raw: directives[directives.length-1].value
        });
    }

    redirectNonBlockedRequest(fctxt) {
        const directives = [];
        staticNetFilteringEngine.transformURL(fctxt, directives);
        if ( staticNetFilteringEngine.hasQuery(fctxt) ) {
            staticNetFilteringEngine.filterQuery(fctxt, directives);
        }
        if ( this.urlSkippableResources.has(fctxt.itype) ) {
            staticNetFilteringEngine.urlSkip(fctxt, false, directives);
        }
        if ( directives.length === 0 ) { return; }
        if ( logger.enabled !== true ) { return; }
        fctxt.pushFilters(directives.map(a => a.logData()));
        if ( fctxt.redirectURL === undefined ) { return; }
        fctxt.pushFilter({
            source: 'redirect',
            raw: fctxt.redirectURL
        });
    }

    skipMainDocument(fctxt, blocked) {
        const directives = staticNetFilteringEngine.urlSkip(fctxt, blocked);
        if ( directives === undefined ) { return; }
        fctxt.pushFilters(directives.map(a => a.logData()));
        if ( fctxt.redirectURL === undefined ) { return; }
        fctxt.pushFilter({
            source: 'redirect',
            raw: fctxt.redirectURL
        });
    }

    filterCSPReport(fctxt) {
        if (
            sessionSwitches.evaluateZ(
                'no-csp-reports',
                fctxt.getHostname()
            )
        ) {
            if ( logger.enabled ) {
                fctxt.filter = sessionSwitches.toLogData();
            }
            return 1;
        }
        return 0;
    }

    filterFont(fctxt) {
        if ( fctxt.itype === fctxt.FONT ) {
            this.remoteFontCount += 1;
        }
        if (
            sessionSwitches.evaluateZ(
                'no-remote-fonts',
                fctxt.getTabHostname()
            ) !== false
        ) {
            if ( logger.enabled ) {
                fctxt.filter = sessionSwitches.toLogData();
            }
            return 1;
        }
        return 0;
    }

    filterScripting(fctxt, netFiltering) {
        fctxt.filter = undefined;
        if ( netFiltering === undefined ) {
            netFiltering = this.getNetFilteringSwitch(fctxt);
        }
        if (
            netFiltering === false ||
            sessionSwitches.evaluateZ(
                'no-scripting',
                fctxt.getTabHostname()
            ) === false
        ) {
            return 0;
        }
        if ( logger.enabled ) {
            fctxt.filter = sessionSwitches.toLogData();
        }
        return 1;
    }

    // The caller is responsible to check whether filtering is enabled or not.
    filterLargeMediaElement(fctxt, headers) {
        fctxt.filter = undefined;
        if ( this.allowLargeMediaElementsUntil === 0 ) { return 0; }
        if ( sessionSwitches.evaluateZ('no-large-media', fctxt.getTabHostname() ) !== true ) {
            this.allowLargeMediaElementsUntil = 0;
            return 0;
        }
        // XHR-based streaming is never blocked but we want to prevent autoplay
        if ( fctxt.itype === fctxt.XMLHTTPREQUEST ) {
            const ctype = headers.contentType;
            if ( ctype.startsWith('audio/') || ctype.startsWith('video/') ) {
                this.largeMediaTimer.on(500);
            }
            return 0;
        }
        if ( Date.now() < this.allowLargeMediaElementsUntil ) {
            if ( fctxt.itype === fctxt.MEDIA ) {
                const sources = this.allowLargeMediaElementsRegex instanceof RegExp
                    ? [ this.allowLargeMediaElementsRegex.source ]
                    : [];
                sources.push('^' + µb.escapeRegex(fctxt.url));
                this.allowLargeMediaElementsRegex = new RegExp(sources.join('|'));
            }
            return 0;
        }
        // Disregard large media elements previously allowed: for example, to
        // seek inside a previously allowed audio/video.
        if (
            this.allowLargeMediaElementsRegex instanceof RegExp &&
            this.allowLargeMediaElementsRegex.test(fctxt.url)
        ) {
            return 0;
        }
        // Regardless of whether a media is blocked, we want to prevent autoplay
        if ( fctxt.itype === fctxt.MEDIA ) {
            this.largeMediaTimer.on(500);
        }
        const size = headers.contentLength;
        if ( isNaN(size) ) {
            return µb.userSettings.largeMediaSize === 0 ? 1 : 0;
        }
        if ( (size >>> 10) < µb.userSettings.largeMediaSize ) { return 0; }
        this.largeMediaCount += 1;
        this.largeMediaTimer.on(500);
        if ( logger.enabled ) {
            fctxt.filter = sessionSwitches.toLogData();
        }
        return 1;
    }

    clickToLoad(frameId, frameURL) {
        let frameStore = this.getFrameStore(frameId);
        if ( frameStore === null ) {
            frameStore = this.setFrameURL({ frameId, url: frameURL });
        }
        this.netFilteringCache.forgetResult(
            this.tabHostname,
            'sub_frame',
            frameURL
        );
        frameStore.clickToLoad = true;
    }

    shouldExceptCname(fctxt) {
        let exceptCname;
        let frameStore;
        if ( fctxt.docId !== undefined ) {
            frameStore = this.getFrameStore(fctxt.docId);
            if ( frameStore instanceof Object ) {
                exceptCname = frameStore.exceptCname;
            }
        }
        if ( exceptCname === undefined ) {
            const result = staticNetFilteringEngine.matchRequestReverse(
                'cname',
                frameStore instanceof Object
                    ? frameStore.rawURL
                    : fctxt.getDocOrigin()
            );
            exceptCname = result === 2
                ? staticNetFilteringEngine.toLogData()
                : false;
            if ( frameStore instanceof Object ) {
                frameStore.exceptCname = exceptCname;
            }
        }
        if ( exceptCname === false ) { return false; }
        if ( exceptCname instanceof Object ) {
            fctxt.setFilter(exceptCname);
        }
        return true;
    }

    getBlockedResources(request, response) {
        const normalURL = µb.normalizeTabURL(this.tabId, request.frameURL);
        const resources = request.resources;
        const fctxt = µb.filteringContext;
        fctxt.fromTabId(this.tabId)
             .setDocOriginFromURL(normalURL);
        // Force some resources to go through the filtering engine in order to
        // populate the blocked-resources cache. This is required because for
        // some resources it's not possible to detect whether they were blocked
        // content script-side (i.e. `iframes` -- unlike `img`).
        if ( Array.isArray(resources) && resources.length !== 0 ) {
            for ( const resource of resources ) {
                this.filterRequest(
                    fctxt.setType(resource.type).setURL(resource.url)
                );
            }
        }
        if ( this.netFilteringCache.hash === response.hash ) { return; }
        response.hash = this.netFilteringCache.hash;
        response.blockedResources =
            this.netFilteringCache.lookupAllBlocked(fctxt.getDocHostname());
    }

    cacheableResults = new Set([
        µb.FilteringContext.SUB_FRAME
    ]);

    collapsibleResources = new Set([
        µb.FilteringContext.IMAGE,
        µb.FilteringContext.MEDIA,
        µb.FilteringContext.OBJECT,
        µb.FilteringContext.SUB_FRAME,
    ]);

    urlSkippableResources = new Set([
        µb.FilteringContext.IMAGE,
        µb.FilteringContext.MAIN_FRAME,
        µb.FilteringContext.MEDIA,
        µb.FilteringContext.OBJECT,
        µb.FilteringContext.OTHER,
        µb.FilteringContext.SUB_FRAME,
    ]);

    // To mitigate memory churning
    static junkyard = [];
    static junkyardMax = 10;
};

/******************************************************************************/

export { PageStore };
