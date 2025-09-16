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

/******************************************************************************/

//                example.com: domain => no slash
//           example.com/toto: domain + path => slash
//         /example\d+\.com$/: domain regex: no literal slash in regex
// /example\d+\.com\/toto\d+/: domain + path => literal slash in regex

/******************************************************************************/

const naivePathnameFromURL = url => {
    if ( typeof url !== 'string' ) { return; }
    const hnPos = url.indexOf('://');
    if ( hnPos === -1 ) { return; }
    const pathPos = url.indexOf('/', hnPos+3);
    if ( pathPos === -1 ) { return; }
    return url.slice(pathPos);
};

const extractSubTargets = target => {
    const isRegex = target.charCodeAt(0) === 0x2F /* / */;
    if ( isRegex === false ) {
        const pathPos = target.indexOf('/');
        return {
            isRegex,
            hn: target.slice(0, pathPos),
            pn: target.slice(pathPos),
        };
    }
    const pathPos = target.indexOf('\\/');
    if ( pathPos !== -1 ) {
        return {
            isRegex,
            hn: `${target.slice(1, pathPos)}$`,
            pn: `^${target.slice(pathPos, -1)}`,
        };
    }
    return { isRegex, hn: target.slice(1, -1) };
};

/******************************************************************************/

export class StaticExtFilteringHostnameDB {
    static VERSION = 1;
    constructor() {
        this.size = 0;
    }

    #hostnameToStringListMap = new Map();
    #matcherMap = new Map();
    #hostnameToMatcherListMap = new Map();
    #strSlots = [ '' ];     // Array of strings (selectors and pseudo-selectors)
    #matcherSlots = [ null ];
    #linkedLists = [ 0, 0 ];// Array of integer pairs
    #regexMap = new Map();
    #strToSlotMap = new Map();
    #cleanupTimer = vAPI.defer.create(( ) => {
        this.#strToSlotMap.clear();
    });

    store(target, s) {
        this.size += 1;
        let iStr = this.#strToSlotMap.get(s);
        if ( iStr === undefined ) {
            iStr = this.#strSlots.length;
            this.#strSlots.push(s);
            this.#strToSlotMap.set(s, iStr);
            if ( this.#cleanupTimer.ongoing() === false ) {
                this.collectGarbage(true);
            }
        }
        if ( target.includes('/') ) {
            return this.#storeMatcher(target, iStr);
        }
        const iList = this.#hostnameToStringListMap.get(target) ?? 0;
        this.#hostnameToStringListMap.set(target, this.#linkedLists.length);
        this.#linkedLists.push(iStr, iList);
    }

    #storeMatcher(target, iStr) {
        const iMatcher = this.#matcherMap.get(target) ||
            this.#matcherSlots.length;
        if ( iMatcher === this.#matcherSlots.length ) {
            const { isRegex, hn, pn } = extractSubTargets(target);
            this.#matcherSlots.push({ isRegex, hn, pn, iList: 0 });
            this.#matcherMap.set(target, iMatcher);
            if ( isRegex === false ) {
                const iMatcherList = this.#hostnameToMatcherListMap.get(hn) ?? 0;
                this.#hostnameToMatcherListMap.set(hn, this.#linkedLists.length);
                this.#linkedLists.push(iMatcher, iMatcherList);
            } else {
                const iMatcherList = this.#hostnameToMatcherListMap.get('') ?? 0;
                this.#hostnameToMatcherListMap.set('', this.#linkedLists.length);
                this.#linkedLists.push(iMatcher, iMatcherList);
            }
        }
        const matcher = this.#matcherSlots[iMatcher];
        const iList = matcher.iList;
        matcher.iList = this.#linkedLists.length;
        this.#linkedLists.push(iStr, iList);
    }

    clear() {
        this.#hostnameToStringListMap.clear();
        this.#matcherMap.clear();
        this.#hostnameToMatcherListMap.clear();
        this.#strSlots = [ '' ];
        this.#matcherSlots = [ null ];
        this.#linkedLists = [ 0, 0 ];
        this.#regexMap.clear();
        this.#strToSlotMap.clear();
        this.size = 0;
    }

    collectGarbage(later = false) {
        if ( later ) {
            return this.#cleanupTimer.onidle(5000, { timeout: 5000 });
        }
        this.#cleanupTimer.off();
        this.#strToSlotMap.clear();
    }

    retrieveSpecifics(out, hostname) {
        let hn = hostname;
        if ( hn === '' ) { return; }
        for (;;) {
            const iList = this.#hostnameToStringListMap.get(hn);
            if ( iList !== undefined ) {
                this.#retrieveFromSlot(out, iList);
            }
            const pos = hn.indexOf('.');
            if ( pos === -1 ) { break; }
            hn = hn.slice(pos + 1);
            if ( hn === '*' ) { break; }
        }
    }

    retrieveGenerics(out) {
        let iList = this.#hostnameToStringListMap.get('');
        if ( iList ) { this.#retrieveFromSlot(out, iList); }
        iList = this.#hostnameToStringListMap.get('*');
        if ( iList ) { this.#retrieveFromSlot(out, iList); }
    }

    retrieveSpecificsByRegex(out, hostname, url) {
        let hn = hostname;
        if ( hn === '' ) { return; }
        const pathname = naivePathnameFromURL(url) ?? '';
        for (;;) {
            this.#retrieveSpecificsByRegex(hn, out, hostname, pathname);
            const pos = hn.indexOf('.');
            if ( pos === -1 ) { break; }
            hn = hn.slice(pos + 1);
        }
        this.#retrieveSpecificsByRegex('', out, hostname, pathname);
    }

    #retrieveSpecificsByRegex(hn, out, hostname, pathname) {
        let iMatchList = this.#hostnameToMatcherListMap.get(hn) ?? 0;
        while ( iMatchList !== 0 ) {
            const iMatchSlot = this.#linkedLists[iMatchList+0];
            const matcher = this.#matcherSlots[iMatchSlot];
            if ( this.#matcherTest(matcher, hostname, pathname) ) {
                this.#retrieveFromSlot(out, matcher.iList);
            }
            iMatchList = this.#linkedLists[iMatchList+1];
        }
    }

    #matcherTest(matcher, hn, pn) {
        if ( matcher.isRegex === false ) {
            return pn.startsWith(matcher.pn);
        }
        if ( this.#restrTest(matcher.hn, hn) === false ) { return false; }
        if ( matcher.pn === undefined ) { return true; }
        return this.#restrTest(matcher.pn, pn);
    }

    #restrTest(restr, s) {
        let re = this.#regexMap.get(restr);
        if ( re === undefined ) {
            this.#regexMap.set(restr, (re = new RegExp(restr)));
        }
        return re.test(s);
    }

    #retrieveFromSlot(out, iList) {
        if ( iList === undefined ) { return; }
        do {
            const iStr = this.#linkedLists[iList+0];
            out.add(this.#strSlots[iStr]);
            iList = this.#linkedLists[iList+1];
        } while ( iList !== 0 );
    }

    toSelfie() {
        return {
            VERSION: StaticExtFilteringHostnameDB.VERSION,
            hostnameToStringListMap: this.#hostnameToStringListMap,
            matcherMap: this.#matcherMap,
            hostnameToMatcherListMap: this.#hostnameToMatcherListMap,
            strSlots: this.#strSlots,
            matcherSlots: this.#matcherSlots,
            linkedLists: this.#linkedLists,
            size: this.size
        };
    }

    fromSelfie(selfie) {
        if ( typeof selfie !== 'object' || selfie === null ) { return; }
        if ( selfie.VERSION !== StaticExtFilteringHostnameDB.VERSION ) {
            throw new TypeError('Bad selfie');
        }
        this.#hostnameToStringListMap = selfie.hostnameToStringListMap;
        this.#matcherMap = selfie.matcherMap;
        this.#hostnameToMatcherListMap = selfie.hostnameToMatcherListMap;
        this.#strSlots = selfie.strSlots;
        this.#matcherSlots = selfie.matcherSlots;
        this.#linkedLists = selfie.linkedLists;
        this.size = selfie.size;
    }
}

/******************************************************************************/
