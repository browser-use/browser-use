/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015-present Raymond Hill

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

import { dom, qs$, qsa$ } from './dom.js';

/******************************************************************************/

(( ) => {

/******************************************************************************/

const logger = self.logger;
const showdomButton = qs$('#showdom');
const inspector = qs$('#domInspector');
const domTree = qs$('#domTree');
const filterToIdMap = new Map();

let inspectedTabId = 0;
let inspectedHostname = '';
let uidGenerator = 1;

/*******************************************************************************
 * 
 * How it works:
 * 
 * 1. The logger/inspector is enabled from the logger window
 * 
 * 2. The inspector content script is injected in the root frame of the tab
 * currently selected in the logger
 * 
 * 3. The inspector content script asks the logger/inspector to establish
 * a two-way communication channel
 * 
 * 3. The inspector content script embed an inspector frame in the document
 * being inspected and waits for the inspector frame to be fully loaded
 * 
 * 4. The inspector content script sends a messaging port object to the
 * embedded inspector frame for a two-way communication channel between
 * the inspector frame and the inspector content script
 * 
 * 5. The inspector content script sends dom information to the
 * logger/inspector
 * 
 * */

const contentInspectorChannel = (( ) => {
    let bcChannel;
    let toContentPort;

    const start = ( ) => {
        bcChannel = new globalThis.BroadcastChannel('contentInspectorChannel');
        bcChannel.onmessage = ev => {
            const msg = ev.data || {};
            connect(msg.tabId, msg.frameId);
        };
        browser.webNavigation.onDOMContentLoaded.addListener(onContentLoaded);
    };

    const shutdown = ( ) => {
        browser.webNavigation.onDOMContentLoaded.removeListener(onContentLoaded);
        disconnect();
        bcChannel.close();
        bcChannel.onmessage = null;
        bcChannel = undefined;
    };

    const connect = (tabId, frameId) => {
        disconnect();
        try {
            toContentPort = browser.tabs.connect(tabId, { frameId });
            toContentPort.onMessage.addListener(onContentMessage);
            toContentPort.onDisconnect.addListener(onContentDisconnect);
        } catch {
        }
    };

    const disconnect = ( ) => {
        if ( toContentPort === undefined ) { return; }
        toContentPort.onMessage.removeListener(onContentMessage);
        toContentPort.onDisconnect.removeListener(onContentDisconnect);
        toContentPort.disconnect();
        toContentPort = undefined;
    };

    const send = msg => {
        if ( toContentPort === undefined ) { return; }
        toContentPort.postMessage(msg);
    };

    const onContentMessage = msg => {
        if ( msg.what === 'domLayoutFull' ) {
            inspectedHostname = msg.hostname;
            renderDOMFull(msg);
        } else if ( msg.what === 'domLayoutIncremental' ) {
            renderDOMIncremental(msg);
        }
    };

    const onContentDisconnect = ( ) => {
        disconnect();
    };

    const onContentLoaded = details => {
        if ( details.tabId !== inspectedTabId ) { return; }
        if ( details.frameId !== 0 ) { return; }
        disconnect();
        injectInspector();
    };

    return { start, disconnect, send, shutdown };
})();

/******************************************************************************/

const nodeFromDomEntry = entry => {
    const li = document.createElement('li');
    dom.attr(li, 'id', entry.nid);
    // expander/collapser
    li.appendChild(document.createElement('span'));
    // selector
    let node = document.createElement('code');
    node.textContent = entry.sel;
    li.appendChild(node);
    // descendant count
    let value = entry.cnt || 0;
    node = document.createElement('span');
    node.textContent = value !== 0 ? value.toLocaleString() : '';
    dom.attr(node, 'data-cnt', value);
    li.appendChild(node);
    // cosmetic filter
    if ( entry.filter === undefined ) {
        return li;
    }
    node = document.createElement('code');
    dom.cl.add(node, 'filter');
    value = filterToIdMap.get(entry.filter);
    if ( value === undefined ) {
        value = `${uidGenerator}`;
        filterToIdMap.set(entry.filter, value);
        uidGenerator += 1;
    }
    dom.attr(node, 'data-filter-id', value);
    node.textContent = entry.filter;
    li.appendChild(node);
    dom.cl.add(li, 'isCosmeticHide');
    return li;
};

/******************************************************************************/

const appendListItem = (ul, li) => {
    ul.appendChild(li);
    // Ancestor nodes of a node which is affected by a cosmetic filter will
    // be marked as "containing cosmetic filters", for user convenience.
    if ( dom.cl.has(li, 'isCosmeticHide') === false ) { return; }
    for (;;) {
        li = li.parentElement.parentElement;
        if ( li === null ) { break; }
        dom.cl.add(li, 'hasCosmeticHide');
    }
};

/******************************************************************************/

const renderDOMFull = response => {
    const domTreeParent = domTree.parentElement;
    let ul = domTreeParent.removeChild(domTree);
    logger.removeAllChildren(domTree);

    filterToIdMap.clear();

    let lvl = 0;
    let li;
    for ( const entry of response.layout ) {
        if ( entry.lvl === lvl ) {
            li = nodeFromDomEntry(entry);
            appendListItem(ul, li);
            continue;
        }
        if ( entry.lvl > lvl ) {
            ul = document.createElement('ul');
            li.appendChild(ul);
            dom.cl.add(li, 'branch');
            li = nodeFromDomEntry(entry);
            appendListItem(ul, li);
            lvl = entry.lvl;
            continue;
        }
        // entry.lvl < lvl
        while ( entry.lvl < lvl ) {
            ul = li.parentNode;
            li = ul.parentNode;
            ul = li.parentNode;
            lvl -= 1;
        }
        li = nodeFromDomEntry(entry);
        appendListItem(ul, li);
    }
    while ( ul.parentNode !== null ) {
        ul = ul.parentNode;
    }
    dom.cl.add(ul.firstElementChild, 'show');

    domTreeParent.appendChild(domTree);
};

/******************************************************************************/

const patchIncremental = (from, delta) => {
    let li = from.parentElement.parentElement;
    const patchCosmeticHide = delta >= 0 &&
        dom.cl.has(from, 'isCosmeticHide') &&
        dom.cl.has(li, 'hasCosmeticHide') === false;
    // Include descendants count when removing a node
    if ( delta < 0 ) {
        delta -= countFromNode(from);
    }
    for ( ; li.localName === 'li'; li = li.parentElement.parentElement ) {
        const span = li.children[2];
        if ( delta !== 0 ) {
            const cnt = countFromNode(li) + delta;
            span.textContent = cnt !== 0 ? cnt.toLocaleString() : '';
            dom.attr(span, 'data-cnt', cnt);
        }
        if ( patchCosmeticHide ) {
            dom.cl.add(li, 'hasCosmeticHide');
        }
    }
};

/******************************************************************************/

const renderDOMIncremental = response => {
    // Process each journal entry:
    //  1 = node added
    // -1 = node removed
    const nodes = new Map(response.nodes);
    let li = null;
    let ul = null;
    for ( const entry of response.journal ) {
        // Remove node
        if ( entry.what === -1 ) {
            li = qs$(`#${entry.nid}`);
            if ( li === null ) { continue; }
            patchIncremental(li, -1);
            li.parentNode.removeChild(li);
            continue;
        }
        // Modify node
        if ( entry.what === 0 ) {
            // TODO: update selector/filter
            continue;
        }
        // Add node as sibling
        if ( entry.what === 1 && entry.l ) {
            const previous = qs$(`#${entry.l}`);
            // This should not happen
            if ( previous === null ) {
                // throw new Error('No left sibling!?');
                continue;
            }
            ul = previous.parentElement;
            li = nodeFromDomEntry(nodes.get(entry.nid));
            ul.insertBefore(li, previous.nextElementSibling);
            patchIncremental(li, 1);
            continue;
        }
        // Add node as child
        if ( entry.what === 1 && entry.u ) {
            li = qs$(`#${entry.u}`);
            // This should not happen
            if ( li === null ) {
                // throw new Error('No parent!?');
                continue;
            }
            ul = qs$(li, 'ul');
            if ( ul === null ) {
                ul = document.createElement('ul');
                li.appendChild(ul);
                dom.cl.add(li, 'branch');
            }
            li = nodeFromDomEntry(nodes.get(entry.nid));
            ul.appendChild(li);
            patchIncremental(li, 1);
            continue;
        }
    }
};

/******************************************************************************/

const countFromNode = li => {
    const span = li.children[2];
    const cnt = parseInt(dom.attr(span, 'data-cnt'), 10);
    return isNaN(cnt) ? 0 : cnt;
};

/******************************************************************************/

const selectorFromNode = node => {
    let selector = '';
    while ( node !== null ) {
        if ( node.localName === 'li' ) {
            const code = qs$(node, 'code');
            if ( code !== null ) {
                selector = `${code.textContent} > ${selector}`;
                if ( selector.includes('#') ) { break; }
            }
        }
        node = node.parentElement;
    }
    return selector.slice(0, -3);
};

/******************************************************************************/

const selectorFromFilter = node => {
    while ( node !== null ) {
        if ( node.localName === 'li' ) {
            const code = qs$(node, 'code:nth-of-type(2)');
            if ( code !== null ) {
                return code.textContent;
            }
        }
        node = node.parentElement;
    }
    return '';
};

/******************************************************************************/

const nidFromNode = node => {
    let li = node;
    while ( li !== null ) {
        if ( li.localName === 'li' ) {
            return li.id || '';
        }
        li = li.parentElement;
    }
    return '';
};

/******************************************************************************/

const startDialog = (( ) => {
    let dialog;
    let textarea;
    let hideSelectors = [];
    let unhideSelectors = [];

    const parse = function() {
        hideSelectors = [];
        unhideSelectors = [];

        const re = /^([^#]*)(#@?#)(.+)$/;
        for ( let line of textarea.value.split(/\s*\n\s*/) ) {
            line = line.trim();
            if ( line === '' || line.charAt(0) === '!' ) { continue; }
            const matches = re.exec(line);
            if ( matches === null || matches.length !== 4 ) { continue; }
            if ( inspectedHostname.lastIndexOf(matches[1]) === -1 ) {
                continue;
            }
            if ( matches[2] === '##' ) {
                hideSelectors.push(matches[3]);
            } else {
                unhideSelectors.push(matches[3]);
            }
        }

        showCommitted();
    };

    const inputTimer = vAPI.defer.create(parse);

    const onInputChanged = ( ) => {
        inputTimer.on(743);
    };

    const onClicked = function(ev) {
        const target = ev.target;

        ev.stopPropagation();

        if ( target.id === 'createCosmeticFilters' ) {
            vAPI.messaging.send('loggerUI', {
                what: 'createUserFilter',
                filters: textarea.value,
            });
            // Force a reload for the new cosmetic filter(s) to take effect
            vAPI.messaging.send('loggerUI', {
                what: 'reloadTab',
                tabId: inspectedTabId,
            });
            return stop();
        }
    };

    const showCommitted = function() {
        contentInspectorChannel.send({
            what: 'showCommitted',
            hide: hideSelectors.join(',\n'),
            unhide: unhideSelectors.join(',\n')
        });
    };

    const showInteractive = function() {
        contentInspectorChannel.send({
            what: 'showInteractive',
            hide: hideSelectors.join(',\n'),
            unhide: unhideSelectors.join(',\n')
        });
    };

    const start = function() {
        dialog = logger.modalDialog.create('#cosmeticFilteringDialog', stop);
        textarea = qs$(dialog, 'textarea');
        hideSelectors = [];
        for ( const node of qsa$(domTree, 'code.off') ) {
            if ( dom.cl.has(node, 'filter') ) { continue; }
            hideSelectors.push(selectorFromNode(node));
        }
        const taValue = [];
        for ( const selector of hideSelectors ) {
            taValue.push(inspectedHostname + '##' + selector);
        }
        const ids = new Set();
        for ( const node of qsa$(domTree, 'code.filter.off') ) {
            const id = dom.attr(node, 'data-filter-id');
            if ( ids.has(id) ) { continue; }
            ids.add(id);
            unhideSelectors.push(node.textContent);
            taValue.push(inspectedHostname + '#@#' + node.textContent);
        }
        textarea.value = taValue.join('\n');
        textarea.addEventListener('input', onInputChanged);
        dialog.addEventListener('click', onClicked, true);
        showCommitted();
        logger.modalDialog.show();
    };

    const stop = function() {
        inputTimer.off();
        showInteractive();
        textarea.removeEventListener('input', onInputChanged);
        dialog.removeEventListener('click', onClicked, true);
        dialog = undefined;
        textarea = undefined;
        hideSelectors = [];
        unhideSelectors = [];
    };

    return start;
})();

/******************************************************************************/

const onClicked = ev => {
    ev.stopPropagation();

    if ( inspectedTabId === 0 ) { return; }

    const target = ev.target;
    const parent = target.parentElement;

    // Expand/collapse branch
    if (
        target.localName === 'span' &&
        parent instanceof HTMLLIElement &&
        dom.cl.has(parent, 'branch') &&
        target === parent.firstElementChild
    ) {
        const state = dom.cl.toggle(parent, 'show');
        if ( !state ) {
            for ( const node of qsa$(parent, '.branch') ) {
                dom.cl.remove(node, 'show');
            }
        }
        return;
    }

    // Not a node or filter 
    if ( target.localName !== 'code' ) { return; }

    // Toggle cosmetic filter
    if ( dom.cl.has(target, 'filter') ) {
        contentInspectorChannel.send({
            what: 'toggleFilter',
            original: false,
            target: dom.cl.toggle(target, 'off'),
            selector: selectorFromNode(target),
            filter: selectorFromFilter(target),
            nid: nidFromNode(target)
        });
        dom.cl.toggle(
            qsa$(inspector, `[data-filter-id="${dom.attr(target, 'data-filter-id')}"]`),
            'off',
            dom.cl.has(target, 'off')
        );
    }
    // Toggle node
    else {
        contentInspectorChannel.send({
            what: 'toggleNodes',
            original: true,
            target: dom.cl.toggle(target, 'off') === false,
            selector: selectorFromNode(target),
            nid: nidFromNode(target)
        });
    }

    const cantCreate = qs$(domTree, '.off') === null;
    dom.cl.toggle(qs$(inspector, '.permatoolbar .revert'), 'disabled', cantCreate);
    dom.cl.toggle(qs$(inspector, '.permatoolbar .commit'), 'disabled', cantCreate);
};

/******************************************************************************/

const onMouseOver = (( ) => {
    let mouseoverTarget = null;

    const mouseoverTimer = vAPI.defer.create(( ) => {
        contentInspectorChannel.send({
            what: 'highlightOne',
            selector: selectorFromNode(mouseoverTarget),
            nid: nidFromNode(mouseoverTarget),
            scrollTo: true
        });
    });

    return ev => {
        if ( inspectedTabId === 0 ) { return; }
        // Convenience: skip real-time highlighting if shift key is pressed.
        if ( ev.shiftKey ) { return; }
        // Find closest `li`
        const target = ev.target.closest('li');
        if ( target === mouseoverTarget ) { return; }
        mouseoverTarget = target;
        mouseoverTimer.on(50);
    };
})();

/******************************************************************************/

const currentTabId = ( ) => {
    if ( dom.cl.has(showdomButton, 'active') === false ) { return 0; }
    return logger.tabIdFromPageSelector();
};

/******************************************************************************/

const injectInspector = (( ) => {
    const timer = vAPI.defer.create(( ) => {
        const tabId = currentTabId();
        if ( tabId <= 0 ) { return; }
        inspectedTabId = tabId;
        vAPI.messaging.send('loggerUI', {
            what: 'scriptlet',
            tabId,
            scriptlet: 'dom-inspector',
        });
    });
    return ( ) => {
        shutdownInspector();
        timer.offon(353);
    };
})();

/******************************************************************************/

const shutdownInspector = ( ) => {
    contentInspectorChannel.disconnect();
    logger.removeAllChildren(domTree);
    dom.cl.remove(inspector, 'vExpanded');
    inspectedTabId = 0;
};

/******************************************************************************/

const onTabIdChanged = ( ) => {
    const tabId = currentTabId();
    if ( tabId <= 0 ) {
        return toggleOff();
    }
    if ( inspectedTabId !== tabId ) {
        injectInspector();
    }
};

/******************************************************************************/

const toggleVExpandView = ( ) => {
    const branches = qsa$('#domTree li.branch.show > ul > li.branch:not(.show)');
    for ( const branch of branches ) {
        dom.cl.add(branch, 'show');
    }
};

const toggleVCompactView = ( ) => {
    const branches = qsa$('#domTree li.branch.show > ul > li:not(.show)');
    const tohideSet = new Set();
    for ( const branch of branches ) {
        const node = branch.closest('li.branch.show');
        if ( node.id === 'n1' ) { continue; }
        tohideSet.add(node);
    }
    const tohideList = Array.from(tohideSet);
    let i = tohideList.length - 1;
    while ( i > 0 ) {
        if ( tohideList[i-1].contains(tohideList[i]) ) {
            tohideList.splice(i-1, 1);
        } else if ( tohideList[i].contains(tohideList[i-1]) ) {
            tohideList.splice(i, 1);
        }
        i -= 1;
    }
    for ( const node of tohideList ) {
        dom.cl.remove(node, 'show');
    }
};

const toggleHCompactView = ( ) => {
    dom.cl.toggle(inspector, 'hCompact');
};

/******************************************************************************/

const revert = ( ) => {
    dom.cl.remove('#domTree .off', 'off');
    contentInspectorChannel.send({ what: 'resetToggledNodes' });
    dom.cl.add(qs$(inspector, '.permatoolbar .revert'), 'disabled');
    dom.cl.add(qs$(inspector, '.permatoolbar .commit'), 'disabled');
};

/******************************************************************************/

const toggleOn = ( ) => {
    dom.cl.add('#inspectors', 'dom');
    window.addEventListener('beforeunload', toggleOff);
    dom.on(document, 'tabIdChanged', onTabIdChanged);
    dom.on(domTree, 'click', onClicked, true);
    dom.on(domTree, 'mouseover', onMouseOver, true);
    dom.on('#domInspector .vExpandToggler', 'click', toggleVExpandView);
    dom.on('#domInspector .vCompactToggler', 'click', toggleVCompactView);
    dom.on('#domInspector .hCompactToggler', 'click', toggleHCompactView);
    dom.on('#domInspector .permatoolbar .revert', 'click', revert);
    dom.on('#domInspector .permatoolbar .commit', 'click', startDialog);
    contentInspectorChannel.start();
    injectInspector();
};

/******************************************************************************/

const toggleOff = ( ) => {
    dom.cl.remove(showdomButton, 'active');
    dom.cl.remove('#inspectors', 'dom');
    shutdownInspector();
    window.removeEventListener('beforeunload', toggleOff);
    dom.off(document, 'tabIdChanged', onTabIdChanged);
    dom.off(domTree, 'click', onClicked, true);
    dom.off(domTree, 'mouseover', onMouseOver, true);
    dom.off('#domInspector .vExpandToggler', 'click', toggleVExpandView);
    dom.off('#domInspector .vCompactToggler', 'click', toggleVCompactView);
    dom.off('#domInspector .hCompactToggler', 'click', toggleHCompactView);
    dom.off('#domInspector .permatoolbar .revert', 'click', revert);
    dom.off('#domInspector .permatoolbar .commit', 'click', startDialog);
    contentInspectorChannel.shutdown();
    inspectedTabId = 0;
};

/******************************************************************************/

const toggle = ( ) => {
    if ( dom.cl.toggle(showdomButton, 'active') ) {
        toggleOn();
    } else {
        toggleOff();
    }
};

dom.on(showdomButton, 'click', toggle);

/******************************************************************************/

})();
