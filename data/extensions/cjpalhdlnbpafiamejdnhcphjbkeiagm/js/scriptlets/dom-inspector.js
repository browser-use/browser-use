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

/******************************************************************************/
/******************************************************************************/

(async ( ) => {

/******************************************************************************/

if ( typeof vAPI !== 'object' ) { return; }
if ( vAPI === null ) { return; }
if ( vAPI.domFilterer instanceof Object === false ) { return; }

if ( vAPI.inspectorFrame ) { return; }
vAPI.inspectorFrame = true;

const inspectorUniqueId = vAPI.randomToken();

const nodeToIdMap = new WeakMap(); // No need to iterate

let blueNodes = [];
const roRedNodes = new Map();    // node => current cosmetic filter
const rwRedNodes = new Set();    // node => new cosmetic filter (toggle node)
const rwGreenNodes = new Set();  // node => new exception cosmetic filter (toggle filter)
//const roGreenNodes = new Map();  // node => current exception cosmetic filter (can't toggle)

const reHasCSSCombinators = /[ >+~]/;

/******************************************************************************/

const domLayout = (( ) => {
    const skipTagNames = new Set([
        'br', 'head', 'link', 'meta', 'script', 'style', 'title'
    ]);
    const resourceAttrNames = new Map([
        [ 'a', 'href' ],
        [ 'iframe', 'src' ],
        [ 'img', 'src' ],
        [ 'object', 'data' ]
    ]);

    let idGenerator = 1;

    // This will be used to uniquely identify nodes across process.

    const newNodeId = node => {
        const nid = `n${(idGenerator++).toString(36)}`;
        nodeToIdMap.set(node, nid);
        return nid;
    };

    const selectorFromNode = node => {
        const tag = node.localName;
        let selector = CSS.escape(tag);
        // Id
        if ( typeof node.id === 'string' ) {
            let str = node.id.trim();
            if ( str !== '' ) {
                selector += `#${CSS.escape(str)}`;
            }
        }
        // Class
        const cl = node.classList;
        if ( cl ) {
            for ( let i = 0; i < cl.length; i++ ) {
                selector += `.${CSS.escape(cl[i])}`;
            }
        }
        // Tag-specific attributes
        const attr = resourceAttrNames.get(tag);
        if ( attr !== undefined ) {
            let str = node.getAttribute(attr) || '';
            str = str.trim();
            const pos = str.startsWith('data:') ? 5 : str.search(/[#?]/);
            let sw = '';
            if ( pos !== -1 ) {
                str = str.slice(0, pos);
                sw = '^';
            }
            if ( str !== '' ) {
                selector += `[${attr}${sw}="${CSS.escape(str, true)}"]`;
            }
        }
        return selector;
    };

    function DomRoot() {
        this.nid = newNodeId(document.body);
        this.lvl = 0;
        this.sel = 'body';
        this.cnt = 0;
        this.filter = roRedNodes.get(document.body);
    }

    function DomNode(node, level) {
        this.nid = newNodeId(node);
        this.lvl = level;
        this.sel = selectorFromNode(node);
        this.cnt = 0;
        this.filter = roRedNodes.get(node);
    }

    const domNodeFactory = (level, node) => {
        const localName = node.localName;
        if ( skipTagNames.has(localName) ) { return null; }
        // skip uBlock's own nodes
        if ( node === inspectorFrame ) { return null; }
        if ( level === 0 && localName === 'body' ) {
            return new DomRoot();
        }
        return new DomNode(node, level);
    };

    // Collect layout data

    const getLayoutData = ( ) => {
        const layout = [];
        const stack = [];
        let lvl = 0;
        let node = document.documentElement;
        if ( node === null ) { return layout; }

        for (;;) {
            const domNode = domNodeFactory(lvl, node);
            if ( domNode !== null ) {
                layout.push(domNode);
            }
            // children
            if ( domNode !== null && node.firstElementChild !== null ) {
                stack.push(node);
                lvl += 1;
                node = node.firstElementChild;
                continue;
            }
            // sibling
            if ( node instanceof Element ) {
                if ( node.nextElementSibling === null ) {
                    do {
                        node = stack.pop();
                        if ( !node ) { break; }
                        lvl -= 1;
                    } while ( node.nextElementSibling === null );
                    if ( !node ) { break; }
                }
                node = node.nextElementSibling;
            }
        }

        return layout;
    };

    // Descendant count for each node.

    const patchLayoutData = layout => {
        const stack = [];
        let ptr;
        let lvl = 0;
        let i = layout.length;

        while ( i-- ) {
            const domNode = layout[i];
            if ( domNode.lvl === lvl ) {
                stack[ptr] += 1;
                continue;
            }
            if ( domNode.lvl > lvl ) {
                while ( lvl < domNode.lvl ) {
                    stack.push(0);
                    lvl += 1;
                }
                ptr = lvl - 1;
                stack[ptr] += 1;
                continue;
            }
            // domNode.lvl < lvl
            const cnt = stack.pop();
            domNode.cnt = cnt;
            lvl -= 1;
            ptr = lvl - 1;
            stack[ptr] += cnt + 1;
        }
        return layout;
    };

    // Track and report mutations of the DOM

    let mutationObserver = null;
    let mutationTimer;
    let addedNodelists = [];
    let removedNodelist = [];

    const previousElementSiblingId = node => {
        let sibling = node;
        for (;;) {
            sibling = sibling.previousElementSibling;
            if ( sibling === null ) { return null; }
            if ( skipTagNames.has(sibling.localName) ) { continue; }
            return nodeToIdMap.get(sibling);
        }
    };

    const journalFromBranch = (root, newNodes, newNodeToIdMap) => {
        let node = root.firstElementChild;
        while ( node !== null ) {
            const domNode = domNodeFactory(undefined, node);
            if ( domNode !== null ) {
                newNodeToIdMap.set(domNode.nid, domNode);
                newNodes.push(node);
            }
            // down
            if ( node.firstElementChild !== null ) {
                node = node.firstElementChild;
                continue;
            }
            // right
            if ( node.nextElementSibling !== null ) {
                node = node.nextElementSibling;
                continue;
            }
            // up then right
            for (;;) {
                if ( node.parentElement === root ) { return; }
                node = node.parentElement;
                if ( node.nextElementSibling !== null ) {
                    node = node.nextElementSibling;
                    break;
                }
            }
        }
    };

    const journalFromMutations = ( ) => {
        mutationTimer = undefined;

        // This is used to temporarily hold all added nodes, before resolving
        // their node id and relative position.
        const newNodes = [];
        const journalEntries = [];
        const newNodeToIdMap = new Map();

        for ( const nodelist of addedNodelists ) {
            for ( const node of nodelist ) {
                if ( node.nodeType !== 1 ) { continue; }
                if ( node.parentElement === null ) { continue; }
                cosmeticFilterMapper.incremental(node);
                const domNode = domNodeFactory(undefined, node);
                if ( domNode !== null ) {
                    newNodeToIdMap.set(domNode.nid, domNode);
                    newNodes.push(node);
                }
                journalFromBranch(node, newNodes, newNodeToIdMap);
            }
        }
        addedNodelists = [];
        for ( const nodelist of removedNodelist ) {
            for ( const node of nodelist ) {
                if ( node.nodeType !== 1 ) { continue; }
                const nid = nodeToIdMap.get(node);
                if ( nid === undefined ) { continue; }
                journalEntries.push({ what: -1, nid });
            }
        }
        removedNodelist = [];
        for ( const node of newNodes ) {
            journalEntries.push({
                what: 1,
                nid: nodeToIdMap.get(node),
                u: nodeToIdMap.get(node.parentElement),
                l: previousElementSiblingId(node)
            });
        }

        if ( journalEntries.length === 0 ) { return; }

        contentInspectorChannel.toLogger({
            what: 'domLayoutIncremental',
            url: window.location.href,
            hostname: window.location.hostname,
            journal: journalEntries,
            nodes: Array.from(newNodeToIdMap)
        });
    };

    const onMutationObserved = mutationRecords => {
        for ( const record of mutationRecords ) {
            if ( record.addedNodes.length !== 0 ) {
                addedNodelists.push(record.addedNodes);
            }
            if ( record.removedNodes.length !== 0 ) {
                removedNodelist.push(record.removedNodes);
            }
        }
        if ( mutationTimer === undefined ) {
            mutationTimer = vAPI.setTimeout(journalFromMutations, 1000);
        }
    };

    // API

    const getLayout = ( ) => {
        cosmeticFilterMapper.reset();
        mutationObserver = new MutationObserver(onMutationObserved);
        mutationObserver.observe(document.body, {
            childList: true,
            subtree: true
        });

        return {
            what: 'domLayoutFull',
            url: window.location.href,
            hostname: window.location.hostname,
            layout: patchLayoutData(getLayoutData())
        };
    };

    const reset = ( ) => {
        shutdown();
    };

    const shutdown = ( ) => {
        if ( mutationTimer !== undefined ) {
            clearTimeout(mutationTimer);
            mutationTimer = undefined;
        }
        if ( mutationObserver !== null ) {
            mutationObserver.disconnect();
            mutationObserver = null;
        }
        addedNodelists = [];
        removedNodelist = [];
    };

    return {
        get: getLayout,
        reset,
        shutdown,
    };
})();

/******************************************************************************/
/******************************************************************************/

const cosmeticFilterMapper = (( ) => {
    const nodesFromStyleTag = rootNode => {
        const filterMap = roRedNodes;
        const details = vAPI.domFilterer.getAllSelectors();

        // Declarative selectors.
        for ( const block of (details.declarative || []) ) {
            for ( const selector of block.split(',\n') ) {
                let nodes;
                if ( reHasCSSCombinators.test(selector) ) {
                    nodes = document.querySelectorAll(selector);
                } else {
                    if (
                        filterMap.has(rootNode) === false &&
                        rootNode.matches(selector)
                    ) {
                        filterMap.set(rootNode, selector);
                    }
                    nodes = rootNode.querySelectorAll(selector);
                }
                for ( const node of nodes ) {
                    if ( filterMap.has(node) ) { continue; }
                    filterMap.set(node, selector);
                }
            }
        }

        // Procedural selectors.
        for ( const entry of (details.procedural || []) ) {
            const nodes = entry.exec();
            for ( const node of nodes ) {
                // Upgrade declarative selector to procedural one
                filterMap.set(node, entry.raw);
            }
        }
    };

    const incremental = rootNode => {
        nodesFromStyleTag(rootNode);
    };

    const reset = ( ) => {
        roRedNodes.clear();
        if ( document.documentElement !== null ) {
            incremental(document.documentElement);
        }
    };

    const shutdown = ( ) => {
        vAPI.domFilterer.toggle(true);
    };

    return {
        incremental,
        reset,
        shutdown,
    };
})();

/******************************************************************************/

const elementsFromSelector = function(selector, context) {
    if ( !context ) {
        context = document;
    }
    if ( selector.indexOf(':') !== -1 ) {
        const out = elementsFromSpecialSelector(selector);
        if ( out !== undefined ) { return out; }
    }
    // plain CSS selector
    try {
        return context.querySelectorAll(selector);
    } catch {
    }
    return [];
};

const elementsFromSpecialSelector = function(selector) {
    const out = [];
    let matches = /^(.+?):has\((.+?)\)$/.exec(selector);
    if ( matches !== null ) {
        let nodes;
        try {
            nodes = document.querySelectorAll(matches[1]);
        } catch {
            nodes = [];
        }
        for ( const node of nodes ) {
            if ( node.querySelector(matches[2]) === null ) { continue; }
            out.push(node);
        }
        return out;
    }

    matches = /^:xpath\((.+?)\)$/.exec(selector);
    if ( matches === null ) { return; }
    const xpr = document.evaluate(
        matches[1],
        document,
        null,
        XPathResult.UNORDERED_NODE_SNAPSHOT_TYPE,
        null
    );
    let i = xpr.snapshotLength;
    while ( i-- ) {
        out.push(xpr.snapshotItem(i));
    }
    return out;
};

/******************************************************************************/

const highlightElements = ( ) => {
    const paths = [];

    const path = [];
    for ( const elem of rwRedNodes.keys() ) {
        if ( elem === inspectorFrame ) { continue; }
        if ( rwGreenNodes.has(elem) ) { continue; }
        if ( typeof elem.getBoundingClientRect !== 'function' ) { continue; }
        const rect = elem.getBoundingClientRect();
        const xl = rect.left;
        const w = rect.width;
        const yt = rect.top;
        const h = rect.height;
        const ws = w.toFixed(1);
        const poly = 'M' + xl.toFixed(1) + ' ' + yt.toFixed(1) +
               'h' + ws +
               'v' + h.toFixed(1) +
               'h-' + ws +
               'z';
        path.push(poly);
    }
    paths.push(path.join('') || 'M0 0');

    path.length = 0;
    for ( const elem of rwGreenNodes ) {
        if ( typeof elem.getBoundingClientRect !== 'function' ) { continue; }
        const rect = elem.getBoundingClientRect();
        const xl = rect.left;
        const w = rect.width;
        const yt = rect.top;
        const h = rect.height;
        const ws = w.toFixed(1);
        const poly = 'M' + xl.toFixed(1) + ' ' + yt.toFixed(1) +
               'h' + ws +
               'v' + h.toFixed(1) +
               'h-' + ws +
               'z';
        path.push(poly);
    }
    paths.push(path.join('') || 'M0 0');

    path.length = 0;
    for ( const elem of roRedNodes.keys() ) {
        if ( elem === inspectorFrame ) { continue; }
        if ( rwGreenNodes.has(elem) ) { continue; }
        if ( typeof elem.getBoundingClientRect !== 'function' ) { continue; }
        const rect = elem.getBoundingClientRect();
        const xl = rect.left;
        const w = rect.width;
        const yt = rect.top;
        const h = rect.height;
        const ws = w.toFixed(1);
        const poly = 'M' + xl.toFixed(1) + ' ' + yt.toFixed(1) +
               'h' + ws +
               'v' + h.toFixed(1) +
               'h-' + ws +
               'z';
        path.push(poly);
    }
    paths.push(path.join('') || 'M0 0');

    path.length = 0;
    for ( const elem of blueNodes ) {
        if ( elem === inspectorFrame ) { continue; }
        if ( typeof elem.getBoundingClientRect !== 'function' ) { continue; }
        const rect = elem.getBoundingClientRect();
        const xl = rect.left;
        const w = rect.width;
        const yt = rect.top;
        const h = rect.height;
        const ws = w.toFixed(1);
        const poly = 'M' + xl.toFixed(1) + ' ' + yt.toFixed(1) +
               'h' + ws +
               'v' + h.toFixed(1) +
               'h-' + ws +
               'z';
        path.push(poly);
    }
    paths.push(path.join('') || 'M0 0');

    contentInspectorChannel.toFrame({
        what: 'svgPaths',
        paths,
    });
};

/******************************************************************************/

const onScrolled = (( ) => {
    let timer;
    return ( ) => {
        if ( timer ) { return; }
        timer = window.requestAnimationFrame(( ) => {
            timer = undefined;
            highlightElements();
        });
    };
})();

const onMouseOver = ( ) => {
    if ( blueNodes.length === 0 ) { return; }
    blueNodes = [];
    highlightElements();
};

/******************************************************************************/

const selectNodes = (selector, nid) => {
    const nodes = elementsFromSelector(selector);
    if ( nid === '' ) { return nodes; }
    for ( const node of nodes ) {
        if ( nodeToIdMap.get(node) === nid ) {
            return [ node ];
        }
    }
    return [];
};

/******************************************************************************/

const nodesFromFilter = selector => {
    const out = [];
    for ( const entry of roRedNodes ) {
        if ( entry[1] === selector ) {
            out.push(entry[0]);
        }
    }
    return out;
};

/******************************************************************************/

const toggleExceptions = (nodes, targetState) => {
    for ( const node of nodes ) {
        if ( targetState ) {
            rwGreenNodes.add(node);
        } else {
            rwGreenNodes.delete(node);
        }
    }
};

const toggleFilter = (nodes, targetState) => {
    for ( const node of nodes ) {
        if ( targetState ) {
            rwRedNodes.delete(node);
        } else {
            rwRedNodes.add(node);
        }
    }
};

const resetToggledNodes = ( ) => {
    rwGreenNodes.clear();
    rwRedNodes.clear();
};

/******************************************************************************/

const startInspector = ( ) => {
    const onReady = ( ) => {
        window.addEventListener('scroll', onScrolled, {
            capture: true,
            passive: true,
        });
        window.addEventListener('mouseover', onMouseOver, {
            capture: true,
            passive: true,
        });
        contentInspectorChannel.toLogger(domLayout.get());
        vAPI.domFilterer.toggle(false, highlightElements);
    };
    if ( document.readyState === 'loading' ) {
        document.addEventListener('DOMContentLoaded', onReady, { once: true });
    } else {
        onReady();
    }
};

/******************************************************************************/

const shutdownInspector = ( ) => {
    cosmeticFilterMapper.shutdown();
    domLayout.shutdown();
    window.removeEventListener('scroll', onScrolled, {
        capture: true,
        passive: true,
    });
    window.removeEventListener('mouseover', onMouseOver, {
        capture: true,
        passive: true,
    });
    contentInspectorChannel.shutdown();
    if ( inspectorFrame ) {
        inspectorFrame.remove();
        inspectorFrame = null;
    }
    vAPI.userStylesheet.remove(inspectorCSS);
    vAPI.userStylesheet.apply();
    vAPI.inspectorFrame = false;
};

/******************************************************************************/
/******************************************************************************/

const onMessage = request => {
    switch ( request.what ) {
    case 'startInspector':
        startInspector();
        break;

    case 'quitInspector':
        shutdownInspector();
        break;

    case 'commitFilters':
        highlightElements();
        break;

    case 'domLayout':
        domLayout.get();
        highlightElements();
        break;

    case 'highlightMode':
        break;

    case 'highlightOne':
        blueNodes = selectNodes(request.selector, request.nid);
        if ( blueNodes.length !== 0 ) {
            blueNodes[0].scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest',
            });
        }
        highlightElements();
        break;

    case 'resetToggledNodes':
        resetToggledNodes();
        highlightElements();
        break;

    case 'showCommitted':
        blueNodes = [];
        // TODO: show only the new filters and exceptions.
        highlightElements();
        break;

    case 'showInteractive':
        blueNodes = [];
        highlightElements();
        break;

    case 'toggleFilter': {
        const nodes = selectNodes(request.selector, request.nid);
        if ( nodes.length !== 0 ) {
            nodes[0].scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest',
            });
        }
        toggleExceptions(nodesFromFilter(request.filter), request.target);
        highlightElements();
        break;
    }
    case 'toggleNodes': {
        const nodes = selectNodes(request.selector, request.nid);
        if ( nodes.length !== 0 ) {
            nodes[0].scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest',
            });
        }
        toggleFilter(nodes, request.target);
        highlightElements();
        break;
    }
    default:
        break;
    }
};

/*******************************************************************************
 * 
 * Establish two-way communication with logger/inspector window and
 * inspector frame
 * 
 * */

const contentInspectorChannel = (( ) => {
    let toLoggerPort;
    let toFramePort;

    const toLogger = msg => {
        if ( toLoggerPort === undefined ) { return; }
        try {
            toLoggerPort.postMessage(msg);
        } catch {
            shutdownInspector();
        }
    };

    const onLoggerMessage = msg => {
        onMessage(msg);
    };

    const onLoggerDisconnect = ( ) => {
        shutdownInspector();
    };

    const onLoggerConnect = port => {
        browser.runtime.onConnect.removeListener(onLoggerConnect);
        toLoggerPort = port;
        port.onMessage.addListener(onLoggerMessage);
        port.onDisconnect.addListener(onLoggerDisconnect);
    };

    const toFrame = msg => {
        if ( toFramePort === undefined ) { return; }
        toFramePort.postMessage(msg);
    };

    const shutdown = ( ) => {
        if ( toFramePort !== undefined ) {
            toFrame({ what: 'quitInspector' });
            toFramePort.onmessage = null;
            toFramePort.close();
            toFramePort = undefined;
        }
        if ( toLoggerPort !== undefined ) {
            toLoggerPort.onMessage.removeListener(onLoggerMessage);
            toLoggerPort.onDisconnect.removeListener(onLoggerDisconnect);
            toLoggerPort.disconnect();
            toLoggerPort = undefined;
        }
        browser.runtime.onConnect.removeListener(onLoggerConnect);
    };

    const start = async ( ) => {
        browser.runtime.onConnect.addListener(onLoggerConnect);
        const inspectorArgs = await vAPI.messaging.send('domInspectorContent', {
            what: 'getInspectorArgs',
        });
        if ( typeof inspectorArgs !== 'object' ) { return; }
        if ( inspectorArgs === null ) { return; }
        return new Promise(resolve => {
            const iframe = document.createElement('iframe');
            iframe.setAttribute(inspectorUniqueId, '');
            document.documentElement.append(iframe);
            iframe.addEventListener('load', ( ) => {
                iframe.setAttribute(`${inspectorUniqueId}-loaded`, '');
                const channel = new MessageChannel();
                toFramePort = channel.port1;
                toFramePort.onmessage = ev => {
                    const msg = ev.data || {};
                    if ( msg.what !== 'startInspector' ) { return; }
                };
                iframe.contentWindow.postMessage(
                    { what: 'startInspector' },
                    inspectorArgs.inspectorURL,
                    [ channel.port2 ]
                );
                resolve(iframe);
            }, { once: true });
            iframe.contentWindow.location = inspectorArgs.inspectorURL;
        });
    };

    return { start, toLogger, toFrame, shutdown };
})();


// Install DOM inspector widget
const inspectorCSSStyle = [
    'background: transparent',
    'border: 0',
    'border-radius: 0',
    'box-shadow: none',
    'color-scheme: light dark',
    'display: block',
    'filter: none',
    'height: 100%',
    'left: 0',
    'margin: 0',
    'max-height: none',
    'max-width: none',
    'min-height: unset',
    'min-width: unset',
    'opacity: 1',
    'outline: 0',
    'padding: 0',
    'pointer-events: none',
    'position: fixed',
    'top: 0',
    'transform: none',
    'visibility: hidden',
    'width: 100%',
    'z-index: 2147483647',
    ''
].join(' !important;\n');

const inspectorCSS = `
:root > [${inspectorUniqueId}] {
    ${inspectorCSSStyle}
}
:root > [${inspectorUniqueId}-loaded] {
    visibility: visible !important;
}
`;

vAPI.userStylesheet.add(inspectorCSS);
vAPI.userStylesheet.apply();

let inspectorFrame = await contentInspectorChannel.start();
if ( inspectorFrame instanceof HTMLIFrameElement === false ) {
    return shutdownInspector();
}

startInspector();

/******************************************************************************/

})();








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;
