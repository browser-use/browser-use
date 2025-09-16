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

(async ( ) => {

/******************************************************************************/

if ( typeof vAPI !== 'object' ) { return; }
if ( vAPI === null ) { return; }

if ( vAPI.pickerFrame ) { return; }
vAPI.pickerFrame = true;

const pickerUniqueId = vAPI.randomToken();

const reCosmeticAnchor = /^#(\$|\?|\$\?)?#/;

const netFilterCandidates = [];
const cosmeticFilterCandidates = [];

let targetElements = [];
let candidateElements = [];
let bestCandidateFilter = null;

const lastNetFilterSession = window.location.host + window.location.pathname;
let lastNetFilterHostname = '';
let lastNetFilterUnion = '';

const hideBackgroundStyle = 'background-image:none!important;';

/******************************************************************************/

const safeQuerySelectorAll = function(node, selector) {
    if ( node !== null ) {
        try {
            return node.querySelectorAll(selector);
        } catch {
        }
    }
    return [];
};

/******************************************************************************/

const getElementBoundingClientRect = function(elem) {
    let rect = typeof elem.getBoundingClientRect === 'function'
        ? elem.getBoundingClientRect()
        : { height: 0, left: 0, top: 0, width: 0 };

    // https://github.com/gorhill/uBlock/issues/1024
    // Try not returning an empty bounding rect.
    if ( rect.width !== 0 && rect.height !== 0 ) {
        return rect;
    }
    if ( elem.shadowRoot instanceof DocumentFragment ) {
        return getElementBoundingClientRect(elem.shadowRoot);
    }

    let left = rect.left,
        right = left + rect.width,
        top = rect.top,
        bottom = top + rect.height;

    for ( const child of elem.children ) {
        rect = getElementBoundingClientRect(child);
        if ( rect.width === 0 || rect.height === 0 ) { continue; }
        if ( rect.left < left ) { left = rect.left; }
        if ( rect.right > right ) { right = rect.right; }
        if ( rect.top < top ) { top = rect.top; }
        if ( rect.bottom > bottom ) { bottom = rect.bottom; }
    }

    return {
        bottom,
        height: bottom - top,
        left,
        right,
        top,
        width: right - left
    };
};

/******************************************************************************/

const highlightElements = function(elems, force) {
    // To make mouse move handler more efficient
    if (
        (force !== true) &&
        (elems.length === targetElements.length) &&
        (elems.length === 0 || elems[0] === targetElements[0])
    ) {
        return;
    }
    targetElements = [];

    const ow = self.innerWidth;
    const oh = self.innerHeight;
    const islands = [];

    for ( const elem of elems ) {
        if ( elem === pickerFrame ) { continue; }
        targetElements.push(elem);
        const rect = getElementBoundingClientRect(elem);
        // Ignore offscreen areas
        if (
            rect.left > ow || rect.top > oh ||
            rect.left + rect.width < 0 || rect.top + rect.height < 0
        ) {
            continue;
        }
        islands.push(
            `M${rect.left} ${rect.top}h${rect.width}v${rect.height}h-${rect.width}z`
        );
    }

    pickerFramePort.postMessage({
        what: 'svgPaths',
        ocean: `M0 0h${ow}v${oh}h-${ow}z`,
        islands: islands.join(''),
    });
};

/******************************************************************************/

const mergeStrings = function(urls) {
    if ( urls.length === 0 ) { return ''; }
    if (
        urls.length === 1 ||
        self.diff_match_patch instanceof Function === false
    ) {
        return urls[0];
    }
    const differ = new self.diff_match_patch();
    let merged = urls[0];
    for ( let i = 1; i < urls.length; i++ ) {
        // The differ works at line granularity: we insert a linefeed after
        // each character to trick the differ to work at character granularity.
        const diffs = differ.diff_main(
            urls[i].split('').join('\n'),
            merged.split('').join('\n')
        );
        const result = [];
        for ( const diff of diffs ) {
            if ( diff[0] !== 0 ) {
                result.push('*');
            } else {
                result.push(diff[1].replace(/\n+/g, ''));
            }
            merged = result.join('');
        }
    }
    // Keep usage of wildcards to a sane level, too many of them can cause
    // high overhead filters
    merged = merged.replace(/^\*+$/, '')
                   .replace(/\*{2,}/g, '*')
                   .replace(/([^*]{1,3}\*)(?:[^*]{1,3}\*)+/g, '$1');

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1494
    let pos = merged.indexOf('/');
    if ( pos === -1 ) { pos = merged.length; }
    return merged.slice(0, pos).includes('*') ? urls[0] : merged;
};

/******************************************************************************/

// Remove fragment part from a URL.

const trimFragmentFromURL = function(url) {
    const pos = url.indexOf('#');
    return pos !== -1 ? url.slice(0, pos) : url;
};

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/1897
// Ignore `data:` URI, they can't be handled by an HTTP observer.

const backgroundImageURLFromElement = function(elem) {
    const style = window.getComputedStyle(elem);
    const bgImg = style.backgroundImage || '';
    const matches = /^url\((["']?)([^"']+)\1\)$/.exec(bgImg);
    const url = matches !== null && matches.length === 3 ? matches[2] : '';
    return url.lastIndexOf('data:', 0) === -1
        ? trimFragmentFromURL(url.slice(0, 1024))
        : '';
};

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/1725#issuecomment-226479197
//   Limit returned string to 1024 characters.
//   Also, return only URLs which will be seen by an HTTP observer.
// https://github.com/uBlockOrigin/uBlock-issues/issues/2260
//   Maybe get to the actual URL indirectly.
const resourceURLsFromElement = function(elem) {
    const urls = [];
    const tagName = elem.localName;
    const prop = netFilter1stSources[tagName];
    if ( prop === undefined ) {
        const url = backgroundImageURLFromElement(elem);
        if ( url !== '' ) { urls.push(url); }
        return urls;
    }
    let s = elem[prop];
    if ( s instanceof SVGAnimatedString ) {
        s = s.baseVal;
    }
    if ( typeof s === 'string' && /^https?:\/\//.test(s) ) {
        urls.push(trimFragmentFromURL(s.slice(0, 1024)));
    }
    resourceURLsFromSrcset(elem, urls);
    resourceURLsFromPicture(elem, urls);
    return urls;
};

// https://html.spec.whatwg.org/multipage/images.html#parsing-a-srcset-attribute
// https://github.com/uBlockOrigin/uBlock-issues/issues/1071
const resourceURLsFromSrcset = function(elem, out) {
    let srcset = elem.srcset;
    if ( typeof srcset !== 'string' || srcset === '' ) { return; }
    for(;;) {
        // trim whitespace
        srcset = srcset.trim();
        if ( srcset.length === 0 ) { break; }
        // abort in case of leading comma
        if ( /^,/.test(srcset) ) { break; }
        // collect and consume all non-whitespace characters
        let match = /^\S+/.exec(srcset);
        if ( match === null ) { break; }
        srcset = srcset.slice(match.index + match[0].length);
        let url = match[0];
        // consume descriptor, if any
        if ( /,$/.test(url) ) {
            url = url.replace(/,$/, '');
            if ( /,$/.test(url) ) { break; }
        } else {
            match = /^[^,]*(?:\(.+?\))?[^,]*(?:,|$)/.exec(srcset);
            if ( match === null ) { break; }
            srcset = srcset.slice(match.index + match[0].length);
        }
        const parsedURL = new URL(url, document.baseURI);
        if ( parsedURL.pathname.length === 0 ) { continue; }
        out.push(trimFragmentFromURL(parsedURL.href));
    }
};

// https://github.com/uBlockOrigin/uBlock-issues/issues/2069#issuecomment-1080600661
// https://developer.mozilla.org/en-US/docs/Web/HTML/Element/picture
const resourceURLsFromPicture = function(elem, out) {
    if ( elem.localName === 'source' ) { return; }
    const picture = elem.parentElement;
    if ( picture === null || picture.localName !== 'picture' ) { return; }
    const sources = picture.querySelectorAll(':scope > source');
    for ( const source of sources ) {
        const urls = resourceURLsFromElement(source);
        if ( urls.length === 0 ) { continue; }
        out.push(...urls);
    }
};

/******************************************************************************/

const netFilterFromUnion = function(patternIn, out) {
    // Reset reference filter when dealing with unrelated URLs
    const currentHostname = self.location.hostname;
    if (
        lastNetFilterUnion === '' ||
        currentHostname === '' ||
        currentHostname !== lastNetFilterHostname
    ) {
        lastNetFilterHostname = currentHostname;
        lastNetFilterUnion = patternIn;
        vAPI.messaging.send('elementPicker', {
            what: 'elementPickerEprom',
            lastNetFilterSession,
            lastNetFilterHostname,
            lastNetFilterUnion,
        });
        return;
    }

    // Related URLs
    lastNetFilterHostname = currentHostname;
    let patternOut = mergeStrings([ patternIn, lastNetFilterUnion ]);
    if ( patternOut !== '/*' && patternOut !== patternIn ) {
        const filter = `||${patternOut}`;
        if ( out.indexOf(filter) === -1 ) {
            out.push(filter);
        }
        lastNetFilterUnion = patternOut;
    }

    // Remember across element picker sessions
    vAPI.messaging.send('elementPicker', {
        what: 'elementPickerEprom',
        lastNetFilterSession,
        lastNetFilterHostname,
        lastNetFilterUnion,
    });
};

/******************************************************************************/

// Extract the best possible net filter, i.e. as specific as possible.

const netFilterFromElement = function(elem) {
    if ( elem === null ) { return 0; }
    if ( elem.nodeType !== 1 ) { return 0; }
    const urls = resourceURLsFromElement(elem);
    if ( urls.length === 0 ) { return 0; }

    if ( candidateElements.indexOf(elem) === -1 ) {
        candidateElements.push(elem);
    }

    const candidates = netFilterCandidates;
    const len = candidates.length;

    for ( let i = 0; i < urls.length; i++ ) {
        urls[i] = urls[i].replace(/^https?:\/\//, '');
    }
    const pattern = mergeStrings(urls);


    if ( bestCandidateFilter === null && elem.matches('html,body') === false ) {
        bestCandidateFilter = {
            type: 'net',
            filters: candidates,
            slot: candidates.length
        };
    }

    candidates.push(`||${pattern}`);

    // Suggest a less narrow filter if possible
    const pos = pattern.indexOf('?');
    if ( pos !== -1 ) {
        candidates.push(`||${pattern.slice(0, pos)}`);
    }

    // Suggest a filter which is a result of combining more than one URL.
    netFilterFromUnion(pattern, candidates);

    return candidates.length - len;
};

const netFilter1stSources = {
     'audio': 'src',
     'embed': 'src',
    'iframe': 'src',
       'img': 'src',
     'image': 'href',
    'object': 'data',
    'source': 'src',
     'video': 'src'
};

const filterTypes = {
     'audio': 'media',
     'embed': 'object',
    'iframe': 'subdocument',
       'img': 'image',
    'object': 'object',
     'video': 'media',
};

/******************************************************************************/

// Extract the best possible cosmetic filter, i.e. as specific as possible.

// https://github.com/gorhill/uBlock/issues/1725
//   Also take into account the `src` attribute for `img` elements -- and limit
//   the value to the 1024 first characters.

const cosmeticFilterFromElement = function(elem) {
    if ( elem === null ) { return 0; }
    if ( elem.nodeType !== 1 ) { return 0; }
    if ( noCosmeticFiltering ) { return 0; }

    if ( candidateElements.indexOf(elem) === -1 ) {
        candidateElements.push(elem);
    }

    let selector = '';

    // Id
    let v = typeof elem.id === 'string' && CSS.escape(elem.id);
    if ( v ) {
        selector = '#' + v;
    }

    // Class(es)
    v = elem.classList;
    if ( v ) {
        let i = v.length || 0;
        while ( i-- ) {
            selector += '.' + CSS.escape(v.item(i));
        }
    }

    // Tag name
    const tagName = CSS.escape(elem.localName);

    // Use attributes if still no selector found.
    // https://github.com/gorhill/uBlock/issues/1901
    //   Trim attribute value, this may help in case of malformed HTML.
    //
    // https://github.com/uBlockOrigin/uBlock-issues/issues/1923
    //   Escape unescaped `"` in attribute values
    if ( selector === '' ) {
        let attributes = [], attr;
        switch ( tagName ) {
        case 'a':
            v = elem.getAttribute('href');
            if ( v ) {
                v = v.trim().replace(/\?.*$/, '');
                if ( v.length ) {
                    attributes.push({ k: 'href', v: v });
                }
            }
            break;
        case 'iframe':
        case 'img':
            v = elem.getAttribute('src');
            if ( v && v.length !== 0 ) {
                v = v.trim();
                if ( v.startsWith('data:') ) {
                    let pos = v.indexOf(',');
                    if ( pos !== -1 ) {
                        v = v.slice(0, pos + 1);
                    }
                } else if ( v.startsWith('blob:') ) {
                    v = new URL(v.slice(5));
                    v.pathname = '';
                    v = 'blob:' + v.href;
                }
                attributes.push({ k: 'src', v: v.slice(0, 256) });
                break;
            }
            v = elem.getAttribute('alt');
            if ( v && v.length !== 0 ) {
                attributes.push({ k: 'alt', v: v });
                break;
            }
            break;
        default:
            break;
        }
        while ( (attr = attributes.pop()) ) {
            if ( attr.v.length === 0 ) { continue; }
            const w = attr.v.replace(/([^\\])"/g, '$1\\"');
            v = elem.getAttribute(attr.k);
            if ( attr.v === v ) {
                selector += `[${attr.k}="${w}"]`;
            } else if ( v.startsWith(attr.v) ) {
                selector += `[${attr.k}^="${w}"]`;
            } else {
                selector += `[${attr.k}*="${w}"]`;
            }
        }
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/17
    //   If selector is ambiguous at this point, add the element name to
    //   further narrow it down.
    const parentNode = elem.parentNode;
    if (
        selector === '' ||
        safeQuerySelectorAll(parentNode, `:scope > ${selector}`).length > 1
    ) {
        selector = tagName + selector;
    }

    // https://github.com/chrisaljoudi/uBlock/issues/637
    //   If the selector is still ambiguous at this point, further narrow using
    //   `nth-of-type`. It is preferable to use `nth-of-type` as opposed to
    //   `nth-child`, as `nth-of-type` is less volatile.
    if ( safeQuerySelectorAll(parentNode, `:scope > ${selector}`).length > 1 ) {
        let i = 1;
        while ( elem.previousSibling !== null ) {
            elem = elem.previousSibling;
            if (
                typeof elem.localName === 'string' &&
                elem.localName === tagName
            ) {
                i++;
            }
        }
        selector += `:nth-of-type(${i})`;
    }

    if ( bestCandidateFilter === null ) {
        bestCandidateFilter = {
            type: 'cosmetic',
            filters: cosmeticFilterCandidates,
            slot: cosmeticFilterCandidates.length
        };
    }

    cosmeticFilterCandidates.push(`##${selector}`);

    return 1;
};

/******************************************************************************/

const filtersFrom = function(x, y) {
    bestCandidateFilter = null;
    netFilterCandidates.length = 0;
    cosmeticFilterCandidates.length = 0;
    candidateElements.length = 0;

    // We need at least one element.
    let first = null;
    if ( typeof x === 'number' ) {
        first = elementFromPoint(x, y);
    } else if ( x instanceof HTMLElement ) {
        first = x;
        x = undefined;
    }

    // https://github.com/gorhill/uBlock/issues/1545
    //   Network filter candidates from all other elements found at [x,y].
    // https://www.reddit.com/r/uBlockOrigin/comments/qmjk36/
    //   Extract network candidates first.
    if ( typeof x === 'number' ) {
        const magicAttr = `${pickerUniqueId}-clickblind`;
        pickerFrame.setAttribute(magicAttr, '');
        const elems = document.elementsFromPoint(x, y);
        pickerFrame.removeAttribute(magicAttr);
        for ( const elem of elems ) {
            netFilterFromElement(elem);
        }
    } else if ( first !== null ) {
        netFilterFromElement(first);
    }

    // Cosmetic filter candidates from ancestors.
    // https://github.com/gorhill/uBlock/issues/2519
    // https://github.com/uBlockOrigin/uBlock-issues/issues/17
    //   Prepend `body` if full selector is ambiguous.
    let elem = first;
    while ( elem && elem !== document.body ) {
        cosmeticFilterFromElement(elem);
        elem = elem.parentNode;
    }
    // The body tag is needed as anchor only when the immediate child
    // uses `nth-of-type`.
    let i = cosmeticFilterCandidates.length;
    if ( i !== 0 ) {
        const selector = cosmeticFilterCandidates[i-1].slice(2);
        if ( safeQuerySelectorAll(document.body, selector).length > 1 ) {
            cosmeticFilterCandidates.push('##body');
        }
    }

    // https://github.com/gorhill/uBlock/commit/ebaa8a8bb28aef043a68c99965fe6c128a3fe5e4#commitcomment-63818019
    //   If still no best candidate, just use whatever is available in network
    //   filter candidates -- which may have been previously skipped in favor
    //   of cosmetic filters.
    if ( bestCandidateFilter === null && netFilterCandidates.length !== 0 ) {
        bestCandidateFilter = {
            type: 'net',
            filters: netFilterCandidates,
            slot: 0
        };
    }

    return netFilterCandidates.length + cosmeticFilterCandidates.length;
};

/*******************************************************************************

    filterToDOMInterface.queryAll
    @desc   Look-up all the HTML elements matching the filter passed in
            argument.
    @param  string, a cosmetic or network filter.
    @param  function, called once all items matching the filter have been
            collected.
    @return array, or undefined if the filter is invalid.

    filterToDOMInterface.preview
    @desc   Apply/unapply filter to the DOM.
    @param  string, a cosmetic of network filter, or literal false to remove
            the effects of the filter on the DOM.
    @return undefined.

    TODO: need to be revised once I implement chained cosmetic operators.

*/

const filterToDOMInterface = (( ) => {
    const reHnAnchorPrefix = '^[\\w-]+://(?:[^/?#]+\\.)?';
    const reCaret = '(?:[^%.0-9a-z_-]|$)';
    const rePseudoElements = /:(?::?after|:?before|:[a-z-]+)$/;

    const matchElemToRegex = (elem, re) => {
        const srcProp = netFilter1stSources[elem.localName];
        let src = elem[srcProp];
        if ( src instanceof SVGAnimatedString ) {
            src = src.baseVal;
        }
        if ( typeof src === 'string' && /^https?:\/\//.test(src) ) {
            if ( re.test(src) ) { return srcProp; }
        }
        src = elem.currentSrc;
        if ( typeof src === 'string' && /^https?:\/\//.test(src) ) {
            if ( re.test(src) ) { return srcProp; }
        }
    };

    // Net filters: we need to lookup manually -- translating into a foolproof
    // CSS selector is just not possible.
    //
    // https://github.com/chrisaljoudi/uBlock/issues/945
    //   Transform into a regular expression, this allows the user to
    //   edit and insert wildcard(s) into the proposed filter.
    // https://www.reddit.com/r/uBlockOrigin/comments/c5do7w/
    //   Better handling of pure hostname filters. Also, discard single
    //   alphanumeric character filters.
    const fromNetworkFilter = function(filter) {
        const out = [];
        if ( /^[0-9a-z]$/i.test(filter) ) { return out; }
        let reStr = '';
        if (
            filter.length > 2 &&
            filter.startsWith('/') &&
            filter.endsWith('/')
        ) {
            reStr = filter.slice(1, -1);
        } else if ( /^\w[\w.-]*[a-z]$/i.test(filter) ) {
            reStr = reHnAnchorPrefix +
                    filter.toLowerCase().replace(/\./g, '\\.') +
                    reCaret;
        } else {
            let rePrefix = '', reSuffix = '';
            if ( filter.startsWith('||') ) {
                rePrefix = reHnAnchorPrefix;
                filter = filter.slice(2);
            } else if ( filter.startsWith('|') ) {
                rePrefix = '^';
                filter = filter.slice(1);   
            }
            if ( filter.endsWith('|') ) {
                reSuffix = '$';
                filter = filter.slice(0, -1);
            }
            reStr = rePrefix +
                    filter.replace(/[.+?${}()|[\]\\]/g, '\\$&')
                          .replace(/\*+/g, '.*')
                          .replace(/\^/g, reCaret) +
                    reSuffix;
        }
        let reFilter = null;
        try {
            reFilter = new RegExp(reStr, 'i');
        } catch {
            return out;
        }

        // Lookup by tag names.
        // https://github.com/uBlockOrigin/uBlock-issues/issues/2260
        //   Maybe get to the actual URL indirectly.
        //
        // https://github.com/uBlockOrigin/uBlock-issues/issues/3142
        //   Don't try to match against non-network URIs.
        const elems = document.querySelectorAll(
            Object.keys(netFilter1stSources).join()
        );
        for ( const elem of elems ) {
            const srcProp = matchElemToRegex(elem, reFilter);
            if ( srcProp === undefined ) { continue; }
            out.push({
                elem,
                src: srcProp,
                opt: filterTypes[elem.localName],
                style: vAPI.hideStyle,
            });
        }

        // Find matching background image in current set of candidate elements.
        for ( const elem of candidateElements ) {
            if ( reFilter.test(backgroundImageURLFromElement(elem)) ) {
                out.push({
                    elem,
                    bg: true,
                    opt: 'image',
                    style: hideBackgroundStyle,
                });
            }
        }

        return out;
    };

    // Cosmetic filters: these are straight CSS selectors.
    //
    // https://github.com/uBlockOrigin/uBlock-issues/issues/389
    //   Test filter using comma-separated list to better detect invalid CSS
    //   selectors.
    //
    // https://github.com/gorhill/uBlock/issues/2515
    //   Remove trailing pseudo-element when querying.
    const fromPlainCosmeticFilter = function(raw) {
        let elems;
        try {
            document.documentElement.matches(`${raw},\na`);
            elems = document.querySelectorAll(
                raw.replace(rePseudoElements, '')
            );
        } catch {
            return;
        }
        const out = [];
        for ( const elem of elems ) {
            if ( elem === pickerFrame ) { continue; }
            out.push({ elem, raw, style: vAPI.hideStyle });
        }
        return out;
    };

    // https://github.com/gorhill/uBlock/issues/1772
    //   Handle procedural cosmetic filters.
    //
    // https://github.com/gorhill/uBlock/issues/2515
    //   Remove trailing pseudo-element when querying.
    const fromCompiledCosmeticFilter = function(raw) {
        if ( noCosmeticFiltering ) { return; }
        if ( typeof raw !== 'string' ) { return; }
        let elems, style;
        try {
            const o = JSON.parse(raw);
            elems = vAPI.domFilterer.createProceduralFilter(o).exec();
            switch ( o.action && o.action[0] || '' ) {
            case '':
            case 'remove':
                style = vAPI.hideStyle;
                break;
            case 'style':
                style = o.action[1];
                break;
            default:
                break;
            }
        } catch {
            return;
        }
        if ( !elems ) { return; }
        const out = [];
        for ( const elem of elems ) {
            out.push({ elem, raw, style });
        }
        return out;
    };

    vAPI.epickerStyleProxies = vAPI.epickerStyleProxies || new Map();

    let lastFilter;
    let lastResultset;
    let previewing = false;

    const queryAll = function(details) {
        let { filter, compiled } = details;
        filter = filter.trim();
        if ( filter === lastFilter ) { return lastResultset; }
        unapply();
        if ( filter === '' || filter === '!' ) {
            lastFilter = '';
            lastResultset = undefined;
            return;
        }
        lastFilter = filter;
        if ( reCosmeticAnchor.test(filter) === false ) {
            lastResultset = fromNetworkFilter(filter);
            if ( previewing ) { apply(); }
            return lastResultset;
        }
        lastResultset = fromPlainCosmeticFilter(compiled);
        if ( lastResultset ) {
            if ( previewing ) { apply(); }
            return lastResultset;
        }
        // Procedural cosmetic filter
        lastResultset = fromCompiledCosmeticFilter(compiled);
        if ( previewing ) { apply(); }
        return lastResultset;
    };

    const apply = function() {
        unapply();
        if ( Array.isArray(lastResultset) === false ) { return; }
        const rootElem = document.documentElement;
        for ( const { elem, style } of lastResultset ) {
            if ( elem === pickerFrame ) { continue; }
            if ( style === undefined ) { continue; }
            if ( elem === rootElem && style === vAPI.hideStyle ) { continue; }
            let styleToken = vAPI.epickerStyleProxies.get(style);
            if ( styleToken === undefined ) {
                styleToken = vAPI.randomToken();
                vAPI.epickerStyleProxies.set(style, styleToken);
                vAPI.userStylesheet.add(`[${styleToken}]\n{${style}}`, true);
            }
            elem.setAttribute(styleToken, '');
        }
    };

    const unapply = function() {
        for ( const styleToken of vAPI.epickerStyleProxies.values() ) {
            for ( const elem of document.querySelectorAll(`[${styleToken}]`) ) {
                elem.removeAttribute(styleToken);
            }
        }
    };

    // https://www.reddit.com/r/uBlockOrigin/comments/c62irc/
    //   Support injecting the cosmetic filters into the DOM filterer
    //   immediately rather than wait for the next page load.
    const preview = function(state, permanent = false) {
        previewing = state !== false;
        if ( previewing === false ) {
            return unapply();
        }
        if ( Array.isArray(lastResultset) === false ) { return; }
        if ( permanent === false || reCosmeticAnchor.test(lastFilter) === false ) {
            return apply();
        }
        if ( noCosmeticFiltering ) { return; }
        const cssSelectors = new Set();
        const proceduralSelectors = new Set();
        for ( const { raw } of lastResultset ) {
            if ( raw.startsWith('{') ) {
                proceduralSelectors.add(raw);
            } else {
                cssSelectors.add(raw);
            }
        }
        if ( cssSelectors.size !== 0 ) {
            vAPI.domFilterer.addCSS(
                `${Array.from(cssSelectors).join('\n')}\n{${vAPI.hideStyle}}`,
                { mustInject: true }
            );
        }
        if ( proceduralSelectors.size !== 0 ) {
            vAPI.domFilterer.addProceduralSelectors(
                Array.from(proceduralSelectors)
            );
        }
    };

    return { preview, queryAll };
})();

/******************************************************************************/

const onOptimizeCandidates = function(details) {
    const { candidates } = details;
    const results = [];
    for ( const paths of candidates ) {
        let count = Number.MAX_SAFE_INTEGER;
        let selector = '';
        for ( let i = 0, n = paths.length; i < n; i++ ) {
            const s = paths.slice(n - i - 1).join('');
            const elems = document.querySelectorAll(s);
            if ( elems.length < count ) {
                selector = s;
                count = elems.length;
            }
        }
        results.push({ selector: `##${selector}`, count });
    }
    // Sort by most match count and shortest selector to least match count and
    // longest selector.
    results.sort((a, b) => {
        const r = b.count - a.count;
        if ( r !== 0 ) { return r; }
        return a.selector.length - b.selector.length;
    });

    pickerFramePort.postMessage({
        what: 'candidatesOptimized',
        candidates: results.map(a => a.selector),
        slot: details.slot,
    });
};

/******************************************************************************/

const showDialog = function(options) {
    pickerFramePort.postMessage({
        what: 'showDialog',
        url: self.location.href,
        netFilters: netFilterCandidates,
        cosmeticFilters: cosmeticFilterCandidates,
        filter: bestCandidateFilter,
        options,
    });
};

/******************************************************************************/

const elementFromPoint = (( ) => {
    let lastX, lastY;

    return (x, y) => {
        if ( x !== undefined ) {
            lastX = x; lastY = y;
        } else if ( lastX !== undefined ) {
            x = lastX; y = lastY;
        } else {
            return null;
        }
        if ( !pickerFrame ) { return null; }
        const magicAttr = `${pickerUniqueId}-clickblind`;
        pickerFrame.setAttribute(magicAttr, '');
        let elem = document.elementFromPoint(x, y);
        if (
            elem === null || /* to skip following tests */
            elem === document.body ||
            elem === document.documentElement || (
                pickerBootArgs.zap !== true &&
                noCosmeticFiltering &&
                resourceURLsFromElement(elem).length === 0
            )
        ) {
            elem = null;
        }
        // https://github.com/uBlockOrigin/uBlock-issues/issues/380
        pickerFrame.removeAttribute(magicAttr);
        return elem;
    };
})();

/******************************************************************************/

const highlightElementAtPoint = function(mx, my) {
    const elem = elementFromPoint(mx, my);
    highlightElements(elem ? [ elem ] : []);
};

/******************************************************************************/

const filterElementAtPoint = function(mx, my, broad) {
    if ( filtersFrom(mx, my) === 0 ) { return; }
    showDialog({ broad });
};

/******************************************************************************/

// https://www.reddit.com/r/uBlockOrigin/comments/bktxtb/scrolling_doesnt_work/emn901o
//   Override 'fixed' position property on body element if present.

// With touch-driven devices, first highlight the element and remove only
// when tapping again the highlighted area.

const zapElementAtPoint = function(mx, my, options) {
    if ( options.highlight ) {
        const elem = elementFromPoint(mx, my);
        if ( elem ) {
            highlightElements([ elem ]);
        }
        return;
    }

    let elemToRemove = targetElements.length !== 0 && targetElements[0] || null;
    if ( elemToRemove === null && mx !== undefined ) {
        elemToRemove = elementFromPoint(mx, my);
    }

    if ( elemToRemove instanceof Element === false ) { return; }

    const getStyleValue = (elem, prop) => {
        const style = window.getComputedStyle(elem);
        return style ? style[prop] : '';
    };

    // Heuristic to detect scroll-locking: remove such lock when detected.
    let maybeScrollLocked = elemToRemove.shadowRoot instanceof DocumentFragment;
    if ( maybeScrollLocked === false ) {
        let elem = elemToRemove;
        do {
            maybeScrollLocked =
                parseInt(getStyleValue(elem, 'zIndex'), 10) >= 1000 ||
                getStyleValue(elem, 'position') === 'fixed';
            elem = elem.parentElement;
        } while ( elem !== null && maybeScrollLocked === false );
    }
    if ( maybeScrollLocked ) {
        const doc = document;
        if ( getStyleValue(doc.body, 'overflowY') === 'hidden' ) {
            doc.body.style.setProperty('overflow', 'auto', 'important');
        }
        if ( getStyleValue(doc.body, 'position') === 'fixed' ) {
            doc.body.style.setProperty('position', 'initial', 'important');
        }
        if ( getStyleValue(doc.documentElement, 'position') === 'fixed' ) {
            doc.documentElement.style.setProperty('position', 'initial', 'important');
        }
        if ( getStyleValue(doc.documentElement, 'overflowY') === 'hidden' ) {
            doc.documentElement.style.setProperty('overflow', 'auto', 'important');
        }
    }
    elemToRemove.remove();
    highlightElementAtPoint(mx, my);
};

/******************************************************************************/

const onKeyPressed = function(ev) {
    // Delete
    if (
        (ev.key === 'Delete' || ev.key === 'Backspace') &&
        pickerBootArgs.zap
    ) {
        ev.stopPropagation();
        ev.preventDefault();
        zapElementAtPoint();
        return;
    }
    // Esc
    if ( ev.key === 'Escape' || ev.which === 27 ) {
        ev.stopPropagation();
        ev.preventDefault();
        filterToDOMInterface.preview(false);
        quitPicker();
        return;
    }
};

/******************************************************************************/

// https://github.com/chrisaljoudi/uBlock/issues/190
//   May need to dynamically adjust the height of the overlay + new position
//   of highlighted elements.

const onViewportChanged = function() {
    highlightElements(targetElements, true);
};

/******************************************************************************/

// Auto-select a specific target, if any, and if possible

const startPicker = function() {
    pickerFrame.focus();

    self.addEventListener('scroll', onViewportChanged, { passive: true });
    self.addEventListener('resize', onViewportChanged, { passive: true });
    self.addEventListener('keydown', onKeyPressed, true);

    // Try using mouse position
    if (
        pickerBootArgs.mouse &&
        vAPI.mouseClick instanceof Object &&
        typeof vAPI.mouseClick.x === 'number' &&
        vAPI.mouseClick.x > 0
    ) {
        if ( filtersFrom(vAPI.mouseClick.x, vAPI.mouseClick.y) !== 0 ) {
            return showDialog();
        }
    }

    // No mouse position available, use suggested target
    const target = pickerBootArgs.target || '';
    const pos = target.indexOf('\t');
    if ( pos === -1 ) { return; }

    const srcAttrMap = {
        'a': 'href',
        'audio': 'src',
        'embed': 'src',
        'iframe': 'src',
        'img': 'src',
        'video': 'src',
    };
    const tagName = target.slice(0, pos);
    const url = target.slice(pos + 1);
    const attr = srcAttrMap[tagName];
    if ( attr === undefined ) { return; }
    const elems = document.getElementsByTagName(tagName);
    for ( const elem of elems  ) {
        if ( elem === pickerFrame ) { continue; }
        const srcs = resourceURLsFromElement(elem);
        if (
            (srcs.length !== 0 && srcs.includes(url) === false) ||
            (srcs.length === 0 && url !== 'about:blank')
        ) {
            continue;
        }
        filtersFrom(elem);
        if (
            netFilterCandidates.length !== 0 ||
            cosmeticFilterCandidates.length !== 0
        ) {
            if ( pickerBootArgs.mouse !== true ) {
                elem.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                    inline: 'center'
                });
            }
            showDialog({ broad: true });
        }
        return;
    }

    // A target was specified, but it wasn't found: abort.
    quitPicker();
};

/******************************************************************************/

// Let's have the element picker code flushed from memory when no longer
// in use: to ensure this, release all local references.

const quitPicker = function() {
    self.removeEventListener('scroll', onViewportChanged, { passive: true });
    self.removeEventListener('resize', onViewportChanged, { passive: true });
    self.removeEventListener('keydown', onKeyPressed, true);
    vAPI.shutdown.remove(quitPicker);
    if ( pickerFramePort ) {
        pickerFramePort.close();
        pickerFramePort = null;
    }
    if ( pickerFrame ) {
        pickerFrame.remove();
        pickerFrame = null;
    }
    vAPI.userStylesheet.remove(pickerCSS);
    vAPI.userStylesheet.apply();
    vAPI.pickerFrame = false;
    self.focus();
};

vAPI.shutdown.add(quitPicker);

/******************************************************************************/

const onDialogMessage = function(msg) {
    switch ( msg.what ) {
    case 'start':
        startPicker();
        if ( pickerFramePort === null ) { break; }
        if ( targetElements.length === 0 ) {
            highlightElements([], true);
        }
        break;
    case 'optimizeCandidates':
        onOptimizeCandidates(msg);
        break;
    case 'dialogCreate':
        filterToDOMInterface.queryAll(msg);
        filterToDOMInterface.preview(true, true);
        quitPicker();
        break;
    case 'dialogSetFilter': {
        const resultset = filterToDOMInterface.queryAll(msg) || [];
        highlightElements(resultset.map(a => a.elem), true);
        if ( msg.filter === '!' ) { break; }
        pickerFramePort.postMessage({
            what: 'resultsetDetails',
            count: resultset.length,
            opt: resultset.length !== 0 ? resultset[0].opt : undefined,
        });
        break;
    }
    case 'quitPicker':
        filterToDOMInterface.preview(false);
        quitPicker();
        break;
    case 'highlightElementAtPoint':
        highlightElementAtPoint(msg.mx, msg.my);
        break;
    case 'unhighlight':
        highlightElements([]);
        break;
    case 'filterElementAtPoint':
        filterElementAtPoint(msg.mx, msg.my, msg.broad);
        break;
    case 'zapElementAtPoint':
        zapElementAtPoint(msg.mx, msg.my, msg.options);
        if ( msg.options.highlight !== true && msg.options.stay !== true ) {
            quitPicker();
        }
        break;
    case 'togglePreview':
        filterToDOMInterface.preview(msg.state);
        if ( msg.state === false ) {
            highlightElements(targetElements, true);
        }
        break;
    default:
        break;
    }
};

/******************************************************************************/

// epicker-ui.html will be injected in the page through an iframe, and
// is a sandboxed so as to prevent the page from interfering with its
// content and behavior.
//
// The purpose of epicker.js is to:
// - Install the element picker UI, and wait for the component to establish
//   a direct communication channel.
// - Lookup candidate filters from elements at a specific position.
// - Highlight element(s) at a specific position or according to whether
//   they match candidate filters;
// - Preview the result of applying a candidate filter;
//
// When the element picker is installed on a page, the only change the page
// sees is an iframe with a random attribute. The page can't see the content
// of the iframe, and cannot interfere with its style properties. However the
// page can remove the iframe.

// The DOM filterer will not be present when cosmetic filtering is disabled.
const noCosmeticFiltering =
    vAPI.domFilterer instanceof Object === false ||
    vAPI.noSpecificCosmeticFiltering === true;

// https://github.com/gorhill/uBlock/issues/1529
//   In addition to inline styles, harden the element picker styles by using
//   dedicated CSS rules.
const pickerCSSStyle = [
    'background: transparent',
    'border: 0',
    'border-radius: 0',
    'box-shadow: none',
    'color-scheme: light dark',
    'display: block',
    'filter: none',
    'height: 100vh',
    '    height: 100svh',
    'left: 0',
    'margin: 0',
    'max-height: none',
    'max-width: none',
    'min-height: unset',
    'min-width: unset',
    'opacity: 1',
    'outline: 0',
    'padding: 0',
    'pointer-events: auto',
    'position: fixed',
    'top: 0',
    'transform: none',
    'visibility: hidden',
    'width: 100%',
    'z-index: 2147483647',
    ''
].join(' !important;\n');


const pickerCSS = `
:root > [${pickerUniqueId}] {
    ${pickerCSSStyle}
}
:root > [${pickerUniqueId}-loaded] {
    visibility: visible !important;
}
:root [${pickerUniqueId}-clickblind] {
    pointer-events: none !important;
}
`;

vAPI.userStylesheet.add(pickerCSS);
vAPI.userStylesheet.apply();

let pickerBootArgs;
let pickerFramePort = null;

const bootstrap = async ( ) => {
    pickerBootArgs = await vAPI.messaging.send('elementPicker', {
        what: 'elementPickerArguments',
    });
    if ( typeof pickerBootArgs !== 'object' ) { return; }
    if ( pickerBootArgs === null ) { return; }
    // Restore net filter union data if origin is the same.
    const eprom = pickerBootArgs.eprom || null;
    if ( eprom !== null && eprom.lastNetFilterSession === lastNetFilterSession ) {
        lastNetFilterHostname = eprom.lastNetFilterHostname || '';
        lastNetFilterUnion = eprom.lastNetFilterUnion || '';
    }
    const url = new URL(pickerBootArgs.pickerURL);
    if ( pickerBootArgs.zap ) {
        url.searchParams.set('zap', '1');
    }
    return new Promise(resolve => {
        const iframe = document.createElement('iframe');
        iframe.setAttribute(pickerUniqueId, '');
        document.documentElement.append(iframe);
        iframe.addEventListener('load', ( ) => {
            iframe.setAttribute(`${pickerUniqueId}-loaded`, '');
            const channel = new MessageChannel();
            pickerFramePort = channel.port1;
            pickerFramePort.onmessage = ev => {
                onDialogMessage(ev.data || {});
            };
            pickerFramePort.onmessageerror = ( ) => {
                quitPicker();
            };
            iframe.contentWindow.postMessage(
                { what: 'epickerStart' },
                url.href,
                [ channel.port2 ]
            );
            resolve(iframe);
        }, { once: true });
        iframe.contentWindow.location = url.href;
    });
};

let pickerFrame = await bootstrap();
if ( Boolean(pickerFrame) === false ) {
    quitPicker();
}

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
