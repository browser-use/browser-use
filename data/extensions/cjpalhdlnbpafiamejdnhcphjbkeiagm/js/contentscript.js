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

/*******************************************************************************

              +--> domCollapser
              |
              |
  domWatcher--+
              |                  +-- domSurveyor
              |                  |
              +--> domFilterer --+-- [domLogger]
                        |        |
                        |        +-- [domInspector]
                        |
             [domProceduralFilterer]

  domWatcher:
    Watches for changes in the DOM, and notify the other components about these
    changes.

  domCollapser:
    Enforces the collapsing of DOM elements for which a corresponding
    resource was blocked through network filtering.

  domFilterer:
    Enforces the filtering of DOM elements, by feeding it cosmetic filters.

  domProceduralFilterer:
    Enforce the filtering of DOM elements through procedural cosmetic filters.
    Loaded on demand, only when needed.

  domSurveyor:
    Surveys the DOM to find new cosmetic filters to apply to the current page.

  domLogger:
    Surveys the page to find and report the injected cosmetic filters blocking
    actual elements on the current page. This component is dynamically loaded
    IF AND ONLY IF uBO's logger is opened.

  If page is whitelisted:
    - domWatcher: off
    - domCollapser: off
    - domFilterer: off
    - domSurveyor: off
    - domLogger: off

  I verified that the code in this file is completely flushed out of memory
  when a page is whitelisted.

  If cosmetic filtering is disabled:
    - domWatcher: on
    - domCollapser: on
    - domFilterer: off
    - domSurveyor: off
    - domLogger: off

  If generic cosmetic filtering is disabled:
    - domWatcher: on
    - domCollapser: on
    - domFilterer: on
    - domSurveyor: off
    - domLogger: on if uBO logger is opened

  If generic cosmetic filtering is enabled:
    - domWatcher: on
    - domCollapser: on
    - domFilterer: on
    - domSurveyor: on
    - domLogger: on if uBO logger is opened

  Additionally, the domSurveyor can turn itself off once it decides that
  it has become pointless (repeatedly not finding new cosmetic filters).

  The domFilterer makes use of platform-dependent user stylesheets[1].

  [1] "user stylesheets" refer to local CSS rules which have priority over,
       and can't be overridden by a web page's own CSS rules.

*/

// Abort execution if our global vAPI object does not exist.
//   https://github.com/chrisaljoudi/uBlock/issues/456
//   https://github.com/gorhill/uBlock/issues/2029

// >>>>>>>> start of HUGE-IF-BLOCK
if ( typeof vAPI === 'object' && !vAPI.contentScript ) {

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

vAPI.contentScript = true;

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/688#issuecomment-663657508
{
    let context = self;
    try {
        while (
            context !== self.top &&
            context.location.href.startsWith('about:blank') &&
            context.parent.location.href
        ) {
            context = context.parent;
        }
    } catch {
    }
    vAPI.effectiveSelf = context;
}

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

vAPI.userStylesheet = {
    added: new Set(),
    removed: new Set(),
    apply: function(callback) {
        if ( this.added.size === 0 && this.removed.size === 0 ) { return; }
        vAPI.messaging.send('vapi', {
            what: 'userCSS',
            add: Array.from(this.added),
            remove: Array.from(this.removed),
        }).then(( ) => {
            if ( callback instanceof Function === false ) { return; }
            callback();
        });
        this.added.clear();
        this.removed.clear();
    },
    add: function(cssText, now) {
        if ( cssText === '' ) { return; }
        this.added.add(cssText);
        if ( now ) { this.apply(); }
    },
    remove: function(cssText, now) {
        if ( cssText === '' ) { return; }
        this.removed.add(cssText);
        if ( now ) { this.apply(); }
    }
};

/******************************************************************************/
/******************************************************************************/
/*******************************************************************************

  The purpose of SafeAnimationFrame is to take advantage of the behavior of
  window.requestAnimationFrame[1]. If we use an animation frame as a timer,
  then this timer is described as follow:

  - time events are throttled by the browser when the viewport is not visible --
    there is no point for uBO to play with the DOM if the document is not
    visible.
  - time events are micro tasks[2].
  - time events are synchronized to monitor refresh, meaning that they can fire
    at most 1/60 (typically).

  If a delay value is provided, a plain timer is first used. Plain timers are
  macro-tasks, so this is good when uBO wants to yield to more important tasks
  on a page. Once the plain timer elapse, an animation frame is used to trigger
  the next time at which to execute the job.

  [1] https://developer.mozilla.org/en-US/docs/Web/API/window/requestAnimationFrame
  [2] https://jakearchibald.com/2015/tasks-microtasks-queues-and-schedules/

*/

// https://github.com/gorhill/uBlock/issues/2147

vAPI.SafeAnimationFrame = class {
    constructor(callback) {
        this.fid = this.tid = undefined;
        this.callback = callback;
    }
    start(delay) {
        if ( self.vAPI instanceof Object === false ) { return; }
        if ( delay === undefined ) {
            if ( this.fid === undefined ) {
                this.fid = requestAnimationFrame(( ) => { this.onRAF(); } );
            }
            if ( this.tid === undefined ) {
                this.tid = vAPI.setTimeout(( ) => { this.onSTO(); }, 20000);
            }
            return;
        }
        if ( this.fid === undefined && this.tid === undefined ) {
            this.tid = vAPI.setTimeout(( ) => { this.macroToMicro(); }, delay);
        }
    }
    clear() {
        if ( this.fid !== undefined ) {
            cancelAnimationFrame(this.fid);
            this.fid = undefined;
        }
        if ( this.tid !== undefined ) {
            clearTimeout(this.tid);
            this.tid = undefined;
        }
    }
    macroToMicro() {
        this.tid = undefined;
        this.start();
    }
    onRAF() {
        if ( this.tid !== undefined ) {
            clearTimeout(this.tid);
            this.tid = undefined;
        }
        this.fid = undefined;
        this.callback();
    }
    onSTO() {
        if ( this.fid !== undefined ) {
            cancelAnimationFrame(this.fid);
            this.fid = undefined;
        }
        this.tid = undefined;
        this.callback();
    }
};

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/552
//   Listen and report CSP violations so that blocked resources through CSP
//   are properly reported in the logger.

{
    const newEvents = new Set();
    const allEvents = new Set();
    let timer;

    const send = function() {
        if ( self.vAPI instanceof Object === false ) { return; }
        vAPI.messaging.send('scriptlets', {
            what: 'securityPolicyViolation',
            type: 'net',
            docURL: document.location.href,
            violations: Array.from(newEvents),
        }).then(response => {
            if ( response === true ) { return; }
            stop();
        });
        for ( const event of newEvents ) {
            allEvents.add(event);
        }
        newEvents.clear();
    };

    const sendAsync = function() {
        if ( timer !== undefined ) { return; }
        timer = self.requestIdleCallback(
            ( ) => { timer = undefined; send(); },
            { timeout: 2063 }
        );
    };

    const listener = function(ev) {
        if ( ev.isTrusted !== true ) { return; }
        if ( ev.disposition !== 'enforce' ) { return; }
        const json = JSON.stringify({
            url: ev.blockedURL || ev.blockedURI,
            policy: ev.originalPolicy,
            directive: ev.effectiveDirective || ev.violatedDirective,
        });
        if ( allEvents.has(json) ) { return; }
        newEvents.add(json);
        sendAsync();
    };

    const stop = function() {
        newEvents.clear();
        allEvents.clear();
        if ( timer !== undefined ) {
            self.cancelIdleCallback(timer);
            timer = undefined;
        }
        document.removeEventListener('securitypolicyviolation', listener);
        if ( vAPI ) { vAPI.shutdown.remove(stop); }
    };

    document.addEventListener('securitypolicyviolation', listener);
    vAPI.shutdown.add(stop);

    // We need to call at least once to find out whether we really need to
    // listen to CSP violations.
    sendAsync();
}

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// vAPI.domWatcher

{
    vAPI.domMutationTime = Date.now();

    const addedNodeLists = [];
    const removedNodeLists = [];
    const addedNodes = [];
    const ignoreTags = new Set([ 'br', 'head', 'link', 'meta', 'script', 'style' ]);
    const listeners = [];

    let domLayoutObserver;
    let listenerIterator = [];
    let listenerIteratorDirty = false;
    let removedNodes = false;
    let safeObserverHandlerTimer;

    const safeObserverHandler = function() {
        let i = addedNodeLists.length;
        while ( i-- ) {
            const nodeList = addedNodeLists[i];
            let iNode = nodeList.length;
            while ( iNode-- ) {
                const node = nodeList[iNode];
                if ( node.nodeType !== 1 ) { continue; }
                if ( ignoreTags.has(node.localName) ) { continue; }
                if ( node.parentElement === null ) { continue; }
                addedNodes.push(node);
            }
        }
        addedNodeLists.length = 0;
        i = removedNodeLists.length;
        while ( i-- && removedNodes === false ) {
            const nodeList = removedNodeLists[i];
            let iNode = nodeList.length;
            while ( iNode-- ) {
                if ( nodeList[iNode].nodeType !== 1 ) { continue; }
                removedNodes = true;
                break;
            }
        }
        removedNodeLists.length = 0;
        if ( addedNodes.length === 0 && removedNodes === false ) { return; }
        for ( const listener of getListenerIterator() ) {
            try { listener.onDOMChanged(addedNodes, removedNodes); }
            catch { }
        }
        addedNodes.length = 0;
        removedNodes = false;
        vAPI.domMutationTime = Date.now();
    };

    // https://github.com/chrisaljoudi/uBlock/issues/205
    //   Do not handle added node directly from within mutation observer.
    const observerHandler = function(mutations) {
        let i = mutations.length;
        while ( i-- ) {
            const mutation = mutations[i];
            let nodeList = mutation.addedNodes;
            if ( nodeList.length !== 0 ) {
                addedNodeLists.push(nodeList);
            }
            nodeList = mutation.removedNodes;
            if ( nodeList.length !== 0 ) {
                removedNodeLists.push(nodeList);
            }
        }
        if ( addedNodeLists.length !== 0 || removedNodeLists.length !== 0 ) {
            safeObserverHandlerTimer.start(
                addedNodeLists.length < 100 ? 1 : undefined
            );
        }
    };

    const startMutationObserver = function() {
        if ( domLayoutObserver !== undefined ) { return; }
        domLayoutObserver = new MutationObserver(observerHandler);
        domLayoutObserver.observe(document, {
            //attributeFilter: [ 'class', 'id' ],
            //attributes: true,
            childList: true,
            subtree: true
        });
        safeObserverHandlerTimer = new vAPI.SafeAnimationFrame(safeObserverHandler);
        vAPI.shutdown.add(cleanup);
    };

    const stopMutationObserver = function() {
        if ( domLayoutObserver === undefined ) { return; }
        cleanup();
        vAPI.shutdown.remove(cleanup);
    };

    const getListenerIterator = function() {
        if ( listenerIteratorDirty ) {
            listenerIterator = listeners.slice();
            listenerIteratorDirty = false;
        }
        return listenerIterator;
    };

    const addListener = function(listener) {
        if ( listeners.indexOf(listener) !== -1 ) { return; }
        listeners.push(listener);
        listenerIteratorDirty = true;
        if ( domLayoutObserver === undefined ) { return; }
        try { listener.onDOMCreated(); }
        catch { }
        startMutationObserver();
    };

    const removeListener = function(listener) {
        const pos = listeners.indexOf(listener);
        if ( pos === -1 ) { return; }
        listeners.splice(pos, 1);
        listenerIteratorDirty = true;
        if ( listeners.length === 0 ) {
            stopMutationObserver();
        }
    };

    const cleanup = function() {
        if ( domLayoutObserver !== undefined ) {
            domLayoutObserver.disconnect();
            domLayoutObserver = undefined;
        }
        if ( safeObserverHandlerTimer !== undefined ) {
            safeObserverHandlerTimer.clear();
            safeObserverHandlerTimer = undefined;
        }
    };

    const start = function() {
        for ( const listener of getListenerIterator() ) {
            try { listener.onDOMCreated(); }
            catch { }
        }
        startMutationObserver();
    };

    vAPI.domWatcher = { start, addListener, removeListener };
}

/******************************************************************************/
/******************************************************************************/
/*******************************************************************************

  The DOM filterer is the heart of uBO's cosmetic filtering.

  DOMFilterer: adds procedural cosmetic filtering

*/

vAPI.hideStyle = 'display:none!important;';

vAPI.DOMFilterer = class {
    constructor() {
        this.commitTimer = new vAPI.SafeAnimationFrame(
            ( ) => { this.commitNow(); }
        );
        this.disabled = false;
        this.listeners = [];
        this.stylesheets = [];
        this.exceptedCSSRules = [];
        this.exceptions = [];
        this.convertedProceduralFilters = [];
        this.proceduralFilterer = null;
    }

    explodeCSS(css) {
        const out = [];
        const cssHide = `{${vAPI.hideStyle}}`;
        const blocks = css.trim().split(/\n\n+/);
        for ( const block of blocks ) {
            if ( block.endsWith(cssHide) === false ) { continue; }
            out.push(block.slice(0, -cssHide.length).trim());
        }
        return out;
    }

    addCSS(css, details = {}) {
        if ( typeof css !== 'string' || css.length === 0 ) { return; }
        if ( this.stylesheets.includes(css) ) { return; }
        this.stylesheets.push(css);
        if ( details.mustInject && this.disabled === false ) {
            vAPI.userStylesheet.add(css);
        }
        if ( this.hasListeners() === false ) { return; }
        if ( details.silent ) { return; }
        this.triggerListeners({ declarative: this.explodeCSS(css) });
    }

    exceptCSSRules(exceptions) {
        if ( exceptions.length === 0 ) { return; }
        this.exceptedCSSRules.push(...exceptions);
        if ( this.hasListeners() ) {
            this.triggerListeners({ exceptions });
        }
    }

    addListener(listener) {
        if ( this.listeners.indexOf(listener) !== -1 ) { return; }
        this.listeners.push(listener);
    }

    removeListener(listener) {
        const pos = this.listeners.indexOf(listener);
        if ( pos === -1 ) { return; }
        this.listeners.splice(pos, 1);
    }

    hasListeners() {
        return this.listeners.length !== 0;
    }

    triggerListeners(changes) {
        for ( const listener of this.listeners ) {
            listener.onFiltersetChanged(changes);
        }
    }

    toggle(state, callback) {
        if ( state === undefined ) { state = this.disabled; }
        if ( state !== this.disabled ) { return; }
        this.disabled = !state;
        const uss = vAPI.userStylesheet;
        for ( const css of this.stylesheets ) {
            if ( this.disabled ) {
                uss.remove(css);
            } else {
                uss.add(css);
            }
        }
        uss.apply(callback);
    }

    // Here we will deal with:
    // - Injecting low priority user styles;
    // - Notifying listeners about changed filterset.
    // https://www.reddit.com/r/uBlockOrigin/comments/9jj0y1/no_longer_blocking_ads/
    //   Ensure vAPI is still valid -- it can go away by the time we are
    //   called, since the port could be force-disconnected from the main
    //   process. Another approach would be to have vAPI.SafeAnimationFrame
    //   register a shutdown job: to evaluate. For now I will keep the fix
    //   trivial.
    commitNow() {
        this.commitTimer.clear();
        if ( vAPI instanceof Object === false ) { return; }
        vAPI.userStylesheet.apply();
        if ( this.proceduralFilterer instanceof Object ) {
            this.proceduralFilterer.commitNow();
        }
    }

    commit(commitNow) {
        if ( commitNow ) {
            this.commitTimer.clear();
            this.commitNow();
        } else {
            this.commitTimer.start();
        }
    }

    proceduralFiltererInstance() {
        if ( this.proceduralFilterer instanceof Object === false ) {
            if ( vAPI.DOMProceduralFilterer instanceof Object === false ) {
                return null;
            }
            this.proceduralFilterer = new vAPI.DOMProceduralFilterer(this);
        }
        return this.proceduralFilterer;
    }

    addProceduralSelectors(selectors) {
        const procedurals = [];
        for ( const raw of selectors ) {
            procedurals.push(JSON.parse(raw));
        }
        if ( procedurals.length === 0 ) { return; }
        const pfilterer = this.proceduralFiltererInstance();
        if ( pfilterer !== null ) {
            pfilterer.addProceduralSelectors(procedurals);
        }
    }

    createProceduralFilter(o) {
        const pfilterer = this.proceduralFiltererInstance();
        if ( pfilterer === null ) { return; }
        return pfilterer.createProceduralFilter(o);
    }

    getAllSelectors(bits = 0) {
        const out = {
            declarative: [],
            exceptions: this.exceptedCSSRules,
        };
        const hasProcedural = this.proceduralFilterer instanceof Object;
        const includePrivateSelectors = (bits & 0b01) !== 0;
        const masterToken = hasProcedural
            ? `[${this.proceduralFilterer.masterToken}]`
            : undefined;
        for ( const css of this.stylesheets ) {
            for ( const block of this.explodeCSS(css) ) {
                if (
                    includePrivateSelectors === false &&
                    masterToken !== undefined &&
                    block.startsWith(masterToken)
                ) {
                    continue;
                }
                out.declarative.push(block);
            }
        }
        const excludeProcedurals = (bits & 0b10) !== 0;
        if ( excludeProcedurals === false ) {
            out.procedural = [];
            if ( hasProcedural ) {
                out.procedural.push(
                    ...this.proceduralFilterer.selectors.values()
                );
            }
            const proceduralFilterer = this.proceduralFiltererInstance();
            if ( proceduralFilterer !== null ) {
                for ( const json of this.convertedProceduralFilters ) {
                    const pfilter = proceduralFilterer.createProceduralFilter(json);
                    pfilter.converted = true;
                    out.procedural.push(pfilter);
                }
            }
        }
        return out;
    }

    getAllExceptionSelectors() {
        return this.exceptions.join(',\n');
    }
};

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// vAPI.domCollapser

{
    const messaging = vAPI.messaging;
    const toCollapse = new Map();
    const src1stProps = {
        audio: 'currentSrc',
        embed: 'src',
        iframe: 'src',
        img: 'currentSrc',
        object: 'data',
        video: 'currentSrc',
    };
    const src2ndProps = {
        audio: 'src',
        img: 'src',
        video: 'src',
    };
    const tagToTypeMap = {
        audio: 'media',
        embed: 'object',
        iframe: 'sub_frame',
        img: 'image',
        object: 'object',
        video: 'media',
    };
    let requestIdGenerator = 1,
        processTimer,
        cachedBlockedSet,
        cachedBlockedSetHash,
        cachedBlockedSetTimer,
        toProcess = [],
        toFilter = [],
        netSelectorCacheCount = 0;

    const cachedBlockedSetClear = function() {
        cachedBlockedSet =
        cachedBlockedSetHash =
        cachedBlockedSetTimer = undefined;
    };

    // https://github.com/chrisaljoudi/uBlock/issues/399
    // https://github.com/gorhill/uBlock/issues/2848
    //   Use a user stylesheet to collapse placeholders.
    const getCollapseToken = ( ) => {
        if ( collapseToken === undefined ) {
            collapseToken = vAPI.randomToken();
            vAPI.userStylesheet.add(
                `[${collapseToken}]\n{display:none!important;}`,
                true
            );
        }
        return collapseToken;
    };
    let collapseToken;

    // https://github.com/chrisaljoudi/uBlock/issues/174
    //   Do not remove fragment from src URL
    const onProcessed = function(response) {
        // This happens if uBO is disabled or restarted.
        if ( response instanceof Object === false ) {
            toCollapse.clear();
            return;
        }

        const targets = toCollapse.get(response.id);
        if ( targets === undefined ) { return; }

        toCollapse.delete(response.id);
        if ( cachedBlockedSetHash !== response.hash ) {
            cachedBlockedSet = new Set(response.blockedResources);
            cachedBlockedSetHash = response.hash;
            if ( cachedBlockedSetTimer !== undefined ) {
                clearTimeout(cachedBlockedSetTimer);
            }
            cachedBlockedSetTimer = vAPI.setTimeout(cachedBlockedSetClear, 30000);
        }
        if ( cachedBlockedSet === undefined || cachedBlockedSet.size === 0 ) {
            return;
        }

        const selectors = [];
        let netSelectorCacheCountMax = response.netSelectorCacheCountMax;

        for ( const target of targets ) {
            const tag = target.localName;
            let prop = src1stProps[tag];
            if ( prop === undefined ) { continue; }
            let src = target[prop];
            if ( typeof src !== 'string' || src.length === 0 ) {
                prop = src2ndProps[tag];
                if ( prop === undefined ) { continue; }
                src = target[prop];
                if ( typeof src !== 'string' || src.length === 0 ) { continue; }
            }
            if ( cachedBlockedSet.has(tagToTypeMap[tag] + ' ' + src) === false ) {
                continue;
            }
            target.setAttribute(getCollapseToken(), '');
            // https://github.com/chrisaljoudi/uBlock/issues/1048
            //   Use attribute to construct CSS rule
            if ( netSelectorCacheCount > netSelectorCacheCountMax ) { continue; }
            const value = target.getAttribute(prop);
            if ( value ) {
                selectors.push(`${tag}[${prop}="${CSS.escape(value)}"]`);
                netSelectorCacheCount += 1;
            }
        }

        if ( selectors.length === 0 ) { return; }
        messaging.send('contentscript', {
            what: 'cosmeticFiltersInjected',
            type: 'net',
            hostname: window.location.hostname,
            selectors,
        });
    };

    const send = function() {
        processTimer = undefined;
        toCollapse.set(requestIdGenerator, toProcess);
        messaging.send('contentscript', {
            what: 'getCollapsibleBlockedRequests',
            id: requestIdGenerator,
            frameURL: window.location.href,
            resources: toFilter,
            hash: cachedBlockedSetHash,
        }).then(response => {
            onProcessed(response);
        });
        toProcess = [];
        toFilter = [];
        requestIdGenerator += 1;
    };

    const process = function(delay) {
        if ( toProcess.length === 0 ) { return; }
        if ( delay === 0 ) {
            if ( processTimer !== undefined ) {
                clearTimeout(processTimer);
            }
            send();
        } else if ( processTimer === undefined ) {
            processTimer = vAPI.setTimeout(send, delay || 20);
        }
    };

    const add = function(target) {
        toProcess[toProcess.length] = target;
    };

    const addMany = function(targets) {
        for ( const target of targets ) {
            add(target);
        }
    };

    const iframeSourceModified = function(mutations) {
        for ( const mutation of mutations ) {
            addIFrame(mutation.target, true);
        }
        process();
    };
    const iframeSourceObserver = new MutationObserver(iframeSourceModified);
    const iframeSourceObserverOptions = {
        attributes: true,
        attributeFilter: [ 'src' ]
    };

    // https://github.com/gorhill/uBlock/issues/162
    //   Be prepared to deal with possible change of src attribute.
    const addIFrame = function(iframe, dontObserve) {
        if ( dontObserve !== true ) {
            iframeSourceObserver.observe(iframe, iframeSourceObserverOptions);
        }
        const src = iframe.src;
        if ( typeof src !== 'string' || src === '' ) { return; }
        if ( src.startsWith('http') === false ) { return; }
        toFilter.push({ type: 'sub_frame', url: iframe.src });
        add(iframe);
    };

    const addIFrames = function(iframes) {
        for ( const iframe of iframes ) {
            addIFrame(iframe);
        }
    };

    const onResourceFailed = function(ev) {
        if ( tagToTypeMap[ev.target.localName] !== undefined ) {
            add(ev.target);
            process();
        }
    };

    const stop = function() {
        document.removeEventListener('error', onResourceFailed, true);
        if ( processTimer !== undefined ) {
            clearTimeout(processTimer);
        }
        if ( vAPI.domWatcher instanceof Object ) {
            vAPI.domWatcher.removeListener(domWatcherInterface);
        }
        vAPI.shutdown.remove(stop);
        vAPI.domCollapser = null;
    };

    const start = function() {
        if ( vAPI.domWatcher instanceof Object ) {
            vAPI.domWatcher.addListener(domWatcherInterface);
        }
    };

    const domWatcherInterface = {
        onDOMCreated: function() {
            if ( self.vAPI instanceof Object === false ) { return; }
            if ( vAPI.domCollapser instanceof Object === false ) {
                if ( vAPI.domWatcher instanceof Object ) {
                    vAPI.domWatcher.removeListener(domWatcherInterface);
                }
                return;
            }
            // Listener to collapse blocked resources.
            // - Future requests not blocked yet
            // - Elements dynamically added to the page
            // - Elements which resource URL changes
            // https://github.com/chrisaljoudi/uBlock/issues/7
            // Preferring getElementsByTagName over querySelectorAll:
            //   http://jsperf.com/queryselectorall-vs-getelementsbytagname/145
            const elems = document.images ||
                          document.getElementsByTagName('img');
            for ( const elem of elems ) {
                if ( elem.complete ) {
                    add(elem);
                }
            }
            addMany(document.embeds || document.getElementsByTagName('embed'));
            addMany(document.getElementsByTagName('object'));
            addIFrames(document.getElementsByTagName('iframe'));
            process(0);

            document.addEventListener('error', onResourceFailed, true);

            vAPI.shutdown.add(stop);
        },
        onDOMChanged: function(addedNodes) {
            if ( addedNodes.length === 0 ) { return; }
            for ( const node of addedNodes ) {
                if ( node.localName === 'iframe' ) {
                    addIFrame(node);
                }
                if ( node.firstElementChild === null ) { continue; }
                const iframes = node.getElementsByTagName('iframe');
                if ( iframes.length !== 0 ) {
                    addIFrames(iframes);
                }
            }
            process();
        }
    };

    vAPI.domCollapser = { start };
}

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// vAPI.domSurveyor

{
    // http://www.cse.yorku.ca/~oz/hash.html#djb2
    //   Must mirror cosmetic filtering compiler's version
    const hashFromStr = (type, s) => {
        const len = s.length;
        const step = len + 7 >>> 3;
        let hash = (type << 5) + type ^ len;
        for ( let i = 0; i < len; i += step ) {
            hash = (hash << 5) + hash ^ s.charCodeAt(i);
        }
        return hash & 0xFFFFFF;
    };

    const addHashes = hashes => {
        for ( const hash of hashes ) {
            queriedHashes.add(hash);
        }
    };

    const queriedHashes = new Set();
    const maxSurveyNodes = 65536;
    const pendingLists = [];
    const pendingNodes = [];
    const processedSet = new Set();
    let domFilterer;
    let hostname = '';
    let domChanged = false;
    let scannedCount = 0;
    let stopped = false;

    const addPendingList = list => {
        if ( list.length === 0 ) { return; }
        pendingLists.push(Array.from(list));
    };

    const nextPendingNodes = ( ) => {
        if ( pendingLists.length === 0 ) { return 0; }
        const bufferSize = 256;
        let j = 0;
        do {
            const nodeList = pendingLists[0];
            let n = bufferSize - j;
            if ( n > nodeList.length ) {
                n = nodeList.length;
            }
            for ( let i = 0; i < n; i++ ) {
                pendingNodes[j+i] = nodeList[i];
            }
            j += n;
            if ( n !== nodeList.length ) {
                pendingLists[0] = nodeList.slice(n);
                break;
            }
            pendingLists.shift();
        } while ( j < bufferSize && pendingLists.length !== 0 );
        return j;
    };

    const hasPendingNodes = ( ) => {
        return pendingLists.length !== 0;
    };

    // Extract all classes/ids: these will be passed to the cosmetic
    // filtering engine, and in return we will obtain only the relevant
    // CSS selectors.

    // https://github.com/gorhill/uBlock/issues/672
    // http://www.w3.org/TR/2014/REC-html5-20141028/infrastructure.html#space-separated-tokens
    // http://jsperf.com/enumerate-classes/6

    const idFromNode = (node, out) => {
        const raw = node.id;
        if ( typeof raw !== 'string' || raw.length === 0 ) { return; }
        const hash = hashFromStr(0x23 /* '#' */, raw.trim());
        if ( queriedHashes.has(hash) ) { return; }
        queriedHashes.add(hash);
        out.push(hash);
    };

    // https://github.com/uBlockOrigin/uBlock-issues/discussions/2076
    //   Performance: avoid using Element.classList
    const classesFromNode = (node, out) => {
        const s = node.getAttribute('class');
        if ( typeof s !== 'string' ) { return; }
        const len = s.length;
        for ( let beg = 0, end = 0; beg < len; beg += 1 ) {
            end = s.indexOf(' ', beg);
            if ( end === beg ) { continue; }
            if ( end === -1 ) { end = len; }
            const token = s.slice(beg, end).trimEnd();
            beg = end;
            if ( token.length === 0 ) { continue; }
            const hash = hashFromStr(0x2E /* '.' */, token);
            if ( queriedHashes.has(hash) ) { continue; }
            queriedHashes.add(hash);
            out.push(hash);
        }
    };

    const getSurveyResults = (hashes, safeOnly) => {
        if ( self.vAPI.messaging instanceof Object === false ) {
            stop(); return;
        }
        const promise = hashes.length === 0
            ? Promise.resolve(null)
            : self.vAPI.messaging.send('contentscript', {
                what: 'retrieveGenericCosmeticSelectors',
                hostname,
                hashes,
                exceptions: domFilterer.exceptions,
                safeOnly,
            });
        promise.then(response => {
            processSurveyResults(response);
        });
    };

    const doSurvey = ( ) => {
        if ( self.vAPI instanceof Object === false ) { return; }
        const t0 = performance.now();
        const hashes = [];
        const nodes = pendingNodes;
        const deadline = t0 + 4;
        let scanned = 0;
        for (;;) {
            const n = nextPendingNodes();
            if ( n === 0 ) { break; }
            for ( let i = 0; i < n; i++ ) {
                const node = nodes[i]; nodes[i] = null;
                if ( domChanged ) {
                    if ( processedSet.has(node) ) { continue; }
                    processedSet.add(node);
                }
                idFromNode(node, hashes);
                classesFromNode(node, hashes);
                scanned += 1;
            }
            if ( performance.now() >= deadline ) { break; }
        }
        scannedCount += scanned;
        if ( scannedCount >= maxSurveyNodes ) {
            stop();
        }
        processedSet.clear();
        getSurveyResults(hashes);
    };

    const surveyTimer = new vAPI.SafeAnimationFrame(doSurvey);

    // This is to shutdown the surveyor if result of surveying keeps being
    // fruitless. This is useful on long-lived web page. I arbitrarily
    // picked 5 minutes before the surveyor is allowed to shutdown. I also
    // arbitrarily picked 256 misses before the surveyor is allowed to
    // shutdown.
    let canShutdownAfter = Date.now() + 300000;
    let surveyResultMissCount = 0;

    // Handle main process' response.

    const processSurveyResults = response => {
        if ( stopped ) { return; }
        const result = response && response.result;
        let mustCommit = false;
        if ( result ) {
            const css = result.injectedCSS;
            if ( typeof css === 'string' && css.length !== 0 ) {
                domFilterer.addCSS(css);
                mustCommit = true;
            }
            const selectors = result.excepted;
            if ( Array.isArray(selectors) && selectors.length !== 0 ) {
                domFilterer.exceptCSSRules(selectors);
            }
        }
        if ( hasPendingNodes() ) {
            surveyTimer.start(1);
        }
        if ( mustCommit ) {
            surveyResultMissCount = 0;
            canShutdownAfter = Date.now() + 300000;
            return;
        }
        surveyResultMissCount += 1;
        if ( surveyResultMissCount < 256 || Date.now() < canShutdownAfter ) {
            return;
        }
        //console.info(`[domSurveyor][${hostname}] Shutting down, too many misses`);
        stop();
        self.vAPI.messaging.send('contentscript', {
            what: 'disableGenericCosmeticFilteringSurveyor',
            hostname,
        });
    };

    const domWatcherInterface = {
        onDOMCreated: function() {
            domFilterer = vAPI.domFilterer;
            // https://github.com/uBlockOrigin/uBlock-issues/issues/1692
            //   Look-up safe-only selectors to mitigate probability of
            //   html/body elements of erroneously being targeted.
            const hashes = [];
            if ( document.documentElement !== null ) {
                idFromNode(document.documentElement, hashes);
                classesFromNode(document.documentElement, hashes);
            }
            if ( document.body !== null ) {
                idFromNode(document.body, hashes);
                classesFromNode(document.body, hashes);
            }
            if ( hashes.length !== 0 ) {
                getSurveyResults(hashes, true);
            }
            addPendingList(document.querySelectorAll(
                '[id]:not(html):not(body),[class]:not(html):not(body)'
            ));
            if ( hasPendingNodes() ) {
                surveyTimer.start();
            }
        },
        onDOMChanged: function(addedNodes) {
            if ( addedNodes.length === 0 ) { return; }
            domChanged = true;
            for ( const node of addedNodes ) {
                addPendingList([ node ]);
                if ( node.firstElementChild === null ) { continue; }
                addPendingList(
                    node.querySelectorAll(
                        '[id]:not(html):not(body),[class]:not(html):not(body)'
                    )
                );
            }
            if ( hasPendingNodes() ) {
                surveyTimer.start(1);
            }
        }
    };

    const start = details => {
        if ( self.vAPI instanceof Object === false ) { return; }
        if ( self.vAPI.domFilterer instanceof Object === false ) { return; }
        if ( self.vAPI.domWatcher instanceof Object === false ) { return; }
        hostname = details.hostname;
        self.vAPI.domWatcher.addListener(domWatcherInterface);
    };

    const stop = ( ) => {
        stopped = true;
        pendingLists.length = 0;
        surveyTimer.clear();
        if ( self.vAPI instanceof Object === false ) { return; }
        if ( self.vAPI.domWatcher instanceof Object ) {
            self.vAPI.domWatcher.removeListener(domWatcherInterface);
        }
        self.vAPI.domSurveyor = null;
    };

    self.vAPI.domSurveyor = { start, addHashes };
}

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

// vAPI.bootstrap:
//   Bootstrapping allows all components of the content script
//   to be launched if/when needed.

{
    const onDomReady = ( ) => {
        // This can happen on Firefox. For instance:
        // https://github.com/gorhill/uBlock/issues/1893
        if ( window.location === null ) { return; }
        if ( self.vAPI instanceof Object === false ) { return; }

        vAPI.messaging.send('contentscript', {
            what: 'shouldRenderNoscriptTags',
        });

        if ( vAPI.domFilterer instanceof Object ) {
            vAPI.domFilterer.commitNow();
        }

        if ( vAPI.domWatcher instanceof Object ) {
            vAPI.domWatcher.start();
        }

        // Element picker works only in top window for now.
        if (
            window !== window.top ||
            vAPI.domFilterer instanceof Object === false
        ) {
            return;
        }

        // To be used by element picker/zapper.
        vAPI.mouseClick = { x: -1, y: -1 };

        const onMouseClick = function(ev) {
            if ( ev.isTrusted === false ) { return; }
            vAPI.mouseClick.x = ev.clientX;
            vAPI.mouseClick.y = ev.clientY;

            // https://github.com/chrisaljoudi/uBlock/issues/1143
            //   Find a link under the mouse, to try to avoid confusing new tabs
            //   as nuisance popups.
            // https://github.com/uBlockOrigin/uBlock-issues/issues/777
            //   Mind that href may not be a string.
            const elem = ev.target.closest('a[href]');
            if ( elem === null || typeof elem.href !== 'string' ) { return; }
            vAPI.messaging.send('contentscript', {
                what: 'maybeGoodPopup',
                url: elem.href || '',
            });
        };

        document.addEventListener('mousedown', onMouseClick, true);

        // https://github.com/gorhill/uMatrix/issues/144
        vAPI.shutdown.add(function() {
            document.removeEventListener('mousedown', onMouseClick, true);
        });
    };

    // https://github.com/uBlockOrigin/uBlock-issues/issues/403
    //   If there was a spurious port disconnection -- in which case the
    //   response is expressly set to `null`, rather than undefined or
    //   an object -- let's stay around, we may be given the opportunity
    //   to try bootstrapping again later.

    const onResponseReady = response => {
        if ( response instanceof Object === false ) { return; }
        vAPI.bootstrap = undefined;

        // cosmetic filtering engine aka 'cfe'
        const cfeDetails = response && response.specificCosmeticFilters;
        if ( !cfeDetails || !cfeDetails.ready ) {
            vAPI.domWatcher = vAPI.domCollapser = vAPI.domFilterer =
            vAPI.domSurveyor = vAPI.domIsLoaded = null;
            return;
        }

        vAPI.domCollapser.start();

        const {
            noSpecificCosmeticFiltering,
            noGenericCosmeticFiltering,
        } = response;

        vAPI.noSpecificCosmeticFiltering = noSpecificCosmeticFiltering;
        vAPI.noGenericCosmeticFiltering = noGenericCosmeticFiltering;

        if ( noSpecificCosmeticFiltering && noGenericCosmeticFiltering ) {
            vAPI.domFilterer = null;
            vAPI.domSurveyor = null;
        } else {
            const domFilterer = vAPI.domFilterer = new vAPI.DOMFilterer();
            if ( noGenericCosmeticFiltering || cfeDetails.disableSurveyor ) {
                vAPI.domSurveyor = null;
            }
            domFilterer.exceptions = cfeDetails.exceptionFilters;
            domFilterer.addCSS(cfeDetails.injectedCSS);
            domFilterer.addProceduralSelectors(cfeDetails.proceduralFilters);
            domFilterer.exceptCSSRules(cfeDetails.exceptedFilters);
            domFilterer.convertedProceduralFilters = cfeDetails.convertedProceduralFilters;
            vAPI.userStylesheet.apply();
        }

        if ( vAPI.domSurveyor ) {
            if ( Array.isArray(cfeDetails.genericCosmeticHashes) ) {
                vAPI.domSurveyor.addHashes(cfeDetails.genericCosmeticHashes);
            }
            vAPI.domSurveyor.start(cfeDetails);
        }

        const readyState = document.readyState;
        if ( readyState === 'interactive' || readyState === 'complete' ) {
            return onDomReady();
        }
        document.addEventListener('DOMContentLoaded', onDomReady, { once: true });
    };

    vAPI.bootstrap = function() {
        vAPI.messaging.send('contentscript', {
            what: 'retrieveContentScriptParameters',
            url: vAPI.effectiveSelf.location.href,
            needScriptlets: self.uBO_scriptletsInjected === undefined,
        }).then(response => {
            onResponseReady(response);
        });
    };
}

// This starts bootstrap process.
vAPI.bootstrap();

/******************************************************************************/
/******************************************************************************/
/******************************************************************************/

}
// <<<<<<<< end of HUGE-IF-BLOCK
