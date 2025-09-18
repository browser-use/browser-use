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

import { parseReplaceFn } from './parse-replace.js';
import { proxyApplyFn } from './proxy-apply.js';
import { registerScriptlet } from './base.js';
import { safeSelf } from './safe-self.js';
import { validateConstantFn } from './set-constant.js';

/**
 * @scriptlet trusted-replace-argument.js
 * 
 * @description
 * Replace an argument passed to a method. Requires a trusted source.
 * 
 * @param propChain
 * The property chain to the function which argument must be replaced when
 * called.
 * 
 * @param argposRaw
 * The zero-based position of the argument in the argument list. Use a negative
 * number for a position relative to the last argument. Use literal `this` to
 * replace the value used in `prototype`-based methods.
 * 
 * @param argraw
 * The replacement value, validated using the same heuristic as with the
 * `set-constant.js` scriptlet.
 * If the replacement value matches `json:...`, the value will be the
 * json-parsed string after `json:`.
 * If the replacement value matches `repl:/.../.../`, the target argument will
 * be replaced according the regex-replacement directive following `repl:`
 * 
 * @param [, condition, pattern]
 * Optional. The replacement will occur only when pattern matches the target
 * argument.
 * 
 * */

export function trustedReplaceArgument(
    propChain = '',
    argposRaw = '',
    argraw = ''
) {
    if ( propChain === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('trusted-replace-argument', propChain, argposRaw, argraw);
    const argoffset = parseInt(argposRaw, 10) || 0;
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 3);
    const replacer = argraw.startsWith('repl:/') &&
        parseReplaceFn(argraw.slice(5)) || undefined;
    const value = replacer === undefined &&
        validateConstantFn(true, argraw, extraArgs);
    const reCondition = extraArgs.condition
        ? safe.patternToRegex(extraArgs.condition)
        : /^/;
    const getArg = context => {
        if ( argposRaw === 'this' ) { return context.thisArg; }
        const { callArgs } = context;
        const argpos = argoffset >= 0 ? argoffset : callArgs.length - argoffset;
        if ( argpos < 0 || argpos >= callArgs.length ) { return; }
        context.private = { argpos };
        return callArgs[argpos];
    };
    const setArg = (context, value) => {
        if ( argposRaw === 'this' ) {
            if ( value !== context.thisArg ) {
                context.thisArg = value;
            }
        } else if ( context.private ) {
            context.callArgs[context.private.argpos] = value;
        }
    };
    proxyApplyFn(propChain, function(context) {
        if ( argposRaw === '' ) {
            safe.uboLog(logPrefix, `Arguments:\n${context.callArgs.join('\n')}`);
            return context.reflect();
        }
        const argBefore = getArg(context);
        if ( extraArgs.condition !== undefined ) {
            if ( safe.RegExp_test.call(reCondition, argBefore) === false ) {
                return context.reflect();
            }
        }
        const argAfter = replacer && typeof argBefore === 'string'
            ? argBefore.replace(replacer.re, replacer.replacement)
            : value;
        if ( argAfter !== argBefore ) {
            setArg(context, argAfter);
            safe.uboLog(logPrefix, `Replaced argument:\nBefore: ${JSON.stringify(argBefore)}\nAfter: ${argAfter}`);
        }
        return context.reflect();
    });
}
registerScriptlet(trustedReplaceArgument, {
    name: 'trusted-replace-argument.js',
    requiresTrust: true,
    dependencies: [
        parseReplaceFn,
        proxyApplyFn,
        safeSelf,
        validateConstantFn,
    ],
});
