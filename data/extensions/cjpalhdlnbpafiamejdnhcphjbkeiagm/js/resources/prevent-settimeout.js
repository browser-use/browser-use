/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2019-present Raymond Hill

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

import { proxyApplyFn } from './proxy-apply.js';
import { registerScriptlet } from './base.js';
import { safeSelf } from './safe-self.js';

/******************************************************************************/

class RangeParser {
    constructor(s) {
        this.not = s.charAt(0) === '!';
        if ( this.not ) { s = s.slice(1); }
        if ( s === '' ) { return; }
        const pos = s.indexOf('-');
        if ( pos !== 0 ) {
            this.min = this.max = parseInt(s, 10) || 0;
        }
        if ( pos !== -1 ) {
            this.max = parseInt(s.slice(pos + 1), 10) || Number.MAX_SAFE_INTEGER;
        }
    }
    unbound() {
        return this.min === undefined && this.max === undefined;
    }
    test(v) {
        const n = Math.min(Math.max(Number(v) || 0, 0), Number.MAX_SAFE_INTEGER);
        if ( this.min === this.max ) {
            return (this.min === undefined || n === this.min) !== this.not;
        }
        if ( this.min === undefined ) {
            return (n <= this.max) !== this.not;
        }
        if ( this.max === undefined ) {
            return (n >= this.min) !== this.not;
        }
        return (n >= this.min && n <= this.max) !== this.not;
    }
}
registerScriptlet(RangeParser, {
    name: 'range-parser.fn',
});

/**
 * @scriptlet prevent-setTimeout
 * 
 * @description
 * Conditionally prevent execution of the callback function passed to native
 * setTimeout method. With no parameters, all calls to setTimeout will be
 * shown in the logger.
 * 
 * @param [needle]
 * A pattern to match against the stringified callback. The pattern can be a
 * plain string, or a regex. Prepend with `!` to reverse the match condition.
 * 
 * @param [delay]
 * A value to match against the delay. Can be a single value for exact match,
 * or a range:
 * - `min-max`: matches if delay >= min and delay <= max
 * - `min-`: matches if delay >= min
 * - `-max`: matches if delay <= max
 * No delay means to match any delay value.
 * Prepend with `!` to reverse the match condition.
 * 
 * */

export function preventSetTimeout(
    needleRaw = '',
    delayRaw = ''
) {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('prevent-setTimeout', needleRaw, delayRaw);
    const needleNot = needleRaw.charAt(0) === '!';
    const reNeedle = safe.patternToRegex(needleNot ? needleRaw.slice(1) : needleRaw);
    const range = new RangeParser(delayRaw);
    proxyApplyFn('setTimeout', function(context) {
        const { callArgs } = context;
        const a = callArgs[0] instanceof Function
            ? safe.String(safe.Function_toString(callArgs[0]))
            : safe.String(callArgs[0]);
        const b = callArgs[1];
        if ( needleRaw === '' && range.unbound() ) {
            safe.uboLog(logPrefix, `Called:\n${a}\n${b}`);
            return context.reflect();
        }
        if ( reNeedle.test(a) !== needleNot && range.test(b) ) {
            callArgs[0] = function(){};
            safe.uboLog(logPrefix, `Prevented:\n${a}\n${b}`);
        }
        return context.reflect();
    });
}
registerScriptlet(preventSetTimeout, {
    name: 'prevent-setTimeout.js',
    aliases: [
        'no-setTimeout-if.js',
        'nostif.js',
        'setTimeout-defuser.js',
    ],
    dependencies: [
        proxyApplyFn,
        RangeParser,
        safeSelf,
    ],
});

/**
 * @scriptlet prevent-setInterval
 * 
 * @description
 * Conditionally prevent execution of the callback function passed to native
 * setInterval method. With no parameters, all calls to setInterval will be
 * shown in the logger.
 * 
 * @param [needle]
 * A pattern to match against the stringified callback. The pattern can be a
 * plain string, or a regex. Prepend with `!` to reverse the match condition.
 * No pattern means to match anything.
 * 
 * @param [delay]
 * A value to match against the delay. Can be a single value for exact match,
 * or a range:
 * - `min-max`: matches if delay >= min and delay <= max
 * - `min-`: matches if delay >= min
 * - `-max`: matches if delay <= max
 * No delay means to match any delay value.
 * Prepend with `!` to reverse the match condition.
 * 
 * */

export function preventSetInterval(
    needleRaw = '',
    delayRaw = ''
) {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('prevent-setInterval', needleRaw, delayRaw);
    const needleNot = needleRaw.charAt(0) === '!';
    const reNeedle = safe.patternToRegex(needleNot ? needleRaw.slice(1) : needleRaw);
    const range = new RangeParser(delayRaw);
    proxyApplyFn('setInterval', function(context) {
        const { callArgs } = context;
        const a = callArgs[0] instanceof Function
            ? safe.String(safe.Function_toString(callArgs[0]))
            : safe.String(callArgs[0]);
        const b = callArgs[1];
        if ( needleRaw === '' && range.unbound() ) {
            safe.uboLog(logPrefix, `Called:\n${a}\n${b}`);
            return context.reflect();
        }
        if ( reNeedle.test(a) !== needleNot && range.test(b) ) {
            callArgs[0] = function(){};
            safe.uboLog(logPrefix, `Prevented:\n${a}\n${b}`);
        }
        return context.reflect();
    });
}
registerScriptlet(preventSetInterval, {
    name: 'prevent-setInterval.js',
    aliases: [
        'no-setInterval-if.js',
        'nosiif.js',
        'setInterval-defuser.js',
    ],
    dependencies: [
        proxyApplyFn,
        RangeParser,
        safeSelf,
    ],
});

/**
 * @scriptlet prevent-requestAnimationFrame
 * 
 * @description
 * Conditionally prevent execution of the callback function passed to native
 * requestAnimationFrame method. With no parameters, all calls to
 * requestAnimationFrame will be shown in the logger.
 * 
 * @param [needle]
 * A pattern to match against the stringified callback. The pattern can be a
 * plain string, or a regex.
 * Prepend with `!` to reverse the match condition.
 * 
 * */

export function preventRequestAnimationFrame(
    needleRaw = ''
) {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('prevent-requestAnimationFrame', needleRaw);
    const needleNot = needleRaw.charAt(0) === '!';
    const reNeedle = safe.patternToRegex(needleNot ? needleRaw.slice(1) : needleRaw);
    proxyApplyFn('requestAnimationFrame', function(context) {
        const { callArgs } = context;
        const a = callArgs[0] instanceof Function
            ? safe.String(safe.Function_toString(callArgs[0]))
            : safe.String(callArgs[0]);
        if ( needleRaw === '' ) {
            safe.uboLog(logPrefix, `Called:\n${a}`);
        } else if ( reNeedle.test(a) !== needleNot ) {
            callArgs[0] = function(){};
            safe.uboLog(logPrefix, `Prevented:\n${a}`);
        }
        return context.reflect();
    });
}
registerScriptlet(preventRequestAnimationFrame, {
    name: 'prevent-requestAnimationFrame.js',
    aliases: [
        'no-requestAnimationFrame-if.js',
        'norafif.js',
    ],
    dependencies: [
        proxyApplyFn,
        safeSelf,
    ],
});
