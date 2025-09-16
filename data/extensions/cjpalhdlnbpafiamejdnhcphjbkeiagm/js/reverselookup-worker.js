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

let listEntries = Object.create(null);

/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/2092
//   Order of ids matters

const extractBlocks = function(content, ...ids) {
    const out = [];
    for ( const id of ids ) {
        const pattern = `#block-start-${id}\n`;
        let beg = content.indexOf(pattern);
        if ( beg === -1 ) { continue; }
        beg += pattern.length;
        const end = content.indexOf(`#block-end-${id}`, beg);
        out.push(content.slice(beg, end));
    }
    return out.join('\n');
};

/******************************************************************************/

// https://github.com/MajkiIT/polish-ads-filter/issues/14768#issuecomment-536006312
//   Avoid reporting badfilter-ed filters.

const fromNetFilter = function(details) {
    const lists = [];
    const compiledFilter = details.compiledFilter;

    for ( const assetKey in listEntries ) {
        const entry = listEntries[assetKey];
        if ( entry === undefined ) { continue; }
        if ( entry.networkContent === undefined ) {
            entry.networkContent = extractBlocks(entry.content, 'NETWORK_FILTERS:GOOD');
        }
        const content = entry.networkContent;
        let pos = 0;
        for (;;) {
            pos = content.indexOf(compiledFilter, pos);
            if ( pos === -1 ) { break; }
            // We need an exact match.
            // https://github.com/gorhill/uBlock/issues/1392
            // https://github.com/gorhill/uBlock/issues/835
            const notFound = pos !== 0 && content.charCodeAt(pos - 1) !== 0x0A;
            pos += compiledFilter.length;
            if (
                notFound ||
                pos !== content.length && content.charCodeAt(pos) !== 0x0A
            ) {
                continue;
            }
            lists.push({
                assetKey,
                title: entry.title,
                supportURL: entry.supportURL,
                reason: entry.reason,
            });
            break;
        }
    }

    const response = {};
    response[details.rawFilter] = lists;

    self.postMessage({ id: details.id, response });
};

/******************************************************************************/

// Looking up filter lists from a cosmetic filter is a bit more complicated
// than with network filters:
//
// The filter is its raw representation, not its compiled version. This is
// because the cosmetic filtering engine can't translate a live cosmetic
// filter into its compiled version. Reason is I do not want to burden
// cosmetic filtering with the resource overhead of being able to recompile
// live cosmetic filters. I want the cosmetic filtering code to be left
// completely unaffected by reverse lookup requirements.
//
// Mainly, given a CSS selector and a hostname as context, we will derive
// various versions of compiled filters and see if there are matches. This
// way the whole CPU cost is incurred by the reverse lookup code -- in a
// worker thread, and the cosmetic filtering engine incurs no cost at all.
//
// For this though, the reverse lookup code here needs some knowledge of
// the inners of the cosmetic filtering engine.
// FilterContainer.fromCompiledContent() is our reference code to create
// the various compiled versions.

const fromExtendedFilter = function(details) {
    const match = /^#@?#\^?/.exec(details.rawFilter);
    const prefix = match[0];
    const exception = prefix.charAt(1) === '@';
    const selector = details.rawFilter.slice(prefix.length);
    const isHtmlFilter = prefix.endsWith('^');
    const url = new URL(details.url || 'about:blank');
    const { hostname, pathname } = url;

    // The longer the needle, the lower the number of false positives.
    // https://github.com/uBlockOrigin/uBlock-issues/issues/1139
    //   Mind that there is no guarantee a selector has `\w` characters.
    const needle = (details.needle || selector).match(/\w+|\*/g).reduce(function(a, b) {
        return a.length > b.length ? a : b;
    });

    const regexFromLabels = (prefix, hn, suffix) =>
        new RegExp(
            prefix +
            hn.split('.').reduce((acc, item) => `(${acc}\\.)?${item}`) +
            suffix
        );

    // https://github.com/uBlockOrigin/uBlock-issues/issues/803
    //   Support looking up selectors of the form `*##...`
    const reHostname = regexFromLabels('^', hostname, '$');
    let reEntity;
    {
        const domain = details.domain;
        const pos = domain.indexOf('.');
        if ( pos !== -1 ) {
            reEntity = regexFromLabels(
                '^(',
                hostname.slice(0, pos + hostname.length - domain.length),
                '\\.)?\\*$'
            );
        }
    }

    const hostnameTargetMatchesHostname = target => {
        if ( target === '' ) { return true; }
        if ( reHostname.test(target) ) { return true; }
        if ( reEntity === undefined ) { return false; }
        if ( reEntity.test(target) ) { return true; }
        return false;
    };

    const regexTargetMatchesHostname = target => {
        return (new RegExp(target)).test(hostname);
    };

    const regexTargetMatchesURL = target => {
        const pathPos = target.indexOf('\\/');
        if ( pathPos === -1 ) {
            return regexTargetMatchesHostname(target);
        }
        return regexTargetMatchesHostname(`${target.slice(1, pathPos)}$`) &&
            (new RegExp(`^${target.slice(pathPos, -1)}`)).test(pathname);
    };

    const pathTargetMatchesURL = target => {
        const pathPos = target.indexOf('/');
        return hostnameTargetMatchesHostname(target.slice(0, pathPos)) &&
            pathname.startsWith(target.slice(pathPos));
    };

    const targetMatchesURL = target => {
        if ( target.charCodeAt(0) === 0x2F /* / */ ) {
            return regexTargetMatchesURL(target.slice(1, -1));
        }
        if ( target.includes('/') ) {
            return pathTargetMatchesURL(target);
        }
        return hostnameTargetMatchesHostname(target);
    };

    const response = Object.create(null);

    for ( const assetKey in listEntries ) {
        const entry = listEntries[assetKey];
        if ( entry === undefined ) { continue; }
        if ( entry.extendedContent === undefined ) {
            entry.extendedContent = extractBlocks(
                entry.content,
                'COSMETIC_FILTERS:SPECIFIC',
                'COSMETIC_FILTERS:GENERIC',
                'SCRIPTLET_FILTERS',
                'HTML_FILTERS',
                'HTTPHEADER_FILTERS'
            );
        }
        const content = entry.extendedContent;
        let found;
        let pos = 0;
        while ( (pos = content.indexOf(needle, pos)) !== -1 ) {
            let beg = content.lastIndexOf('\n', pos);
            if ( beg === -1 ) { beg = 0; }
            let end = content.indexOf('\n', pos);
            if ( end === -1 ) { end = content.length; }
            pos = end;
            const fargs = JSON.parse(content.slice(beg, end));
            const filterType = fargs[0];

            // https://github.com/gorhill/uBlock/issues/2763
            if ( filterType === 0 && details.ignoreGeneric ) { continue; }

            // Do not confuse cosmetic filters with HTML ones.
            if ( (filterType === 64) !== isHtmlFilter ) { continue; }

            switch ( filterType ) {
            // Lowly generic cosmetic filters
            case 0:
                if ( exception ) { break; }
                if ( fargs[2] !== selector ) { break; }
                found = prefix + selector;
                break;
            // Highly generic cosmetic filters
            case 4: // simple highly generic
            case 5: // complex highly generic
                if ( exception ) { break; }
                if ( fargs[1] !== selector ) { break; }
                found = prefix + selector;
                break;
            // Specific cosmetic filtering
            // Generic exception
            case 8:
            // HTML filtering
            // Response header filtering
            /* fallthrough */
            case 64: {
                if ( exception !== (fargs[2].charCodeAt(0) === 0x2D /* - */) ) { break; }
                const candidate = fargs[2].slice(1);
                if ( /^responseheader\(.+\)$/.test(selector) ) {
                    if ( candidate !== needle ) { break; }
                    if ( targetMatchesURL(fargs[1]) === false ) { break; }
                    found = fargs[1] + prefix + selector;
                    break;
                }
                const isProcedural = candidate.charCodeAt(0) === 0x7B /* { */;
                if (
                    isProcedural === false && candidate !== selector ||
                    isProcedural && JSON.parse(candidate).raw !== selector
                ) {
                    break;
                }
                if ( targetMatchesURL(fargs[1]) === false ) { break; }
                // https://www.reddit.com/r/uBlockOrigin/comments/d6vxzj/
                //   Ignore match if specific cosmetic filters are disabled
                if ( 
                    filterType === 8 &&
                    exception === false &&
                    details.ignoreSpecific
                ) {
                    break;
                }
                found = fargs[1] + prefix + selector;
                break;
            }
            // Scriptlet injection
            case 32: {
                if ( exception !== (fargs[2].charCodeAt(0) === 0x2D /* - */) ) { break; }
                const candidate = fargs[2].slice(1);
                if ( candidate !== details.needle ) { break; }
                if (targetMatchesURL(fargs[1]) ) {
                    found = fargs[1] + prefix + selector;
                }
                break;
            }
            default:
                break;
            }
            if ( found !== undefined  ) {
                if ( response[found] === undefined ) {
                    response[found] = [];
                }
                response[found].push({
                    assetKey: assetKey,
                    title: entry.title,
                    supportURL: entry.supportURL
                });
                break;
            }
        }
    }

    self.postMessage({ id: details.id, response });
};

/******************************************************************************/

self.onmessage = function(e) {
    const msg = e.data;

    switch ( msg.what ) {
    case 'resetLists':
        listEntries = Object.create(null);
        break;

    case 'setList':
        listEntries[msg.details.assetKey] = msg.details;
        break;

    case 'fromNetFilter':
        fromNetFilter(msg);
        break;

    case 'fromExtendedFilter':
        fromExtendedFilter(msg);
        break;
    }
};

/******************************************************************************/
