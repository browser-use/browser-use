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

import { generateContentFn } from './utils.js';
import { proxyApplyFn } from './proxy-apply.js';
import { registerScriptlet } from './base.js';
import { safeSelf } from './safe-self.js';

/******************************************************************************/

function preventFetchFn(
    trusted = false,
    propsToMatch = '',
    responseBody = '',
    responseType = ''
) {
    const safe = safeSelf();
    const setTimeout = self.setTimeout;
    const scriptletName = `${trusted ? 'trusted-' : ''}prevent-fetch`;
    const logPrefix = safe.makeLogPrefix(
        scriptletName,
        propsToMatch,
        responseBody,
        responseType
    );
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 4);
    const needles = [];
    for ( const condition of safe.String_split.call(propsToMatch, /\s+/) ) {
        if ( condition === '' ) { continue; }
        const pos = condition.indexOf(':');
        let key, value;
        if ( pos !== -1 ) {
            key = condition.slice(0, pos);
            value = condition.slice(pos + 1);
        } else {
            key = 'url';
            value = condition;
        }
        needles.push({ key, pattern: safe.initPattern(value, { canNegate: true }) });
    }
    const validResponseProps = {
        ok: [ false, true ],
        statusText: [ '', 'Not Found' ],
        type: [ 'basic', 'cors', 'default', 'error', 'opaque' ],
    };
    const responseProps = {
        statusText: { value: 'OK' },
    };
    if ( /^\{.*\}$/.test(responseType) ) {
        try {
            Object.entries(JSON.parse(responseType)).forEach(([ p, v ]) => {
                if ( validResponseProps[p] === undefined ) { return; }
                if ( validResponseProps[p].includes(v) === false ) { return; }
                responseProps[p] = { value: v };
            });
        }
        catch { }
    } else if ( responseType !== '' ) {
        if ( validResponseProps.type.includes(responseType) ) {
            responseProps.type = { value: responseType };
        }
    }
    proxyApplyFn('fetch', function fetch(context) {
        const { callArgs } = context;
        const details = callArgs[0] instanceof self.Request
            ? callArgs[0]
            : Object.assign({ url: callArgs[0] }, callArgs[1]);
        let proceed = true;
        try {
            const props = new Map();
            for ( const prop in details ) {
                let v = details[prop];
                if ( typeof v !== 'string' ) {
                    try { v = safe.JSON_stringify(v); }
                    catch { }
                }
                if ( typeof v !== 'string' ) { continue; }
                props.set(prop, v);
            }
            if ( safe.logLevel > 1 || propsToMatch === '' && responseBody === '' ) {
                const out = Array.from(props).map(a => `${a[0]}:${a[1]}`);
                safe.uboLog(logPrefix, `Called: ${out.join('\n')}`);
            }
            if ( propsToMatch === '' && responseBody === '' ) {
                return context.reflect();
            }
            proceed = needles.length === 0;
            for ( const { key, pattern } of needles ) {
                if (
                    pattern.expect && props.has(key) === false ||
                    safe.testPattern(pattern, props.get(key)) === false
                ) {
                    proceed = true;
                    break;
                }
            }
        } catch {
        }
        if ( proceed ) {
            return context.reflect();
        }
        return Promise.resolve(generateContentFn(trusted, responseBody)).then(text => {
            safe.uboLog(logPrefix, `Prevented with response "${text}"`);
            const response = new Response(text, {
                headers: {
                    'Content-Length': text.length,
                }
            });
            const props = Object.assign(
                { url: { value: details.url } },
                responseProps
            );
            safe.Object_defineProperties(response, props);
            if ( extraArgs.throttle ) {
                return new Promise(resolve => {
                    setTimeout(( ) => { resolve(response); }, extraArgs.throttle);
                });
            }
            return response;
        });
    });
}
registerScriptlet(preventFetchFn, {
    name: 'prevent-fetch.fn',
    dependencies: [
        generateContentFn,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet prevent-fetch
 * 
 * @description
 * Prevent a fetch() call from making a network request to a remote server.
 * 
 * @param propsToMatch
 * The fetch arguments to match for the prevention to be triggered. The
 * untrusted flavor limits the realm of response to return to safe values.
 * 
 * @param [responseBody]
 * Optional. The reponse to return when the prevention occurs.
 * 
 * @param [responseType]
 * Optional. The response type to use when emitting a dummy response as a
 * result of the prevention.
 * 
 * @param [...varargs]
 * ["throttle", n]: the time to wait in ms before returning a result.
 *
 * */

function preventFetch(...args) {
    preventFetchFn(false, ...args);
}
registerScriptlet(preventFetch, {
    name: 'prevent-fetch.js',
    aliases: [
        'no-fetch-if.js',
    ],
    dependencies: [
        preventFetchFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-prevent-fetch
 * 
 * @description
 * Prevent a fetch() call from making a network request to a remote server.
 * 
 * @param propsToMatch
 * The fetch arguments to match for the prevention to be triggered.
 * 
 * @param [responseBody]
 * Optional. The reponse to return when the prevention occurs. The trusted
 * flavor allows to return any response.
 * 
 * @param [responseType]
 * Optional. The response type to use when emitting a dummy response as a
 * result of the prevention.
 * 
 * @param [...varargs]
 * ["throttle", n]: the time to wait in ms before returning a result.
 *
 * */

function trustedPreventFetch(...args) {
    preventFetchFn(true, ...args);
}
registerScriptlet(trustedPreventFetch, {
    name: 'trusted-prevent-fetch.js',
    requiresTrust: true,
    dependencies: [
        preventFetchFn,
    ],
});

/******************************************************************************/
