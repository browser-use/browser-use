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

import * as fc from  './filtering-context.js';
import * as sfp from './static-filtering-parser.js';
import {
    sessionFirewall,
    sessionSwitches,
    sessionURLFiltering,
} from './filtering-engines.js';
import htmlFilteringEngine from './html-filtering.js';
import httpheaderFilteringEngine from './httpheader-filtering.js';
import { isNetworkURI } from './uri-utils.js';
import logger from './logger.js';
import scriptletFilteringEngine from './scriptlet-filtering.js';
import staticNetFilteringEngine from './static-net-filtering.js';
import textEncode from './text-encode.js';
import µb from './background.js';

/******************************************************************************/

// For platform-specific behavior.
const isGecko = vAPI.webextFlavor.isGecko;

/******************************************************************************/

const patchLocalRedirectURL = url => url.charCodeAt(0) === 0x2F /* '/' */
    ? vAPI.getURL(url)
    : url;

/******************************************************************************/

// Intercept and filter web requests.

function onBeforeRequest(details) {
    const fctxt = µb.filteringContext.fromWebrequestDetails(details);

    // Special handling for root document.
    // https://github.com/chrisaljoudi/uBlock/issues/1001
    // This must be executed regardless of whether the request is
    // behind-the-scene
    if ( fctxt.itype === fctxt.MAIN_FRAME ) {
        return onBeforeRootFrameRequest(fctxt);
    }

    // Special treatment: behind-the-scene requests
    const tabId = details.tabId;
    if ( tabId < 0 ) {
        return onBeforeBehindTheSceneRequest(fctxt);
    }

    // Lookup the page store associated with this tab id.
    let pageStore = µb.pageStoreFromTabId(tabId);
    if ( pageStore === null ) {
        const tabContext = µb.tabContextManager.mustLookup(tabId);
        if ( tabContext.tabId < 0 ) {
            return onBeforeBehindTheSceneRequest(fctxt);
        }
        vAPI.tabs.onNavigation({ tabId, frameId: 0, url: tabContext.rawURL });
        pageStore = µb.pageStoreFromTabId(tabId);
    }

    const result = pageStore.filterRequest(fctxt);

    pageStore.journalAddRequest(fctxt, result);

    if ( logger.enabled ) {
        fctxt.setRealm('network').toLogger();
    }

    // Redirected

    if ( fctxt.redirectURL !== undefined ) {
        return { redirectUrl: patchLocalRedirectURL(fctxt.redirectURL) };
    }

    // Not redirected

    // Blocked
    if ( result === 1 ) {
        return { cancel: true };
    }

    // Not blocked
    if (
        fctxt.itype === fctxt.SUB_FRAME &&
        details.parentFrameId !== -1 &&
        details.aliasURL === undefined
    ) {
        pageStore.setFrameURL(details);
    }

    if ( result === 2 ) {
        return { cancel: false };
    }
};

/******************************************************************************/

function onBeforeRootFrameRequest(fctxt) {
    const requestURL = fctxt.url;

    // Special handling for root document.
    // https://github.com/chrisaljoudi/uBlock/issues/1001
    //   This must be executed regardless of whether the request is
    //   behind-the-scene
    const requestHostname = fctxt.getHostname();
    let result = 0;
    let logData;

    // If the site is whitelisted, disregard strict blocking
    const trusted = µb.getNetFilteringSwitch(requestURL) === false;
    if ( trusted ) {
        result = 2;
        if ( logger.enabled ) {
            logData = { engine: 'u', result: 2, raw: 'whitelisted' };
        }
    }

    // Permanently unrestricted?
    if (
        result === 0 &&
        sessionSwitches.evaluateZ('no-strict-blocking', requestHostname)
    ) {
        result = 2;
        if ( logger.enabled ) {
            logData = {
                engine: 'u',
                result: 2,
                raw: `no-strict-blocking: ${sessionSwitches.z} true`
            };
        }
    }

    // Temporarily whitelisted?
    if ( result === 0 && strictBlockBypasser.isBypassed(requestHostname) ) {
        result = 2;
        if ( logger.enabled ) {
            logData = {
                engine: 'u',
                result: 2,
                raw: 'no-strict-blocking: true (temporary)'
            };
        }
    }

    // Static filtering
    if ( result === 0 ) {
        ({ result, logData } = shouldStrictBlock(fctxt, logger.enabled));
    }

    const pageStore = µb.bindTabToPageStore(fctxt.tabId, 'beforeRequest');
    if ( pageStore !== null ) {
        pageStore.journalAddRootFrame('uncommitted', requestURL);
        pageStore.journalAddRequest(fctxt, result);
    }

    if ( logger.enabled ) {
        fctxt.setRealm('network').setFilter(logData);
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/760
    //   Redirect non-blocked request?
    if ( trusted === false && pageStore !== null ) {
        if ( result !== 1 ) {
            pageStore.redirectNonBlockedRequest(fctxt);
        } else {
            pageStore.skipMainDocument(fctxt, true);
        }
    }

    if ( logger.enabled ) {
        fctxt.toLogger();
    }

    // Redirected

    if ( fctxt.redirectURL !== undefined ) {
        return { redirectUrl: patchLocalRedirectURL(fctxt.redirectURL) };
    }

    // Not blocked

    if ( result !== 1 ) { return; }

    // No log data means no strict blocking (because we need to report why
    // the blocking occurs
    if ( logData === undefined  ) { return; }

    // Blocked

    let reason = logData.reason;

    // Find out the URL navigated to should the document not be strict-blocked
    pageStore.skipMainDocument(fctxt, false);

    if ( reason === undefined && Array.isArray(fctxt.filter) ) {
        const filter = fctxt.filter.find(a => a.reason !== undefined);
        reason = filter?.reason;
    }

    const query = {
        url: requestURL,
        dn: fctxt.getDomain() || requestHostname,
        fs: logData.raw,
        hn: requestHostname,
        to: fctxt.redirectURL || '',
    };
    if ( reason ) {
        query.reason = reason;
    }

    vAPI.tabs.replace(
        fctxt.tabId,
        `${vAPI.getURL('document-blocked.html?details=')}${encodeURIComponent(JSON.stringify(query))}`
    );

    return { cancel: true };
}

/******************************************************************************/

// Strict blocking through static filtering
//
// https://github.com/chrisaljoudi/uBlock/issues/1128
//   Do not block if the match begins after the hostname,
//   except when the filter is specifically of type `other`.
// https://github.com/gorhill/uBlock/issues/490
//   Removing this for the time being, will need a new, dedicated type.
// https://github.com/uBlockOrigin/uBlock-issues/issues/1501
//   Support explicit exception filters.
//
// Let result of match for specific `document` type be `rs`
// Let result of match for no specific type be `rg` *after* going through
//   confirmation necessary for implicit matches
// Let `important` be `i`
// Let final result be logical combination of `rs` and `rg` as follow:
//
//                  |                rs                 |
//                  +--------+--------+--------+--------|
//                  |   0    |   1    |   1i   |   2    |
// --------+--------+--------+--------+--------+--------|
//         |   0    |   rg   |   rs   |   rs   |   rs   |
//    rg   |   1    |   rg   |   rs   |   rs   |   rs   |
//         |   1i   |   rg   |   rg   |   rs   |   rg   |
//         |   2    |   rg   |   rg   |   rs   |   rs   |
// --------+--------+--------+--------+--------+--------+

function shouldStrictBlock(fctxt, loggerEnabled) {
    const snfe = staticNetFilteringEngine;

    // Explicit filtering: `document` option
    const rs = snfe.matchRequest(fctxt, 0b0011);
    const is = rs === 1 && snfe.isBlockImportant();
    let lds;
    if ( rs !== 0 || loggerEnabled ) {
        lds = snfe.toLogData();
    }

    //                  |                rs                 |
    //                  +--------+--------+--------+--------|
    //                  |   0    |   1    |   1i   |   2    |
    // --------+--------+--------+--------+--------+--------|
    //         |   0    |   rg   |   rs   |   x    |   rs   |
    //    rg   |   1    |   rg   |   rs   |   x    |   rs   |
    //         |   1i   |   rg   |   rg   |   x    |   rg   |
    //         |   2    |   rg   |   rg   |   x    |   rs   |
    // --------+--------+--------+--------+--------+--------+
    if ( rs === 1 && is ) {
        return { result: rs, logData: lds };
    }

    // Implicit filtering: no `document` option
    fctxt.type = 'no_type';
    let rg = snfe.matchRequest(fctxt, 0b0011);
    fctxt.type = 'main_frame';
    const ig = rg === 1 && snfe.isBlockImportant();
    let ldg;
    if ( rg !== 0 || loggerEnabled ) {
        ldg = snfe.toLogData();
        if ( rg === 1 && validateStrictBlock(fctxt, ldg) === false ) {
            rg = 0; ldg = undefined;
        }
    }

    //                  |                rs                 |
    //                  +--------+--------+--------+--------|
    //                  |   0    |   1    |   1i   |   2    |
    // --------+--------+--------+--------+--------+--------|
    //         |   0    |   x    |   rs   |   -    |   rs   |
    //    rg   |   1    |   x    |   rs   |   -    |   rs   |
    //         |   1i   |   x    |   x    |   -    |   x    |
    //         |   2    |   x    |   x    |   -    |   rs   |
    // --------+--------+--------+--------+--------+--------+
    if ( rs === 0 || rg === 1 && ig || rg === 2 && rs !== 2 ) {
        return { result: rg, logData: ldg };
    }

    //                  |                rs                 |
    //                  +--------+--------+--------+--------|
    //                  |   0    |   1    |   1i   |   2    |
    // --------+--------+--------+--------+--------+--------|
    //         |   0    |   -    |   x    |   -    |   x    |
    //    rg   |   1    |   -    |   x    |   -    |   x    |
    //         |   1i   |   -    |   -    |   -    |   -    |
    //         |   2    |   -    |   -    |   -    |   x    |
    // --------+--------+--------+--------+--------+--------+
    return { result: rs, logData: lds };
}

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/3208
//   Mind case insensitivity.
// https://github.com/uBlockOrigin/uBlock-issues/issues/1147
//   Do not strict-block if the filter pattern does not contain at least one
//   token character.

function validateStrictBlock(fctxt, logData) {
    if ( typeof logData.regex !== 'string' ) { return false; }
    if ( typeof logData.raw === 'string' && /\w/.test(logData.raw) === false ) {
        return false;
    }
    const url = fctxt.url;
    const re = new RegExp(logData.regex, 'i');
    const match = re.exec(url.toLowerCase());
    if ( match === null ) { return false; }

    // https://github.com/chrisaljoudi/uBlock/issues/1128
    // https://github.com/chrisaljoudi/uBlock/issues/1212
    //   Verify that the end of the match is anchored to the end of the
    //   hostname.
    // https://github.com/uBlockOrigin/uAssets/issues/7619#issuecomment-653010310
    //   Also match FQDN.
    const hostname = fctxt.getHostname();
    const hnpos = url.indexOf(hostname);
    const hnlen = hostname.length;
    const end = match.index + match[0].length - hnpos - hnlen;
    return end === 0 || end === 1 ||
           end === 2 && url.charCodeAt(hnpos + hnlen) === 0x2E /* '.' */;
}

/******************************************************************************/

// Intercept and filter behind-the-scene requests.

function onBeforeBehindTheSceneRequest(fctxt) {
    const pageStore = µb.pageStoreFromTabId(fctxt.tabId);
    if ( pageStore === null ) { return; }

    // https://github.com/gorhill/uBlock/issues/3150
    //   Ability to globally block CSP reports MUST also apply to
    //   behind-the-scene network requests.

    let result = 0;

    // https://github.com/uBlockOrigin/uBlock-issues/issues/339
    //   Need to also test against `-scheme` since tabOrigin is normalized.
    //   Not especially elegant but for now this accomplishes the purpose of
    //   not dealing with network requests fired from a synthetic scope,
    //   that is unless advanced user mode is enabled.

    if (
        fctxt.tabOrigin.endsWith('-scheme') === false &&
        isNetworkURI(fctxt.tabOrigin) ||
        µb.userSettings.advancedUserEnabled ||
        fctxt.itype === fctxt.CSP_REPORT
    ) {
        result = pageStore.filterRequest(fctxt);

        // The "any-tab" scope is not whitelist-able, and in such case we must
        // use the origin URL as the scope. Most such requests aren't going to
        // be blocked, so we test for whitelisting and modify the result only
        // when the request is being blocked.
        //
        // https://github.com/uBlockOrigin/uBlock-issues/issues/1478
        //   Also remove potential redirection when request is to be
        //   whitelisted.
        if (
            result === 1 &&
            µb.getNetFilteringSwitch(fctxt.tabOrigin) === false
        ) {
            result = 2;
            fctxt.redirectURL = undefined;
            fctxt.filter = { engine: 'u', result: 2, raw: 'whitelisted' };
        }
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1204
    onBeforeBehindTheSceneRequest.journalAddRequest(fctxt, result);

    if ( logger.enabled ) {
        fctxt.setRealm('network').toLogger();
    }

    // Redirected

    if ( fctxt.redirectURL !== undefined ) {
        return { redirectUrl: patchLocalRedirectURL(fctxt.redirectURL) };
    }

    // Blocked?

    if ( result === 1 ) {
        return { cancel: true };
    }
}

// https://github.com/uBlockOrigin/uBlock-issues/issues/1204
//   Report the tabless network requests to all page stores matching the
//   document origin. This is an approximation, there is unfortunately no
//   way to know for sure which exact page triggered a tabless network
//   request.

{
    const pageStores = new Set();
    let hostname = '';
    let pageStoresToken = 0;

    const reset = function() {
        hostname = '';
        pageStores.clear();
        pageStoresToken = 0;
    };

    const gc = ( ) => {
        if ( pageStoresToken !== µb.pageStoresToken ) { return reset(); }
        gcTimer.on(30011);
    };

    const gcTimer = vAPI.defer.create(gc);

    onBeforeBehindTheSceneRequest.journalAddRequest = (fctxt, result) => {
        const docHostname = fctxt.getDocHostname();
        if (
            docHostname !== hostname ||
            pageStoresToken !== µb.pageStoresToken
        ) {
            hostname = docHostname;
            pageStores.clear();
            for ( const pageStore of µb.pageStores.values() ) {
                if ( pageStore.tabHostname !== docHostname ) { continue; }
                pageStores.add(pageStore);
            }
            pageStoresToken = µb.pageStoresToken;
            gcTimer.offon(30011);
        }
        for ( const pageStore of pageStores ) {
            pageStore.journalAddRequest(fctxt, result);
        }
    };
}

/******************************************************************************/

// To handle:
// - Media elements larger than n kB
// - Scriptlet injection (requires ability to modify response body)
// - HTML filtering (requires ability to modify response body)
// - CSP injection

function onHeadersReceived(details) {

    const fctxt = µb.filteringContext.fromWebrequestDetails(details);
    const isRootDoc = fctxt.itype === fctxt.MAIN_FRAME;

    let pageStore = µb.pageStoreFromTabId(fctxt.tabId);
    if ( pageStore === null ) {
        if ( isRootDoc === false ) { return; }
        pageStore = µb.bindTabToPageStore(fctxt.tabId, 'beforeRequest');
    }
    if ( pageStore.getNetFilteringSwitch(fctxt) === false ) { return; }

    // To enforce strict-blocking with ipaddress option
    if ( isRootDoc && fctxt.ipaddress ) {
        const r = onBeforeRootFrameRequest(fctxt);
        if ( r ) { return ( r ); }
    }

    if ( (fctxt.itype & foilLargeMediaElement.TYPE_BITS) !== 0 ) {
        const result = foilLargeMediaElement(details, fctxt, pageStore);
        if ( result !== undefined ) { return result; }
    }

    // Keep in mind response headers will be modified in-place if needed, so
    // `details.responseHeaders` will always point to the modified response
    // headers.
    const { responseHeaders } = details;
    if ( Array.isArray(responseHeaders) === false ) { return; }

    if ( isRootDoc === false ) {
        const result = pageStore.filterOnHeaders(fctxt, responseHeaders);
        if ( result !== 0 ) {
            if ( logger.enabled ) {
                fctxt.setRealm('network').toLogger();
            }
            if ( result === 1 ) {
                pageStore.journalAddRequest(fctxt, 1);
                return { cancel: true };
            }
        }
    }

    const mime = mimeFromHeaders(responseHeaders);

    // https://github.com/gorhill/uBlock/issues/2813
    //   Disable the blocking of large media elements if the document is itself
    //   a media element: the resource was not prevented from loading so no
    //   point to further block large media elements for the current document.
    if ( isRootDoc ) {
        if ( reMediaContentTypes.test(mime) ) {
            pageStore.allowLargeMediaElementsUntil = 0;
            // Fall-through: this could be an SVG document, which supports
            // script tags.
        }
    }

    if ( bodyFilterer.canFilter(fctxt, details) ) {
        const jobs = [];
        // `replace=` filter option
        const replaceDirectives =
            staticNetFilteringEngine.matchAndFetchModifiers(fctxt, 'replace');
        if ( replaceDirectives ) {
            jobs.push({
                fn: textResponseFilterer,
                args: [ replaceDirectives ],
            });
        }
        // html filtering
        if ( mime === 'text/html' || mime === 'application/xhtml+xml' ) {
            const selectors = htmlFilteringEngine.retrieve(fctxt);
            if ( selectors ) {
                jobs.push({
                    fn: htmlResponseFilterer,
                    args: [ selectors ],
                });
            }
        }
        if ( jobs.length !== 0 ) {
            bodyFilterer.doFilter(details.requestId, fctxt, jobs);
        }
    }

    let modifiedHeaders = false;
    if ( httpheaderFilteringEngine.apply(fctxt, responseHeaders) === true ) {
        modifiedHeaders = true;
    }

    // https://github.com/uBlockOrigin/uBlock-issues/issues/229#issuecomment-2220354261
    // Inject CSP/PP in document resource only
    if ( fctxt.isDocument() ) {
        if ( injectCSP(fctxt, pageStore, responseHeaders) === true ) {
            modifiedHeaders = true;
        }
        if ( injectPP(fctxt, pageStore, responseHeaders) === true ) {
            modifiedHeaders = true;
        }
    }

    // https://bugzilla.mozilla.org/show_bug.cgi?id=1376932
    //   Prevent document from being cached by the browser if we modified it,
    //   either through HTML filtering and/or modified response headers.
    // https://github.com/uBlockOrigin/uBlock-issues/issues/229
    //   Use `no-cache` instead of `no-cache, no-store, must-revalidate`, this
    //   allows Firefox's offline mode to work as expected.
    if ( modifiedHeaders && isGecko ) {
        const cacheControl = µb.hiddenSettings.cacheControlForFirefox1376932;
        if ( cacheControl !== 'unset' ) {
            let i = headerIndexFromName('cache-control', responseHeaders);
            if ( i !== -1 ) {
                responseHeaders[i].value = cacheControl;
            } else {
                responseHeaders.push({ name: 'Cache-Control', value: cacheControl });
            }
            modifiedHeaders = true;
        }
    }

    if ( modifiedHeaders ) {
        return { responseHeaders };
    }
}

const reMediaContentTypes = /^(?:audio|image|video)\/|(?:\/ogg)$/;

/******************************************************************************/

const mimeFromHeaders = headers => {
    if ( Array.isArray(headers) === false ) { return ''; }
    return mimeFromContentType(headerValueFromName('content-type', headers));
};

const mimeFromContentType = contentType => {
    const match = reContentTypeMime.exec(contentType);
    if ( match === null ) { return ''; }
    return match[0].toLowerCase();
};

const reContentTypeMime = /^[^;]+/i;

/******************************************************************************/

function textResponseFilterer(session, directives) {
    const applied = [];
    for ( const directive of directives ) {
        if ( directive.refs instanceof Object === false ) { continue; }
        if ( directive.result !== 1 ) {
            applied.push(directive);
            continue;
        }
        const { refs } = directive;
        if ( refs.$cache !== null ) {
            const { jsonp } = refs.$cache;
            if ( jsonp && jsonp.apply === undefined ) {
                refs.$cache = null;
            }
        }
        if ( refs.$cache === null ) {
            refs.$cache = sfp.parseReplaceValue(refs.value);
        }
        const cache = refs.$cache;
        if ( cache === undefined ) { continue; }
        switch ( cache.type ) {
        case 'json': {
            const json = session.getString();
            let obj;
            try { obj = JSON.parse(json); } catch { break; }
            const objAfter = cache.jsonp.apply(obj);
            if ( objAfter === undefined ) { break; }
            session.setString(cache.jsonp.toJSON(objAfter));
            applied.push(directive);
            break;
        }
        case 'jsonl': {
            const linesBefore = session.getString().split(/\n+/);
            const linesAfter = [];
            for ( const lineBefore of linesBefore ) {
                let obj;
                try { obj = JSON.parse(lineBefore); } catch { }
                if ( typeof obj !== 'object' || obj === null ) {
                    linesAfter.push(lineBefore);
                    continue;
                }
                const objAfter = cache.jsonp.apply(obj);
                if ( objAfter === undefined ) {
                    linesAfter.push(lineBefore);
                    continue;
                }
                linesAfter.push(cache.jsonp.toJSON(objAfter));
            }
            session.setString(linesAfter.join('\n'));
            break;
        }
        case 'text': {
            cache.re.lastIndex = 0;
            if ( cache.re.test(session.getString()) !== true ) { break; }
            cache.re.lastIndex = 0;
            session.setString(session.getString().replace(
                cache.re,
                cache.replacement
            ));
            applied.push(directive);
            break;
        }
        default:
            break;
        }
    }
    if ( applied.length === 0 ) { return; }
    if ( logger.enabled !== true ) { return; }
    session.setRealm('network')
         .pushFilters(applied.map(a => a.logData()))
         .toLogger();
}

/******************************************************************************/

function htmlResponseFilterer(session, selectors) {
    if ( htmlResponseFilterer.domParser === null ) {
        htmlResponseFilterer.domParser = new DOMParser();
        htmlResponseFilterer.xmlSerializer = new XMLSerializer();
    }

    const doc = htmlResponseFilterer.domParser.parseFromString(
        session.getString(),
        session.mime
    );

    if ( selectors === undefined ) { return; }
    if ( htmlFilteringEngine.apply(doc, session, selectors) !== true ) { return; }

    // https://stackoverflow.com/questions/6088972/get-doctype-of-an-html-as-string-with-javascript/10162353#10162353
    const doctypeStr = [
        doc.doctype instanceof Object ?
            htmlResponseFilterer.xmlSerializer.serializeToString(doc.doctype) + '\n' :
            '',
        doc.documentElement.outerHTML,
    ].join('\n');
    session.setString(doctypeStr);
}
htmlResponseFilterer.domParser = null;
htmlResponseFilterer.xmlSerializer = null;


/*******************************************************************************

    The response body filterer is responsible for:

    - Realize static network filter option `replace=`
    - HTML filtering

**/

const bodyFilterer = (( ) => {
    const sessions = new Map();
    const reContentTypeCharset = /charset=['"]?([^'" ]+)/i;
    const otherValidMimes = new Set([
        'application/dash+xml',
        'application/javascript',
        'application/json',
        'application/mpegurl',
        'application/vnd.api+json',
        'application/vnd.apple.mpegurl',
        'application/vnd.apple.mpegurl.audio',
        'application/x-javascript',
        'application/x-mpegurl',
        'application/xhtml+xml',
        'application/xml',
        'audio/mpegurl',
        'audio/x-mpegurl',
    ]);
    const BINARY_TYPES = fc.FONT | fc.IMAGE | fc.MEDIA | fc.WEBSOCKET;
    const MAX_RESPONSE_BUFFER_LENGTH = 10 * 1024 * 1024;

    let textDecoder, textEncoder;
    let mime = '';
    let charset = '';

    const contentTypeFromDetails = details => {
        switch ( details.type ) {
        case 'script':
            return 'text/javascript; charset=utf-8';
        case 'stylesheet':
            return 'text/css';
        default:
            break;
        }
        return '';
    };

    const charsetFromContentType = contentType => {
        const match = reContentTypeCharset.exec(contentType);
        if ( match === null ) { return; }
        return match[1].toLowerCase();
    };

    const charsetFromMime = mime => {
        switch ( mime ) {
        case 'application/xml':
        case 'application/xhtml+xml':
        case 'text/html':
        case 'text/css':
            return;
        default:
            break;
        }
        return 'utf-8';
    };

    const charsetFromStream = bytes => {
        if ( bytes.length < 3 ) { return; }
        if ( bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF ) {
            return 'utf-8';
        }
        let i = -1;
        while ( i < 65536 ) {
            i += 1;
            /* c */ if ( bytes[i+0] !== 0x63 ) { continue; }
            /* h */ if ( bytes[i+1] !== 0x68 ) { continue; }
            /* a */ if ( bytes[i+2] !== 0x61 ) { continue; }
            /* r */ if ( bytes[i+3] !== 0x72 ) { continue; }
            /* s */ if ( bytes[i+4] !== 0x73 ) { continue; }
            /* e */ if ( bytes[i+5] !== 0x65 ) { continue; }
            /* t */ if ( bytes[i+6] !== 0x74 ) { continue; }
            break;
        }
        if ( (i + 40) >= 65536 ) { return; }
        i += 8;
        // find first alpha character
        let j = -1;
        while ( j < 8 ) {
            j += 1;
            const c = bytes[i+j];
            if ( c >= 0x41 && c <= 0x5A ) { break; }
            if ( c >= 0x61 && c <= 0x7A ) { break; }
        }
        if ( j === 8 ) { return; }
        i += j;
        // Collect characters until first non charset-name-character
        const chars = [];
        j = 0;
        while ( j < 24 ) {
            const c = bytes[i+j];
            if ( c < 0x2D ) { break; }
            if ( c > 0x2D && c < 0x30 ) { break; }
            if ( c > 0x39 && c < 0x41 ) { break; }
            if ( c > 0x5A && c < 0x61 ) { break; }
            if ( c > 0x7A ) { break; }
            chars.push(c);
            j += 1;
        }
        if ( j === 20 ) { return; }
        return String.fromCharCode(...chars).toLowerCase();
    };

    const streamClose = (session, buffer) => {
        if ( buffer !== undefined ) {
            session.stream.write(buffer);
        } else if ( session.buffer !== undefined ) {
            session.stream.write(session.buffer);
        }
        session.stream.close();
    };

    const onStreamData = function(ev) {
        const session = sessions.get(this);
        if ( session === undefined ) {
            this.write(ev.data);
            this.disconnect();
            return;
        }
        if ( this.status !== 'transferringdata' ) {
            if ( this.status !== 'finishedtransferringdata' ) {
                sessions.delete(this);
                this.disconnect();
                return;
            }
        }
        if ( session.buffer === null ) {
            session.buffer = new Uint8Array(ev.data);
            return;
        }
        const buffer = new Uint8Array(
            session.buffer.byteLength + ev.data.byteLength
        );
        buffer.set(session.buffer);
        buffer.set(new Uint8Array(ev.data), session.buffer.byteLength);
        session.buffer = buffer;
        if ( session.buffer.length >= MAX_RESPONSE_BUFFER_LENGTH ) {
            sessions.delete(this);
            this.write(session.buffer);
            this.disconnect();
        }
    };

    const onStreamStop = function() {
        const session = sessions.get(this);
        sessions.delete(this);
        if ( session === undefined || session.buffer === null ) {
            this.close();
            return;
        }
        if ( this.status !== 'finishedtransferringdata' ) { return; }

        // If encoding is still unknown, try to extract from stream data.
        // Just assume utf-8 if ultimately no encoding can be looked up.
        if ( session.charset === undefined ) {
            const charsetFound = charsetFromStream(session.buffer);
            if ( charsetFound !== undefined ) {
                const charsetUsed = textEncode.normalizeCharset(charsetFound);
                if ( charsetUsed === undefined ) { return streamClose(session); }
                session.charset = charsetUsed;
            } else {
                session.charset = 'utf-8';
            }
        }

        while ( session.jobs.length !== 0 ) {
            const job = session.jobs.shift();
            job.fn(session, ...job.args);
        }
        if ( session.modified !== true ) { return streamClose(session); }

        if ( textEncoder === undefined ) {
            textEncoder = new TextEncoder();
        }
        let encodedStream = textEncoder.encode(session.str);

        if ( session.charset !== 'utf-8' ) {
            encodedStream = textEncode.encode(session.charset, encodedStream);
        }

        streamClose(session, encodedStream);
    };

    const onStreamError = function() {
        sessions.delete(this);
    };

    return class Session extends µb.FilteringContext {
        constructor(fctxt, mime, charset, jobs) {
            super(fctxt);
            this.stream = null;
            this.buffer = null;
            this.mime = mime;
            this.charset = charset;
            this.str = null;
            this.modified = false;
            this.jobs = jobs;
        }
        getString() {
            if ( this.str !== null ) { return this.str; }
            if ( textDecoder !== undefined ) {
                if ( textDecoder.encoding !== this.charset ) {
                    textDecoder = undefined;
                }
            }
            if ( textDecoder === undefined ) {
                textDecoder = new TextDecoder(this.charset);
            }
            this.str = textDecoder.decode(this.buffer);
            return this.str;
        }
        setString(s) {
            this.str = s;
            this.modified = true;
        }
        static doFilter(requestId, fctxt, jobs) {
            if ( jobs.length === 0 ) { return; }
            const session = new Session(fctxt, mime, charset, jobs);
            session.stream = browser.webRequest.filterResponseData(requestId);
            session.stream.ondata = onStreamData;
            session.stream.onstop = onStreamStop;
            session.stream.onerror = onStreamError;
            sessions.set(session.stream, session);
        }
        static canFilter(fctxt, details) {
            if ( µb.canFilterResponseData !== true ) { return; }

            if ( (fctxt.itype & BINARY_TYPES) !== 0 ) { return; }

            if ( fctxt.method !== fc.METHOD_GET ) {
                if ( fctxt.method !== fc.METHOD_POST ) {
                    return;
                }
            }

            // https://github.com/gorhill/uBlock/issues/3478
            const statusCode = details.statusCode || 0;
            if ( statusCode === 0 ) { return; }

            const hostname = fctxt.getHostname();
            if ( hostname === '' ) { return; }

            // https://bugzilla.mozilla.org/show_bug.cgi?id=1426789
            const headers = details.responseHeaders;
            const disposition = headerValueFromName('content-disposition', headers);
            if ( disposition !== '' ) {
                if ( disposition.startsWith('inline') === false ) { return; }
            }

            mime = 'text/plain';
            charset = 'utf-8';
            const contentType = headerValueFromName('content-type', headers) ||
                contentTypeFromDetails(details);
            if ( contentType !== '' ) {
                mime = mimeFromContentType(contentType);
                if ( mime === undefined ) { return; }
                if ( mime.startsWith('text/') === false ) {
                    if ( otherValidMimes.has(mime) === false ) { return; }
                }
                charset = charsetFromContentType(contentType);
                if ( charset !== undefined ) {
                    charset = textEncode.normalizeCharset(charset);
                    if ( charset === undefined ) { return; }
                } else {
                    charset = charsetFromMime(mime);
                }
            }

            return true;
        }
    };
})();

/******************************************************************************/

function injectCSP(fctxt, pageStore, responseHeaders) {
    const cspSubsets = [];
    const requestType = fctxt.type;

    // Start collecting policies >>>>>>>>

    // ======== built-in policies

    const builtinDirectives = [];

    if ( pageStore.filterScripting(fctxt, true) === 1 ) {
        builtinDirectives.push(µb.hiddenSettings.noScriptingCSP);
        if ( logger.enabled ) {
            fctxt.setRealm('network').setType('scripting').toLogger();
        }
    }
    // https://github.com/uBlockOrigin/uBlock-issues/issues/422
    //   We need to derive a special context for filtering `inline-script`,
    //   as the embedding document for this "resource" will always be the
    //   frame itself, not that of the parent of the frame.
    else {
        const fctxt2 = fctxt.duplicate();
        fctxt2.type = 'inline-script';
        fctxt2.setDocOriginFromURL(fctxt.url);
        const result = pageStore.filterRequest(fctxt2);
        if ( result === 1 ) {
            builtinDirectives.push(µb.cspNoInlineScript);
        }
        if ( result === 2 && logger.enabled ) {
            fctxt2.setRealm('network').toLogger();
        }
    }

    // https://github.com/gorhill/uBlock/issues/1539
    // - Use a CSP to also forbid inline fonts if remote fonts are blocked.
    fctxt.type = 'inline-font';
    if ( pageStore.filterRequest(fctxt) === 1 ) {
        builtinDirectives.push(µb.cspNoInlineFont);
        if ( logger.enabled ) {
            fctxt.setRealm('network').toLogger();
        }
    }

    if ( builtinDirectives.length !== 0 ) {
        cspSubsets[0] = builtinDirectives.join(', ');
    }

    // ======== filter-based policies

    // Static filtering.

    fctxt.type = requestType;
    const staticDirectives =
        staticNetFilteringEngine.matchAndFetchModifiers(fctxt, 'csp');
    if ( staticDirectives !== undefined ) {
        for ( const directive of staticDirectives ) {
            if ( directive.result !== 1 ) { continue; }
            cspSubsets.push(directive.value);
        }
    }

    // URL filtering `allow` rules override static filtering.
    if (
        cspSubsets.length !== 0 &&
        sessionURLFiltering.evaluateZ(
            fctxt.getTabHostname(),
            fctxt.url,
            'csp'
        ) === 2
    ) {
        if ( logger.enabled ) {
            fctxt.setRealm('network')
                 .setType('csp')
                 .setFilter(sessionURLFiltering.toLogData())
                 .toLogger();
        }
        return;
    }

    // Dynamic filtering `allow` rules override static filtering.
    if (
        cspSubsets.length !== 0 &&
        µb.userSettings.advancedUserEnabled &&
        sessionFirewall.evaluateCellZY(
            fctxt.getTabHostname(),
            fctxt.getTabHostname(),
            '*'
        ) === 2
    ) {
        if ( logger.enabled ) {
            fctxt.setRealm('network')
                 .setType('csp')
                 .setFilter(sessionFirewall.toLogData())
                 .toLogger();
        }
        return;
    }

    // <<<<<<<< All policies have been collected

    // Static CSP policies will be applied.

    if ( logger.enabled && staticDirectives !== undefined ) {
        fctxt.setRealm('network')
             .pushFilters(staticDirectives.map(a => a.logData()))
             .toLogger();
    }

    if ( cspSubsets.length === 0 ) { return; }

    µb.updateToolbarIcon(fctxt.tabId, 0b0010);

    // Use comma to merge CSP directives.
    // Ref.: https://www.w3.org/TR/CSP2/#implementation-considerations
    //
    // https://github.com/gorhill/uMatrix/issues/967
    //   Inject a new CSP header rather than modify an existing one, except
    //   if the current environment does not support merging headers:
    //   Firefox 58/webext and less can't merge CSP headers, so we will merge
    //   them here.

    responseHeaders.push({
        name: 'Content-Security-Policy',
        value: cspSubsets.join(', ')
    });

    return true;
}

/******************************************************************************/

function injectPP(fctxt, pageStore, responseHeaders) {
    const permissions = [];
    const directives = staticNetFilteringEngine.matchAndFetchModifiers(fctxt, 'permissions');
    if ( directives !== undefined ) {
        for ( const directive of directives ) {
            if ( directive.result !== 1 ) { continue; }
            permissions.push(directive.value.replace('|', ', '));
        }
    }

    if ( logger.enabled && directives !== undefined ) {
        fctxt.setRealm('network')
             .pushFilters(directives.map(a => a.logData()))
             .toLogger();
    }

    if ( permissions.length === 0 ) { return; }

    µb.updateToolbarIcon(fctxt.tabId, 0x02);

    responseHeaders.push({
        name: 'permissions-policy',
        value: permissions.join(', ')
    });

    return true;
}

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/1163
//   "Block elements by size".
// https://github.com/gorhill/uBlock/issues/1390#issuecomment-187310719
//   Do not foil when the media element is fetched from the browser
//   cache. This works only when the webext API supports the `fromCache`
//   property (Firefox).

function foilLargeMediaElement(details, fctxt, pageStore) {
    if ( details.fromCache === true ) { return; }

    onDemandHeaders.setHeaders(details.responseHeaders);

    const result = pageStore.filterLargeMediaElement(fctxt, onDemandHeaders);

    onDemandHeaders.reset();

    if ( result === 0 ) { return; }

    if ( logger.enabled ) {
        fctxt.setRealm('network').toLogger();
    }

    return { cancel: true };
}

foilLargeMediaElement.TYPE_BITS = fc.IMAGE | fc.MEDIA | fc.XMLHTTPREQUEST;

/******************************************************************************/

// Caller must ensure headerName is normalized to lower case.

const headerIndexFromName = function(headerName, headers) {
    for ( let i = 0, n = headers.length; i < n; i++ ) {
        if ( headers[i].name.toLowerCase() === headerName ) { return i; }
    }
    return -1;
};

const headerValueFromName = function(headerName, headers) {
    const i = headerIndexFromName(headerName, headers);
    return i !== -1 ? headers[i].value : '';
};

const onDemandHeaders = {
    headers: [],
    get contentLength() {
        const contentLength = headerValueFromName('content-length', this.headers);
        if ( contentLength === '' ) { return Number.NaN; }
        return parseInt(contentLength, 10) || 0;
    },
    get contentType() {
        return headerValueFromName('content-type', this.headers);
    },
    setHeaders(headers) {
        this.headers = headers;
    },
    reset() {
        this.headers = [];
    }
};

/******************************************************************************/

const strictBlockBypasser = {
    hostnameToDeadlineMap: new Map(),
    cleanupTimer: vAPI.defer.create(( ) => {
        strictBlockBypasser.cleanup();
    }),

    cleanup: function() {
        for ( const [ hostname, deadline ] of this.hostnameToDeadlineMap ) {
            if ( deadline <= Date.now() ) {
                this.hostnameToDeadlineMap.delete(hostname);
            }
        }
    },

    revokeTime: function() {
        return Date.now() + µb.hiddenSettings.strictBlockingBypassDuration * 1000;
    },

    bypass: function(hostname) {
        if ( typeof hostname !== 'string' || hostname === '' ) { return; }
        this.hostnameToDeadlineMap.set(hostname, this.revokeTime());
    },

    isBypassed: function(hostname) {
        if ( this.hostnameToDeadlineMap.size === 0 ) { return false; }
        this.cleanupTimer.on({ sec: µb.hiddenSettings.strictBlockingBypassDuration + 10 });
        for (;;) {
            const deadline = this.hostnameToDeadlineMap.get(hostname);
            if ( deadline !== undefined ) {
                if ( deadline > Date.now() ) {
                    this.hostnameToDeadlineMap.set(hostname, this.revokeTime());
                    return true;
                }
                this.hostnameToDeadlineMap.delete(hostname);
            }
            const pos = hostname.indexOf('.');
            if ( pos === -1 ) { break; }
            hostname = hostname.slice(pos + 1);
        }
        return false;
    }
};

/******************************************************************************/

function onResponseStarted(details) {
    if ( details.tabId === -1 ) { return; }
    const pageStore = µb.pageStoreFromTabId(details.tabId);
    if ( pageStore === null ) { return; }
    if ( pageStore.getNetFilteringSwitch() === false ) { return; }
    // To enforce strict-blocking with ipaddress option
    if ( isGecko === false && details.type === 'main_frame' ) {
        const fctxt = µb.filteringContext.fromWebrequestDetails(details);
        const r = onBeforeRootFrameRequest(fctxt);
        if ( r?.cancel ) { return; }
    }
    details.ancestors = pageStore.getFrameAncestorDetails(details.frameId);
    scriptletFilteringEngine.injectNow(details);
}

/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/2350
//   Added scriptlet injection attempt at onResponseStarted time as per
//   https://github.com/AdguardTeam/AdguardBrowserExtension/issues/1029 and
//   https://github.com/AdguardTeam/AdguardBrowserExtension/blob/9ab85be5/Extension/src/background/webrequest.js#L620

const webRequest = {
    onBeforeRequest,

    start: (( ) => {
        vAPI.net = new vAPI.Net();
        if ( vAPI.Net.canSuspend() ) {
            vAPI.net.suspend();
        }

        return ( ) => {
            vAPI.net.setSuspendableListener(onBeforeRequest);
            vAPI.net.addListener('onHeadersReceived', onHeadersReceived, {
                urls: [ 'http://*/*', 'https://*/*' ]
            }, [ 'blocking', 'responseHeaders' ]);
            vAPI.net.addListener('onResponseStarted', onResponseStarted, {
                types: [ 'main_frame', 'sub_frame' ],
                urls: [ 'http://*/*', 'https://*/*' ]
            });
            vAPI.defer.once({ sec: µb.hiddenSettings.toolbarWarningTimeout }).then(( ) => {
                if ( vAPI.net.hasUnprocessedRequest() === false ) { return; }
                vAPI.net.removeUnprocessedRequest();
                return vAPI.tabs.getCurrent();
            }).then(tab => {
                if ( tab instanceof Object === false ) { return; }
                µb.updateToolbarIcon(tab.id, 0b0110);
            });
            vAPI.net.unsuspend({ all: true });
        };
    })(),

    strictBlockBypass: hostname => {
        strictBlockBypasser.bypass(hostname);
    },
};

/******************************************************************************/

export default webRequest;

/******************************************************************************/
