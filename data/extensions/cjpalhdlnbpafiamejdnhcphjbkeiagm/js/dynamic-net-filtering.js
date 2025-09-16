/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-2018 Raymond Hill

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
    decomposeHostname,
    domainFromHostname,
} from './uri-utils.js';
import { LineIterator } from './text-utils.js';
import punycode from '../lib/punycode.js';

/******************************************************************************/

// Object.create(null) is used below to eliminate worries about unexpected
// property names in prototype chain -- and this way we don't have to use
// Object.hasOwn() to avoid this.

const supportedDynamicTypes = Object.create(null);
Object.assign(supportedDynamicTypes, {
           '3p': true,
        'image': true,
'inline-script': true,
    '1p-script': true,
    '3p-script': true,
     '3p-frame': true
});

const typeBitOffsets = Object.create(null);
Object.assign(typeBitOffsets, {
            '*':  0,
'inline-script':  2,
    '1p-script':  4,
    '3p-script':  6,
     '3p-frame':  8,
        'image': 10,
           '3p': 12
});

const nameToActionMap = Object.create(null);
Object.assign(nameToActionMap, {
    'block': 1,
    'allow': 2,
     'noop': 3
});

const intToActionMap = new Map([
    [ 1, 'block' ],
    [ 2, 'allow' ],
    [ 3, 'noop' ]
]);

// For performance purpose, as simple tests as possible
const reBadHostname = /[^0-9a-z_.[\]:%-]/;
const reNotASCII = /[^\x20-\x7F]/;
const decomposedSource = [];
const decomposedDestination = [];

/******************************************************************************/

function is3rdParty(srcHostname, desHostname) {
    // If at least one is party-less, the relation can't be labelled
    // "3rd-party"
    if ( desHostname === '*' || srcHostname === '*' || srcHostname === '' ) {
        return false;
    }

    // No domain can very well occurs, for examples:
    // - localhost
    // - file-scheme
    // etc.
    const srcDomain = domainFromHostname(srcHostname) || srcHostname;

    if ( desHostname.endsWith(srcDomain) === false ) {
        return true;
    }
    // Do not confuse 'example.com' with 'anotherexample.com'
    return desHostname.length !== srcDomain.length &&
           desHostname.charAt(desHostname.length - srcDomain.length - 1) !== '.';
}

/******************************************************************************/

class DynamicHostRuleFiltering {

    constructor() {
        this.reset();
    }

    reset() {
        this.r = 0;
        this.type = '';
        this.y = '';
        this.z = '';
        this.rules = new Map();
        this.changed = false;
    }

    assign(other) {
        // Remove rules not in other
        for ( const k of this.rules.keys() ) {
            if ( other.rules.has(k) === false ) {
                this.rules.delete(k);
                this.changed = true;
            }
        }
        // Add/change rules in other
        for ( const entry of other.rules ) {
            if ( this.rules.get(entry[0]) !== entry[1] ) {
                this.rules.set(entry[0], entry[1]);
                this.changed = true;
            }
        }
    }

    copyRules(from, srcHostname, desHostnames) {
        // Specific types
        let thisBits = this.rules.get('* *');
        let fromBits = from.rules.get('* *');
        if ( fromBits !== thisBits ) {
            if ( fromBits !== undefined ) {
                this.rules.set('* *', fromBits);
            } else {
                this.rules.delete('* *');
            }
            this.changed = true;
        }

        let key = `${srcHostname} *`;
        thisBits = this.rules.get(key);
        fromBits = from.rules.get(key);
        if ( fromBits !== thisBits ) {
            if ( fromBits !== undefined ) {
                this.rules.set(key, fromBits);
            } else {
                this.rules.delete(key);
            }
            this.changed = true;
        }

        // Specific destinations
        for ( const desHostname in desHostnames ) {
            key = `* ${desHostname}`;
            thisBits = this.rules.get(key);
            fromBits = from.rules.get(key);
            if ( fromBits !== thisBits ) {
                if ( fromBits !== undefined ) {
                    this.rules.set(key, fromBits);
                } else {
                    this.rules.delete(key);
                }
                this.changed = true;
            }
            key = `${srcHostname} ${desHostname}` ;
            thisBits = this.rules.get(key);
            fromBits = from.rules.get(key);
            if ( fromBits !== thisBits ) {
                if ( fromBits !== undefined ) {
                    this.rules.set(key, fromBits);
                } else {
                    this.rules.delete(key);
                }
                this.changed = true;
            }
        }

        return this.changed;
    }

    // - *    *  type
    // - from *  type
    // - *    to *
    // - from to *

    hasSameRules(other, srcHostname, desHostnames) {
        // Specific types
        let key = '* *';
        if ( this.rules.get(key) !== other.rules.get(key) ) { return false; }
        key = `${srcHostname} *`;
        if ( this.rules.get(key) !== other.rules.get(key) ) { return false; }
        // Specific destinations
        for ( const desHostname in desHostnames ) {
            key = `* ${desHostname}`;
            if ( this.rules.get(key) !== other.rules.get(key) ) {
                return false;
            }
            key = `${srcHostname} ${desHostname}`;
            if ( this.rules.get(key) !== other.rules.get(key) ) {
                return false;
            }
        }
        return true;
    }

    setCell(srcHostname, desHostname, type, state) {
        const bitOffset = typeBitOffsets[type];
        const k = `${srcHostname} ${desHostname}`;
        const oldBitmap = this.rules.get(k) || 0;
        const newBitmap = oldBitmap & ~(3 << bitOffset) | (state << bitOffset);
        if ( newBitmap === oldBitmap ) { return false; }
        if ( newBitmap === 0 ) {
            this.rules.delete(k);
        } else {
            this.rules.set(k, newBitmap);
        }
        this.changed = true;
        return true;
    }

    unsetCell(srcHostname, desHostname, type) {
        this.evaluateCellZY(srcHostname, desHostname, type);
        if ( this.r === 0 ) { return false; }
        this.setCell(srcHostname, desHostname, type, 0);
        this.changed = true;
        return true;
    }

    evaluateCell(srcHostname, desHostname, type) {
        const key = `${srcHostname} ${desHostname}`;
        const bitmap = this.rules.get(key);
        if ( bitmap === undefined ) { return 0; }
        return bitmap >> typeBitOffsets[type] & 3;
    }

    clearRegisters() {
        this.r = 0;
        this.type = this.y = this.z = '';
        return this;
    }

    evaluateCellZ(srcHostname, desHostname, type) {
        decomposeHostname(srcHostname, decomposedSource);
        this.type = type;
        const bitOffset = typeBitOffsets[type];
        for ( const srchn of decomposedSource ) {
            this.z = srchn;
            let v = this.rules.get(`${srchn} ${desHostname}`);
            if ( v === undefined ) { continue; }
            v = v >>> bitOffset & 3;
            if ( v === 0 ) { continue; }
            return (this.r = v);
        }
        // srcHostname is '*' at this point
        this.r = 0;
        return 0;
    }

    evaluateCellZY(srcHostname, desHostname, type) {
        // Pathological cases.
        if ( desHostname === '' ) {
            this.r = 0;
            return 0;
        }

        // Precedence: from most specific to least specific

        // Specific-destination, any party, any type
        decomposeHostname(desHostname, decomposedDestination);
        for ( const deshn of decomposedDestination ) {
            if ( deshn === '*' ) { break; }
            this.y = deshn;
            if ( this.evaluateCellZ(srcHostname, deshn, '*') !== 0 ) {
                return this.r;
            }
        }

        const thirdParty = is3rdParty(srcHostname, desHostname);

        // Any destination
        this.y = '*';

        // Specific party
        if ( thirdParty ) {
            // 3rd-party, specific type
            if ( type === 'script' ) {
                if ( this.evaluateCellZ(srcHostname, '*', '3p-script') !== 0 ) {
                    return this.r;
                }
            } else if ( type === 'sub_frame' || type === 'object' ) {
                if ( this.evaluateCellZ(srcHostname, '*', '3p-frame') !== 0 ) {
                    return this.r;
                }
            }
            // 3rd-party, any type
            if ( this.evaluateCellZ(srcHostname, '*', '3p') !== 0 ) {
                return this.r;
            }
        } else if ( type === 'script' ) {
            // 1st party, specific type
            if ( this.evaluateCellZ(srcHostname, '*', '1p-script') !== 0 ) {
                return this.r;
            }
        }

        // Any destination, any party, specific type
        if ( supportedDynamicTypes[type] !== undefined ) {
            if ( this.evaluateCellZ(srcHostname, '*', type) !== 0 ) {
                return this.r;
            }
            if ( type.startsWith('3p-') ) {
                if ( this.evaluateCellZ(srcHostname, '*', '3p') !== 0 ) {
                    return this.r;
                }
            }
        }

        // Any destination, any party, any type
        if ( this.evaluateCellZ(srcHostname, '*', '*') !== 0 ) {
            return this.r;
        }

        this.type = '';
        return 0;
    }

    mustAllowCellZY(srcHostname, desHostname, type) {
        return this.evaluateCellZY(srcHostname, desHostname, type) === 2;
    }

    mustBlockOrAllow() {
        return this.r === 1 || this.r === 2;
    }

    mustBlock() {
        return this.r === 1;
    }

    mustAbort() {
        return this.r === 3;
    }

    lookupRuleData(src, des, type) {
        const r = this.evaluateCellZY(src, des, type);
        if ( r === 0 ) { return; }
        return `${this.z} ${this.y} ${this.type} ${r}`;
    }

    toLogData() {
        if ( this.r === 0  || this.type === '' ) { return; }
        return {
            source: 'dynamicHost',
            result: this.r,
            raw: `${this.z} ${this.y} ${this.type} ${intToActionMap.get(this.r)}`
        };
    }

    srcHostnameFromRule(rule) {
        return rule.slice(0, rule.indexOf(' '));
    }

    desHostnameFromRule(rule) {
        return rule.slice(rule.indexOf(' ') + 1);
    }

    toArray() {
        const out = [];
        for ( const key of this.rules.keys() ) {
            const srchn = this.srcHostnameFromRule(key);
            const deshn = this.desHostnameFromRule(key);
            const srchnPretty = srchn.includes('xn--') && punycode
                ? punycode.toUnicode(srchn)
                : srchn;
            const deshnPretty = deshn.includes('xn--') && punycode
                ? punycode.toUnicode(deshn)
                : deshn;
            for ( const type in typeBitOffsets ) {
                if ( typeBitOffsets[type] === undefined ) { continue; }
                const val = this.evaluateCell(srchn, deshn, type);
                if ( val === 0 ) { continue; }
                const action = intToActionMap.get(val);
                if ( action === undefined ) { continue; }
                out.push(`${srchnPretty} ${deshnPretty} ${type} ${action}`);
            }
        }
        return out;
    }

    toString() {
        return this.toArray().join('\n');
    }

    fromString(text, append) {
        const lineIter = new LineIterator(text);
        if ( append !== true ) { this.reset(); }
        while ( lineIter.eot() === false ) {
            this.addFromRuleParts(lineIter.next().trim().split(/\s+/));
        }
    }

    validateRuleParts(parts) {
        if ( parts.length < 4 ) { return; }

        // Ignore hostname-based switch rules
        if ( parts[0].endsWith(':') ) { return; }

        // Ignore URL-based rules
        if ( parts[1].includes('/') ) { return; }

        if ( typeBitOffsets[parts[2]] === undefined ) { return; }

        if ( nameToActionMap[parts[3]] === undefined ) { return; }

        // https://github.com/chrisaljoudi/uBlock/issues/840
        //   Discard invalid rules
        if ( parts[1] !== '*' && parts[2] !== '*' ) { return; }

        // Performance: avoid punycoding when only ASCII chars
        if ( punycode !== undefined ) {
            if ( reNotASCII.test(parts[0]) ) {
                parts[0] = punycode.toASCII(parts[0]);
            }
            if ( reNotASCII.test(parts[1]) ) {
                parts[1] = punycode.toASCII(parts[1]);
            }
        }

        // https://github.com/chrisaljoudi/uBlock/issues/1082
        //   Discard rules with invalid hostnames
        if (
            (parts[0] !== '*' && reBadHostname.test(parts[0])) ||
            (parts[1] !== '*' && reBadHostname.test(parts[1]))
        ) {
            return;
        }

        return parts;
    }

    addFromRuleParts(parts) {
        if ( this.validateRuleParts(parts) !== undefined ) {
            this.setCell(parts[0], parts[1], parts[2], nameToActionMap[parts[3]]);
            return true;
        }
        return false;
    }

    removeFromRuleParts(parts) {
        if ( this.validateRuleParts(parts) !== undefined ) {
            this.setCell(parts[0], parts[1], parts[2], 0);
            return true;
        }
        return false;
    }

    toSelfie() {
        return {
            magicId: this.magicId,
            rules: Array.from(this.rules)
        };
    }

    fromSelfie(selfie) {
        if ( selfie.magicId !== this.magicId ) { return false; }
        this.rules = new Map(selfie.rules);
        this.changed = true;
        return true;
    }
}

DynamicHostRuleFiltering.prototype.magicId = 1;

/******************************************************************************/

export default DynamicHostRuleFiltering;

/******************************************************************************/
