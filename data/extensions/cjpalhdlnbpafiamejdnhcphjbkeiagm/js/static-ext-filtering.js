/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2017-present Raymond Hill

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

import cosmeticFilteringEngine from './cosmetic-filtering.js';
import htmlFilteringEngine from './html-filtering.js';
import httpheaderFilteringEngine from './httpheader-filtering.js';
import logger from './logger.js';
import scriptletFilteringEngine from './scriptlet-filtering.js';

/*******************************************************************************

  All static extended filters are of the form:

  field 1: one hostname, or a list of comma-separated hostnames
  field 2: `##` or `#@#`
  field 3: selector

  The purpose of the static extended filtering engine is to coarse-parse and
  dispatch to appropriate specialized filtering engines. There are currently
  three specialized filtering engines:

  - cosmetic filtering (aka "element hiding" in Adblock Plus)
  - scriptlet injection: selector starts with `script:inject`
    - New shorter syntax (1.15.12): `example.com##+js(bab-defuser.js)`
  - html filtering: selector starts with `^`

  Depending on the specialized filtering engine, field 1 may or may not be
  optional.

  The static extended filtering engine also offers parsing capabilities which
  are available to all other specialized filtering engines. For example,
  cosmetic and html filtering can ask the extended filtering engine to
  compile/validate selectors.

**/

//--------------------------------------------------------------------------
// Public API
//--------------------------------------------------------------------------

const staticExtFilteringEngine = {
    get acceptedCount() {
        return cosmeticFilteringEngine.acceptedCount +
               scriptletFilteringEngine.acceptedCount +
               httpheaderFilteringEngine.acceptedCount +
               htmlFilteringEngine.acceptedCount;
    },
    get discardedCount() {
        return cosmeticFilteringEngine.discardedCount +
               scriptletFilteringEngine.discardedCount +
               httpheaderFilteringEngine.discardedCount +
               htmlFilteringEngine.discardedCount;
    },
};

//--------------------------------------------------------------------------
// Public methods
//--------------------------------------------------------------------------

staticExtFilteringEngine.reset = function() {
    cosmeticFilteringEngine.reset();
    scriptletFilteringEngine.reset();
    httpheaderFilteringEngine.reset();
    htmlFilteringEngine.reset();
};

staticExtFilteringEngine.freeze = function() {
    cosmeticFilteringEngine.freeze();
    scriptletFilteringEngine.freeze();
    httpheaderFilteringEngine.freeze();
    htmlFilteringEngine.freeze();
};

staticExtFilteringEngine.compile = function(parser, writer) {
    if ( parser.isExtendedFilter() === false ) { return false; }

    if ( parser.hasError() ) {
        logger.writeOne({
            realm: 'message',
            type: 'error',
            text: `Invalid extended filter in ${writer.properties.get('name') || '?'}: ${parser.raw}`
        });
        return true;
    }

    // Scriptlet injection
    if ( parser.isScriptletFilter() ) {
        scriptletFilteringEngine.compile(parser, writer);
        return true;
    }

    // Response header filtering
    if ( parser.isResponseheaderFilter() ) {
        httpheaderFilteringEngine.compile(parser, writer);
        return true;
    }

    // HTML filtering
    // TODO: evaluate converting Adguard's `$$` syntax into uBO's HTML
    //       filtering syntax.
    if ( parser.isHtmlFilter() ) {
        htmlFilteringEngine.compile(parser, writer);
        return true;
    }

    // Cosmetic filtering
    if ( parser.isCosmeticFilter() ) {
        cosmeticFilteringEngine.compile(parser, writer);
        return true;
    }

    logger.writeOne({
        realm: 'message',
        type: 'error',
        text: `Unknown extended filter in ${writer.properties.get('name') || '?'}: ${parser.raw}`
    });
    return true;
};

staticExtFilteringEngine.fromCompiledContent = function(reader, options) {
    cosmeticFilteringEngine.fromCompiledContent(reader, options);
    scriptletFilteringEngine.fromCompiledContent(reader, options);
    httpheaderFilteringEngine.fromCompiledContent(reader, options);
    htmlFilteringEngine.fromCompiledContent(reader, options);
};

staticExtFilteringEngine.toSelfie = function() {
    return {
        cosmetic: cosmeticFilteringEngine.toSelfie(),
        scriptlets: scriptletFilteringEngine.toSelfie(),
        httpHeaders: httpheaderFilteringEngine.toSelfie(),
        html: htmlFilteringEngine.toSelfie(),
    };
};

staticExtFilteringEngine.fromSelfie = async function(selfie) {
    if ( typeof selfie !== 'object' || selfie === null ) { return false; }
    cosmeticFilteringEngine.fromSelfie(selfie.cosmetic);
    httpheaderFilteringEngine.fromSelfie(selfie.httpHeaders);
    htmlFilteringEngine.fromSelfie(selfie.html);
    if ( scriptletFilteringEngine.fromSelfie(selfie.scriptlets) === false ) {
        return false;
    }
    return true;
};

/******************************************************************************/

export default staticExtFilteringEngine;

/******************************************************************************/
