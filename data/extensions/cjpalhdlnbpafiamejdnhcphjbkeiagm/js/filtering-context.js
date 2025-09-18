/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2018-present Raymond Hill

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

import {
    domainFromHostname,
    hostnameFromURI,
    originFromURI,
} from './uri-utils.js';

/******************************************************************************/

// https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/ResourceType

// Long term, convert code wherever possible to work with integer-based type
// values -- the assumption being that integer operations are faster than
// string operations.

export const           NO_TYPE = 0;
export const            BEACON = 1 <<  0;
export const        CSP_REPORT = 1 <<  1;
export const              FONT = 1 <<  2;
export const             IMAGE = 1 <<  4;
export const          IMAGESET = 1 <<  4;
export const        MAIN_FRAME = 1 <<  5;
export const             MEDIA = 1 <<  6;
export const            OBJECT = 1 <<  7;
export const OBJECT_SUBREQUEST = 1 <<  7;
export const              PING = 1 <<  8;
export const            SCRIPT = 1 <<  9;
export const        STYLESHEET = 1 << 10;
export const         SUB_FRAME = 1 << 11;
export const         WEBSOCKET = 1 << 12;
export const    XMLHTTPREQUEST = 1 << 13;
export const       INLINE_FONT = 1 << 14;
export const     INLINE_SCRIPT = 1 << 15;
export const             OTHER = 1 << 16;
export const         FRAME_ANY = MAIN_FRAME | SUB_FRAME | OBJECT;
export const          FONT_ANY = FONT | INLINE_FONT;
export const        INLINE_ANY = INLINE_FONT | INLINE_SCRIPT;
export const          PING_ANY = BEACON | CSP_REPORT | PING;
export const        SCRIPT_ANY = SCRIPT | INLINE_SCRIPT;

const typeStrToIntMap = {
           'no_type': NO_TYPE,
            'beacon': BEACON,
        'csp_report': CSP_REPORT,
              'font': FONT,
             'image': IMAGE,
          'imageset': IMAGESET,
        'main_frame': MAIN_FRAME,
             'media': MEDIA,
            'object': OBJECT,
 'object_subrequest': OBJECT_SUBREQUEST,
              'ping': PING,
            'script': SCRIPT,
        'stylesheet': STYLESHEET,
         'sub_frame': SUB_FRAME,
         'websocket': WEBSOCKET,
    'xmlhttprequest': XMLHTTPREQUEST,
       'inline-font': INLINE_FONT,
     'inline-script': INLINE_SCRIPT,
             'other': OTHER,
};

export const    METHOD_NONE = 0;
export const METHOD_CONNECT = 1 << 1;
export const  METHOD_DELETE = 1 << 2;
export const     METHOD_GET = 1 << 3;
export const    METHOD_HEAD = 1 << 4;
export const METHOD_OPTIONS = 1 << 5;
export const   METHOD_PATCH = 1 << 6;
export const    METHOD_POST = 1 << 7;
export const     METHOD_PUT = 1 << 8;

const methodStrToBitMap = {
           '': METHOD_NONE,
    'connect': METHOD_CONNECT,
     'delete': METHOD_DELETE,
        'get': METHOD_GET,
       'head': METHOD_HEAD,
    'options': METHOD_OPTIONS,
      'patch': METHOD_PATCH,
       'post': METHOD_POST,
        'put': METHOD_PUT,
    'CONNECT': METHOD_CONNECT,
     'DELETE': METHOD_DELETE,
        'GET': METHOD_GET,
       'HEAD': METHOD_HEAD,
    'OPTIONS': METHOD_OPTIONS,
      'PATCH': METHOD_PATCH,
       'POST': METHOD_POST,
        'PUT': METHOD_PUT,
};

const methodBitToStrMap = new Map([
    [ METHOD_NONE, '' ],
    [ METHOD_CONNECT, 'connect' ],
    [ METHOD_DELETE, 'delete' ],
    [ METHOD_GET, 'get' ],
    [ METHOD_HEAD, 'head' ],
    [ METHOD_OPTIONS, 'options' ],
    [ METHOD_PATCH, 'patch' ],
    [ METHOD_POST, 'post' ],
    [ METHOD_PUT, 'put' ],
]);

const reIPv4 = /^\d+\.\d+\.\d+\.\d+$/;

/******************************************************************************/

export const FilteringContext = class {
    constructor(other) {
        if ( other instanceof FilteringContext ) {
            return this.fromFilteringContext(other);
        }
        this.tstamp = 0;
        this.realm = '';
        this.method = 0;
        this.itype = NO_TYPE;
        this.stype = undefined;
        this.url = undefined;
        this.aliasURL = undefined;
        this.hostname = undefined;
        this.domain = undefined;
        this.ipaddress = undefined;
        this.docId = -1;
        this.frameId = -1;
        this.docOrigin = undefined;
        this.docHostname = undefined;
        this.docDomain = undefined;
        this.tabId = undefined;
        this.tabOrigin = undefined;
        this.tabHostname = undefined;
        this.tabDomain = undefined;
        this.redirectURL = undefined;
        this.filter = undefined;
    }

    get type() {
        return this.stype;
    }

    set type(a) {
        this.itype = typeStrToIntMap[a] || NO_TYPE;
        this.stype = a;
    }

    isRootDocument() {
        return (this.itype & MAIN_FRAME) !== 0;
    }
    isDocument() {
        return (this.itype & FRAME_ANY) !== 0;
    }

    isFont() {
        return (this.itype & FONT_ANY) !== 0;
    }

    fromFilteringContext(other) {
        this.realm = other.realm;
        this.type = other.type;
        this.method = other.method;
        this.url = other.url;
        this.hostname = other.hostname;
        this.domain = other.domain;
        this.ipaddress = other.ipaddress;
        this.docId = other.docId;
        this.frameId = other.frameId;
        this.docOrigin = other.docOrigin;
        this.docHostname = other.docHostname;
        this.docDomain = other.docDomain;
        this.tabId = other.tabId;
        this.tabOrigin = other.tabOrigin;
        this.tabHostname = other.tabHostname;
        this.tabDomain = other.tabDomain;
        this.redirectURL = other.redirectURL;
        this.filter = undefined;
        return this;
    }

    fromDetails({ originURL, url, type }) {
        this.setDocOriginFromURL(originURL)
            .setURL(url)
            .setType(type);
        return this;
    }

    duplicate() {
        return (new FilteringContext(this));
    }

    setRealm(a) {
        this.realm = a;
        return this;
    }

    setType(a) {
        this.type = a;
        return this;
    }

    setURL(a) {
        if ( a !== this.url ) {
            this.hostname = this.domain = this.ipaddress = undefined;
            this.url = a;
        }
        return this;
    }

    getHostname() {
        if ( this.hostname === undefined ) {
            this.hostname = hostnameFromURI(this.url);
        }
        return this.hostname;
    }

    setHostname(a) {
        if ( a !== this.hostname ) {
            this.domain = undefined;
            this.hostname = a;
        }
        return this;
    }

    getDomain() {
        if ( this.domain === undefined ) {
            this.domain = domainFromHostname(this.getHostname());
        }
        return this.domain;
    }

    setDomain(a) {
        this.domain = a;
        return this;
    }

    getIPAddress() {
        if ( this.ipaddress !== undefined ) {
            return this.ipaddress;
        }
        const ipaddr = this.getHostname();
        const c0 = ipaddr.charCodeAt(0);
        if ( c0 === 0x5B /* [ */ ) {
            return (this.ipaddress = ipaddr.slice(1, -1));
        } else if ( c0 <= 0x39 && c0 >= 0x30 ) {
            if ( reIPv4.test(ipaddr) ) {
                return (this.ipaddress = ipaddr);
            }
        }
        return (this.ipaddress = '');
    }

    // Must always be called *after* setURL()
    setIPAddress(ipaddr) {
        this.ipaddress = ipaddr || undefined;
        return this;
    }

    getDocOrigin() {
        if ( this.docOrigin === undefined ) {
            this.docOrigin = this.tabOrigin;
        }
        return this.docOrigin;
    }

    setDocOrigin(a) {
        if ( a !== this.docOrigin ) {
            this.docHostname = this.docDomain = undefined;
            this.docOrigin = a;
        }
        return this;
    }

    setDocOriginFromURL(a) {
        return this.setDocOrigin(originFromURI(a));
    }

    getDocHostname() {
        if ( this.docHostname === undefined ) {
            this.docHostname = hostnameFromURI(this.getDocOrigin());
        }
        return this.docHostname;
    }

    setDocHostname(a) {
        if ( a !== this.docHostname ) {
            this.docDomain = undefined;
            this.docHostname = a;
        }
        return this;
    }

    getDocDomain() {
        if ( this.docDomain === undefined ) {
            this.docDomain = domainFromHostname(this.getDocHostname());
        }
        return this.docDomain;
    }

    setDocDomain(a) {
        this.docDomain = a;
        return this;
    }

    // The idea is to minimize the amount of work done to figure out whether
    // the resource is 3rd-party to the document.
    is3rdPartyToDoc() {
        let docDomain = this.getDocDomain();
        if ( docDomain === '' ) { docDomain = this.docHostname; }
        if ( this.domain !== undefined && this.domain !== '' ) {
            return this.domain !== docDomain;
        }
        const hostname = this.getHostname();
        if ( hostname.endsWith(docDomain) === false ) { return true; }
        const i = hostname.length - docDomain.length;
        if ( i === 0 ) { return false; }
        return hostname.charCodeAt(i - 1) !== 0x2E /* '.' */;
    }

    setTabId(a) {
        this.tabId = a;
        return this;
    }

    getTabOrigin() {
        return this.tabOrigin;
    }

    setTabOrigin(a) {
        if ( a !== this.tabOrigin ) {
            this.tabHostname = this.tabDomain = undefined;
            this.tabOrigin = a;
        }
        return this;
    }

    setTabOriginFromURL(a) {
        return this.setTabOrigin(originFromURI(a));
    }

    getTabHostname() {
        if ( this.tabHostname === undefined ) {
            this.tabHostname = hostnameFromURI(this.getTabOrigin());
        }
        return this.tabHostname;
    }

    setTabHostname(a) {
        if ( a !== this.tabHostname ) {
            this.tabDomain = undefined;
            this.tabHostname = a;
        }
        return this;
    }

    getTabDomain() {
        if ( this.tabDomain === undefined ) {
            this.tabDomain = domainFromHostname(this.getTabHostname());
        }
        return this.tabDomain;
    }

    setTabDomain(a) {
        this.docDomain = a;
        return this;
    }

    // The idea is to minimize the amount of work done to figure out whether
    // the resource is 3rd-party to the top document.
    is3rdPartyToTab() {
        let tabDomain = this.getTabDomain();
        if ( tabDomain === '' ) { tabDomain = this.tabHostname; }
        if ( this.domain !== undefined && this.domain !== '' ) {
            return this.domain !== tabDomain;
        }
        const hostname = this.getHostname();
        if ( hostname.endsWith(tabDomain) === false ) { return true; }
        const i = hostname.length - tabDomain.length;
        if ( i === 0 ) { return false; }
        return hostname.charCodeAt(i - 1) !== 0x2E /* '.' */;
    }

    setFilter(a) {
        this.filter = a;
        return this;
    }

    pushFilter(a) {
        if ( this.filter === undefined ) {
            return this.setFilter(a);
        }
        if ( Array.isArray(this.filter) ) {
            this.filter.push(a);
        } else {
            this.filter = [ this.filter, a ];
        }
        return this;
    }

    pushFilters(a) {
        if ( this.filter === undefined ) {
            return this.setFilter(a);
        }
        if ( Array.isArray(this.filter) ) {
            this.filter.push(...a);
        } else {
            this.filter = [ this.filter, ...a ];
        }
        return this;
    }

    setMethod(a) {
        this.method = methodStrToBitMap[a] || 0;
        return this;
    }

    getMethodName() {
        return FilteringContext.getMethodName(this.method);
    }

    static getMethod(a) {
        return methodStrToBitMap[a] || 0;
    }

    static getMethodName(a) {
        return methodBitToStrMap.get(a) || '';
    }

    BEACON = BEACON;
    CSP_REPORT = CSP_REPORT;
    FONT = FONT;
    IMAGE = IMAGE;
    IMAGESET = IMAGESET;
    MAIN_FRAME = MAIN_FRAME;
    MEDIA = MEDIA;
    OBJECT = OBJECT;
    OBJECT_SUBREQUEST = OBJECT_SUBREQUEST;
    PING = PING;
    SCRIPT = SCRIPT;
    STYLESHEET = STYLESHEET;
    SUB_FRAME = SUB_FRAME;
    WEBSOCKET = WEBSOCKET;
    XMLHTTPREQUEST = XMLHTTPREQUEST;
    INLINE_FONT = INLINE_FONT;
    INLINE_SCRIPT = INLINE_SCRIPT;
    OTHER = OTHER;
    FRAME_ANY = FRAME_ANY;
    FONT_ANY = FONT_ANY;
    INLINE_ANY = INLINE_ANY;
    PING_ANY = PING_ANY;
    SCRIPT_ANY = SCRIPT_ANY;
    METHOD_NONE = METHOD_NONE;
    METHOD_CONNECT = METHOD_CONNECT;
    METHOD_DELETE = METHOD_DELETE;
    METHOD_GET = METHOD_GET;
    METHOD_HEAD = METHOD_HEAD;
    METHOD_OPTIONS = METHOD_OPTIONS;
    METHOD_PATCH = METHOD_PATCH;
    METHOD_POST = METHOD_POST;
    METHOD_PUT = METHOD_PUT;

    static BEACON = BEACON;
    static CSP_REPORT = CSP_REPORT;
    static FONT = FONT;
    static IMAGE = IMAGE;
    static IMAGESET = IMAGESET;
    static MAIN_FRAME = MAIN_FRAME;
    static MEDIA = MEDIA;
    static OBJECT = OBJECT;
    static OBJECT_SUBREQUEST = OBJECT_SUBREQUEST;
    static PING = PING;
    static SCRIPT = SCRIPT;
    static STYLESHEET = STYLESHEET;
    static SUB_FRAME = SUB_FRAME;
    static WEBSOCKET = WEBSOCKET;
    static XMLHTTPREQUEST = XMLHTTPREQUEST;
    static INLINE_FONT = INLINE_FONT;
    static INLINE_SCRIPT = INLINE_SCRIPT;
    static OTHER = OTHER;
    static FRAME_ANY = FRAME_ANY;
    static FONT_ANY = FONT_ANY;
    static INLINE_ANY = INLINE_ANY;
    static PING_ANY = PING_ANY;
    static SCRIPT_ANY = SCRIPT_ANY;
    static METHOD_NONE = METHOD_NONE;
    static METHOD_CONNECT = METHOD_CONNECT;
    static METHOD_DELETE = METHOD_DELETE;
    static METHOD_GET = METHOD_GET;
    static METHOD_HEAD = METHOD_HEAD;
    static METHOD_OPTIONS = METHOD_OPTIONS;
    static METHOD_PATCH = METHOD_PATCH;
    static METHOD_POST = METHOD_POST;
    static METHOD_PUT = METHOD_PUT;
};

/******************************************************************************/
