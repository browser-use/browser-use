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

import { LineIterator } from './text-utils.js';
import { decomposeHostname } from './uri-utils.js';
import punycode from '../lib/punycode.js';

/******************************************************************************/

const decomposedSource = [];

// Object.create(null) is used below to eliminate worries about unexpected
// property names in prototype chain -- and this way we don't have to use
// Object.hasOwn() to avoid this.

const switchBitOffsets = Object.create(null);
Object.assign(switchBitOffsets, {
       'no-strict-blocking':  0,
                'no-popups':  2,
    'no-cosmetic-filtering':  4,
          'no-remote-fonts':  6,
           'no-large-media':  8,
           'no-csp-reports': 10,
             'no-scripting': 12,
});

const switchStateToNameMap = Object.create(null);
Object.assign(switchStateToNameMap, {
    '1': 'true',
    '2': 'false',
});

const nameToSwitchStateMap = Object.create(null);
Object.assign(nameToSwitchStateMap, {
     'true': 1,
    'false': 2,
       'on': 1,
      'off': 2,
});

/******************************************************************************/

// For performance purpose, as simple test as possible
const reNotASCII = /[^\x20-\x7F]/;

// http://tools.ietf.org/html/rfc5952
// 4.3: "MUST be represented in lowercase"
// Also: http://en.wikipedia.org/wiki/IPv6_address#Literal_IPv6_addresses_in_network_resource_identifiers

/******************************************************************************/

class DynamicSwitchRuleFiltering {
    constructor() {
        this.reset();
    }

    reset() {
        this.switches = new Map();
        this.n = '';
        this.z = '';
        this.r = 0;
        this.changed = true;
    }

    assign(from) {
        // Remove rules not in other
        for ( const hn of this.switches.keys() ) {
            if ( from.switches.has(hn) === false ) {
                this.switches.delete(hn);
                this.changed = true;
            }
        }
        // Add/change rules in other
        for ( const [hn, bits] of from.switches ) {
            if ( this.switches.get(hn) !== bits ) {
                this.switches.set(hn, bits);
                this.changed = true;
            }
        }
    }

    copyRules(from, srcHostname) {
        const thisBits = this.switches.get(srcHostname);
        const fromBits = from.switches.get(srcHostname);
        if ( fromBits !== thisBits ) {
            if ( fromBits !== undefined ) {
                this.switches.set(srcHostname, fromBits);
            } else {
                this.switches.delete(srcHostname);
            }
            this.changed = true;
        }
        return this.changed;
    }

    hasSameRules(other, srcHostname) {
        return this.switches.get(srcHostname) === other.switches.get(srcHostname);
    }

    toggle(switchName, hostname, newVal) {
        const bitOffset = switchBitOffsets[switchName];
        if ( bitOffset === undefined ) { return false; }
        if ( newVal === this.evaluate(switchName, hostname) ) { return false; }
        let bits = this.switches.get(hostname) || 0;
        bits &= ~(3 << bitOffset);
        bits |= newVal << bitOffset;
        if ( bits === 0 ) {
            this.switches.delete(hostname);
        } else {
            this.switches.set(hostname, bits);
        }
        this.changed = true;
        return true;
    }

    toggleOneZ(switchName, hostname, newState) {
        const bitOffset = switchBitOffsets[switchName];
        if ( bitOffset === undefined ) { return false; }
        let state = this.evaluateZ(switchName, hostname);
        if ( newState === state ) { return false; }
        if ( newState === undefined ) {
            newState = !state;
        }
        let bits = this.switches.get(hostname) || 0;
        bits &= ~(3 << bitOffset);
        if ( bits === 0 ) {
            this.switches.delete(hostname);
        } else {
            this.switches.set(hostname, bits);
        }
        state = this.evaluateZ(switchName, hostname);
        if ( state !== newState ) {
            this.switches.set(hostname, bits | ((newState ? 1 : 2) << bitOffset));
        }
        this.changed = true;
        return true;
    }

    toggleBranchZ(switchName, targetHostname, newState) {
        this.toggleOneZ(switchName, targetHostname, newState);

        // Turn off all descendant switches, they will inherit the state of the
        // branch's origin.
        const targetLen = targetHostname.length;
        for ( const hostname of this.switches.keys() ) {
            if ( hostname === targetHostname ) { continue; }
            if ( hostname.length <= targetLen ) { continue; }
            if ( hostname.endsWith(targetHostname) === false ) { continue; }
            if ( hostname.charAt(hostname.length - targetLen - 1) !== '.' ) {
                continue;
            }
            this.toggle(switchName, hostname, 0);
        }

        return this.changed;
    }

    toggleZ(switchName, hostname, deep, newState) {
        if ( deep === true ) {
            return this.toggleBranchZ(switchName, hostname, newState);
        }
        return this.toggleOneZ(switchName, hostname, newState);
    }

    // 0 = inherit from broader scope, up to default state
    // 1 = non-default state
    // 2 = forced default state (to override a broader non-default state)

    evaluate(switchName, hostname) {
        const bits = this.switches.get(hostname);
        if ( bits === undefined ) { return 0; }
        let bitOffset = switchBitOffsets[switchName];
        if ( bitOffset === undefined ) { return 0; }
        return (bits >>> bitOffset) & 3;
    }

    evaluateZ(switchName, hostname) {
        const bitOffset = switchBitOffsets[switchName];
        if ( bitOffset === undefined ) {
            this.r = 0;
            return false;
        }
        this.n = switchName;
        for ( const shn of decomposeHostname(hostname, decomposedSource) ) {
            let bits = this.switches.get(shn);
            if ( bits === undefined ) { continue; }
            bits = bits >>> bitOffset & 3;
            if ( bits === 0 ) { continue; }
            this.z = shn;
            this.r = bits;
            return bits === 1;
        }
        this.r = 0;
        return false;
    }

    toLogData() {
        return {
            source: 'switch',
            result: this.r,
            raw: `${this.n}: ${this.z} true`
        };
    }

    toArray() {
        const out = [];
        for ( const hostname of this.switches.keys() ) {
            const prettyHn = hostname.includes('xn--') && punycode
                ? punycode.toUnicode(hostname)
                : hostname;
            for ( const switchName in switchBitOffsets ) {
                if ( switchBitOffsets[switchName] === undefined ) { continue; }
                const val = this.evaluate(switchName, hostname);
                if ( val === 0 ) { continue; }
                out.push(`${switchName}: ${prettyHn} ${switchStateToNameMap[val]}`);
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
        if ( parts.length < 3 ) { return; }
        if ( parts[0].endsWith(':') === false ) { return; }
        if ( nameToSwitchStateMap[parts[2]] === undefined ) { return; }
        if ( reNotASCII.test(parts[1]) && punycode !== undefined ) {
            parts[1] = punycode.toASCII(parts[1]);
        }
        return parts;
    }

    addFromRuleParts(parts) {
        if ( this.validateRuleParts(parts) === undefined ) { return false; }
        const switchName = parts[0].slice(0, -1);
        if ( switchBitOffsets[switchName] === undefined ) { return false; }
        this.toggle(switchName, parts[1], nameToSwitchStateMap[parts[2]]);
        return true;
    }

    removeFromRuleParts(parts) {
        if ( this.validateRuleParts(parts) !== undefined ) {
            this.toggle(parts[0].slice(0, -1), parts[1], 0);
            return true;
        }
        return false;
    }
}

/******************************************************************************/

export default DynamicSwitchRuleFiltering;

/******************************************************************************/
