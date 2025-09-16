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

import publicSuffixList from '../lib/publicsuffixlist/publicsuffixlist.js';
import punycode from '../lib/punycode.js';

/******************************************************************************/

// Originally:
// https://github.com/gorhill/uBlock/blob/8b5733a58d3acf9fb62815e14699c986bd1c2fdc/src/js/uritools.js

const reHostnameFromCommonURL =
    /^https:\/\/[0-9a-z._-]+[0-9a-z]\//;
const reAuthorityFromURI =
    /^(?:[^:/?#]+:)?(\/\/[^/?#]+)/;
const reHostFromNakedAuthority =
    /^[0-9a-z._-]+[0-9a-z]$/i;
const reHostFromAuthority =
    /^(?:[^@]*@)?([^:]+)(?::\d*)?$/;
const reIPv6FromAuthority =
    /^(?:[^@]*@)?(\[[0-9a-f:]+\])(?::\d*)?$/i;
const reMustNormalizeHostname =
    /[^0-9a-z._-]/;
const reOriginFromURI =
    /^[^:/?#]+:\/\/[^/?#]+/;
const reHostnameFromNetworkURL =
    /^(?:http|ws|ftp)s?:\/\/([0-9a-z_][0-9a-z._-]*[0-9a-z])(?::\d+)?\//;
const reIPAddressNaive =
    /^\d+\.\d+\.\d+\.\d+$|^\[[\da-zA-Z:]+\]$/;
const reNetworkURI =
    /^(?:ftps?|https?|wss?):\/\//;

// For performance purpose, as simple tests as possible
const reIPv4VeryCoarse = /\.\d+$/;
const reHostnameVeryCoarse = /[g-z_-]/;

/******************************************************************************/

function domainFromHostname(hostname) {
    return reIPAddressNaive.test(hostname)
        ? hostname
        : publicSuffixList.getDomain(hostname);
}

function domainFromURI(uri) {
    if ( !uri ) { return ''; }
    return domainFromHostname(hostnameFromURI(uri));
}

function entityFromDomain(domain) {
    const pos = domain.indexOf('.');
    return pos !== -1 ? domain.slice(0, pos) + '.*' : '';
}

function entityFromHostname(hostname, domain) {
    if ( domain === undefined ) {
        domain = domainFromHostname(hostname);
    }
    const entity = entityFromDomain(domain);
    if ( entity === '' ) { return ''; }
    return `${hostname.slice(0, -domain.length)}${entity}`
}

function hostnameFromURI(uri) {
    let match = reHostnameFromCommonURL.exec(uri);
    if ( match !== null ) { return match[0].slice(8, -1); }
    match = reAuthorityFromURI.exec(uri);
    if ( match === null ) { return ''; }
    const authority = match[1].slice(2);
    if ( reHostFromNakedAuthority.test(authority) ) {
        return authority.toLowerCase();
    }
    match = reHostFromAuthority.exec(authority);
    if ( match === null ) {
        match = reIPv6FromAuthority.exec(authority);
        if ( match === null ) { return ''; }
    }
    let hostname = match[1];
    while ( hostname.endsWith('.') ) {
        hostname = hostname.slice(0, -1);
    }
    if ( reMustNormalizeHostname.test(hostname) ) {
        hostname = punycode.toASCII(hostname.toLowerCase());
    }
    return hostname;
}

function hostnameFromNetworkURL(url) {
    const matches = reHostnameFromNetworkURL.exec(url);
    return matches !== null ? matches[1] : '';
}

function originFromURI(uri) {
    let match = reHostnameFromCommonURL.exec(uri);
    if ( match !== null ) { return match[0].slice(0, -1); }
    match = reOriginFromURI.exec(uri);
    return match !== null ? match[0].toLowerCase() : '';
}

function isNetworkURI(uri) {
    return reNetworkURI.test(uri);
}

/******************************************************************************/

function toBroaderHostname(hostname) {
    const pos = hostname.indexOf('.');
    if ( pos !== -1 ) {
        return hostname.slice(pos + 1);
    }
    return hostname !== '*' && hostname !== '' ? '*' : '';
}

function toBroaderIPv4Address(ipaddress) {
    if ( ipaddress === '*' || ipaddress === '' ) { return ''; }
    const pos = ipaddress.lastIndexOf('.');
    if ( pos === -1 ) { return '*'; }
    return ipaddress.slice(0, pos);
}

function toBroaderIPv6Address(ipaddress) {
    return ipaddress !== '*' && ipaddress !== '' ? '*' : '';
}

function decomposeHostname(hostname, out) {
    if ( out.length !== 0 && out[0] === hostname ) {
        return out;
    }
    let broadenFn;
    if ( reHostnameVeryCoarse.test(hostname) === false ) {
        if ( reIPv4VeryCoarse.test(hostname) ) {
            broadenFn = toBroaderIPv4Address;
        } else if ( hostname.startsWith('[') ) {
            broadenFn = toBroaderIPv6Address;
        }
    }
    if ( broadenFn === undefined ) {
        broadenFn = toBroaderHostname;
    }
    out[0] = hostname;
    let i = 1;
    for (;;) {
        hostname = broadenFn(hostname);
        if ( hostname === '' ) { break; }
        out[i++] = hostname;
    }
    out.length = i;
    return out;
}

/******************************************************************************/

export {
    decomposeHostname,
    domainFromHostname,
    domainFromURI,
    entityFromDomain,
    entityFromHostname,
    hostnameFromNetworkURL,
    hostnameFromURI,
    isNetworkURI,
    originFromURI,
};
