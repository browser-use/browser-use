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

import {
    matchObjectPropertiesFn,
    parsePropertiesToMatchFn,
} from './utils.js';

import { JSONPath } from './shared.js';
import { proxyApplyFn } from './proxy-apply.js';
import { registerScriptlet } from './base.js';
import { safeSelf } from './safe-self.js';

/******************************************************************************/
/******************************************************************************/

function editOutboundObjectFn(
    trusted = false,
    propChain = '',
    jsonq = '',
) {
    if ( propChain === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}edit-outbound-object`,
        propChain,
        jsonq
    );
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    proxyApplyFn(propChain, function(context) {
        const obj = context.reflect();
        const objAfter = jsonp.apply(obj);
        if ( objAfter === undefined ) { return obj; }
        safe.uboLog(logPrefix, 'Edited');
        if ( safe.logLevel > 1 ) {
            safe.uboLog(logPrefix, `After edit:\n${safe.JSON_stringify(objAfter, null, 2)}`);
        }
        return objAfter;
    });
}
registerScriptlet(editOutboundObjectFn, {
    name: 'edit-outbound-object.fn',
    dependencies: [
        JSONPath,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet edit-outbound-object-.js
 * 
 * @description
 * Prune properties from an object returned by a specific method.
 * Properties can only be removed.
 * 
 * @param propChain
 * Property chain of the method to trap.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function editOutboundObject(propChain = '', jsonq = '') {
    editOutboundObjectFn(false, propChain, jsonq);
}
registerScriptlet(editOutboundObject, {
    name: 'edit-outbound-object.js',
    dependencies: [
        editOutboundObjectFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-edit-outbound-object.js
 * 
 * @description
 * Edit properties of an object returned by a specific method.
 * Properties can be assigned new values.
 * 
  * @param propChain
 * Property chain of the method to trap.
 * 
* @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function trustedEditOutboundObject(propChain = '', jsonq = '') {
    editOutboundObjectFn(true, propChain, jsonq);
}
registerScriptlet(trustedEditOutboundObject, {
    name: 'trusted-edit-outbound-object.js',
    requiresTrust: true,
    dependencies: [
        editOutboundObjectFn,
    ],
});

/******************************************************************************/
/******************************************************************************/
/**
 * @scriptlet json-edit.js
 * 
 * @description
 * Edit object generated through JSON.parse().
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function jsonEdit(jsonq = '') {
    editOutboundObjectFn(false, 'JSON.parse', jsonq);
}
registerScriptlet(jsonEdit, {
    name: 'json-edit.js',
    dependencies: [
        editOutboundObjectFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-json-edit.js
 * 
 * @description
 * Edit object generated through JSON.parse().
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function trustedJsonEdit(jsonq = '') {
    editOutboundObjectFn(true, 'JSON.parse', jsonq);
}
registerScriptlet(trustedJsonEdit, {
    name: 'trusted-json-edit.js',
    requiresTrust: true,
    dependencies: [
        editOutboundObjectFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function editInboundObjectFn(
    trusted = false,
    propChain = '',
    argPosRaw = '',
    jsonq = '',
) {
    if ( propChain === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}edit-inbound-object`,
        propChain,
        jsonq
    );
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const argPos = parseInt(argPosRaw, 10);
    if ( isNaN(argPos) ) { return; }
    const getArgPos = args => {
        if ( argPos >= 0 ) {
            if ( args.length <= argPos ) { return; }
            return argPos;
        }
        if ( args.length < -argPos ) { return; }
        return args.length + argPos;
    };
    const editObj = obj => {
        let clone;
        try {
            clone = safe.JSON_parse(safe.JSON_stringify(obj));
        } catch {
        }
        if ( typeof clone !== 'object' || clone === null ) { return; }
        const objAfter = jsonp.apply(clone);
        if ( objAfter === undefined ) { return; }
        safe.uboLog(logPrefix, 'Edited');
        if ( safe.logLevel > 1 ) {
            safe.uboLog(logPrefix, `After edit:\n${safe.JSON_stringify(objAfter, null, 2)}`);
        }
        return objAfter;
    };
    proxyApplyFn(propChain, function(context) {
        const i = getArgPos(context.args);
        if ( i !== undefined ) {
            const obj = editObj(context.args[i]);
            if ( obj ) {
                context.args[i] = obj;
            }
        }
        return context.reflect();
    });
}
registerScriptlet(editInboundObjectFn, {
    name: 'edit-inbound-object.fn',
    dependencies: [
        JSONPath,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet edit-inbound-object.js
 * 
 * @description
 * Prune properties from an object passed as argument to a specific method.
 * Properties can only be removed.
 * 
 * @param propChain
 * Property chain of the method to trap.
 * 
 * @param argPos
 * 0-based position of the argument. Use negative integer for position relative
 * to the end.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function editInboundObject(propChain = '', argPos = '', jsonq = '') {
    editInboundObjectFn(false, propChain, argPos, jsonq);
}
registerScriptlet(editInboundObject, {
    name: 'edit-inbound-object.js',
    dependencies: [
        editInboundObjectFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-edit-inbound-object.js
 * 
 * @description
 * Edit properties of an object passed as argument to a specific method.
 * Properties can be assigned new values.
 * 
 * @param propChain
 * Property chain of the method to trap.
 * 
 * @param argPos
 * 0-based position of the argument. Use negative integer for position relative
 * to the end.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * */

function trustedEditInboundObject(propChain = '', argPos = '', jsonq = '') {
    editInboundObjectFn(true, propChain, argPos, jsonq);
}
registerScriptlet(trustedEditInboundObject, {
    name: 'trusted-edit-inbound-object.js',
    requiresTrust: true,
    dependencies: [
        editInboundObjectFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonEditXhrResponseFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}json-edit-xhr-response`,
        jsonq
    );
    const xhrInstances = new WeakMap();
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    self.XMLHttpRequest = class extends self.XMLHttpRequest {
        open(method, url, ...args) {
            const xhrDetails = { method, url };
            const matched = propNeedles.size === 0 ||
                matchObjectPropertiesFn(propNeedles, xhrDetails);
            if ( matched ) {
                if ( safe.logLevel > 1 && Array.isArray(matched) ) {
                    safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
                }
                xhrInstances.set(this, xhrDetails);
            }
            return super.open(method, url, ...args);
        }
        get response() {
            const innerResponse = super.response;
            const xhrDetails = xhrInstances.get(this);
            if ( xhrDetails === undefined ) { return innerResponse; }
            const responseLength = typeof innerResponse === 'string'
                ? innerResponse.length
                : undefined;
            if ( xhrDetails.lastResponseLength !== responseLength ) {
                xhrDetails.response = undefined;
                xhrDetails.lastResponseLength = responseLength;
            }
            if ( xhrDetails.response !== undefined ) {
                return xhrDetails.response;
            }
            let obj;
            if ( typeof innerResponse === 'object' ) {
                obj = innerResponse;
            } else if ( typeof innerResponse === 'string' ) {
                try { obj = safe.JSON_parse(innerResponse); } catch { }
            }
            if ( typeof obj !== 'object' || obj === null ) {
                return (xhrDetails.response = innerResponse);
            }
            const objAfter = jsonp.apply(obj);
            if ( objAfter === undefined ) {
                return (xhrDetails.response = innerResponse);
            }
            safe.uboLog(logPrefix, 'Edited');
            const outerResponse = typeof innerResponse === 'string'
                ? JSONPath.toJSON(objAfter, safe.JSON_stringify)
                : objAfter;
            return (xhrDetails.response = outerResponse);
        }
        get responseText() {
            const response = this.response;
            return typeof response !== 'string'
                ? super.responseText
                : response;
        }
    };
}
registerScriptlet(jsonEditXhrResponseFn, {
    name: 'json-edit-xhr-response.fn',
    dependencies: [
        JSONPath,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet json-edit-xhr-response.js
 * 
 * @description
 * Edit the object fetched through a XHR instance.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function jsonEditXhrResponse(jsonq = '', ...args) {
    jsonEditXhrResponseFn(false, jsonq, ...args);
}
registerScriptlet(jsonEditXhrResponse, {
    name: 'json-edit-xhr-response.js',
    dependencies: [
        jsonEditXhrResponseFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-json-edit-xhr-response.js
 * 
 * @description
 * Edit the object fetched through a XHR instance.
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function trustedJsonEditXhrResponse(jsonq = '', ...args) {
    jsonEditXhrResponseFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonEditXhrResponse, {
    name: 'trusted-json-edit-xhr-response.js',
    requiresTrust: true,
    dependencies: [
        jsonEditXhrResponseFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonEditXhrRequestFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}json-edit-xhr-request`,
        jsonq
    );
    const xhrInstances = new WeakMap();
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    self.XMLHttpRequest = class extends self.XMLHttpRequest {
        open(method, url, ...args) {
            const xhrDetails = { method, url };
            const matched = propNeedles.size === 0 ||
                matchObjectPropertiesFn(propNeedles, xhrDetails);
            if ( matched ) {
                if ( safe.logLevel > 1 && Array.isArray(matched) ) {
                    safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
                }
                xhrInstances.set(this, xhrDetails);
            }
            return super.open(method, url, ...args);
        }
        send(body) {
            const xhrDetails = xhrInstances.get(this);
            if ( xhrDetails ) {
                body = this.#filterBody(body) || body;
            }
            super.send(body);
        }
        #filterBody(body) {
            if ( typeof body !== 'string' ) { return; }
            let data;
            try { data = safe.JSON_parse(body); }
            catch { }
            if ( data instanceof Object === false ) { return; }
            const objAfter = jsonp.apply(data);
            if ( objAfter === undefined ) { return; }
            body = safe.JSON_stringify(objAfter);
            safe.uboLog(logPrefix, 'Edited');
            if ( safe.logLevel > 1 ) {
                safe.uboLog(logPrefix, `After edit:\n${body}`);
            }
            return body;
        }
    };
}
registerScriptlet(jsonEditXhrRequestFn, {
    name: 'json-edit-xhr-request.fn',
    dependencies: [
        JSONPath,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet json-edit-xhr-request.js
 * 
 * @description
 * Edit the object sent as the body in a XHR instance.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function jsonEditXhrRequest(jsonq = '', ...args) {
    jsonEditXhrRequestFn(false, jsonq, ...args);
}
registerScriptlet(jsonEditXhrRequest, {
    name: 'json-edit-xhr-request.js',
    dependencies: [
        jsonEditXhrRequestFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-json-edit-xhr-request.js
 * 
 * @description
 * Edit the object sent as the body in a XHR instance.
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function trustedJsonEditXhrRequest(jsonq = '', ...args) {
    jsonEditXhrRequestFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonEditXhrRequest, {
    name: 'trusted-json-edit-xhr-request.js',
    requiresTrust: true,
    dependencies: [
        jsonEditXhrRequestFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonEditFetchResponseFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}json-edit-fetch-response`,
        jsonq
    );
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    proxyApplyFn('fetch', function(context) {
        const args = context.callArgs;
        const fetchPromise = context.reflect();
        if ( propNeedles.size !== 0 ) {
            const objs = [ args[0] instanceof Object ? args[0] : { url: args[0] } ];
            if ( objs[0] instanceof Request ) {
                try {
                    objs[0] = safe.Request_clone.call(objs[0]);
                } catch(ex) {
                    safe.uboErr(logPrefix, 'Error:', ex);
                }
            }
            if ( args[1] instanceof Object ) {
                objs.push(args[1]);
            }
            const matched = matchObjectPropertiesFn(propNeedles, ...objs);
            if ( matched === undefined ) { return fetchPromise; }
            if ( safe.logLevel > 1 ) {
                safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
            }
        }
        return fetchPromise.then(responseBefore => {
            const response = responseBefore.clone();
            return response.json().then(obj => {
                if ( typeof obj !== 'object' ) { return responseBefore; }
                const objAfter = jsonp.apply(obj);
                if ( objAfter === undefined ) { return responseBefore; }
                safe.uboLog(logPrefix, 'Edited');
                const responseAfter = Response.json(objAfter, {
                    status: responseBefore.status,
                    statusText: responseBefore.statusText,
                    headers: responseBefore.headers,
                });
                Object.defineProperties(responseAfter, {
                    ok: { value: responseBefore.ok },
                    redirected: { value: responseBefore.redirected },
                    type: { value: responseBefore.type },
                    url: { value: responseBefore.url },
                });
                return responseAfter;
            }).catch(reason => {
                safe.uboErr(logPrefix, 'Error:', reason);
                return responseBefore;
            });
        }).catch(reason => {
            safe.uboErr(logPrefix, 'Error:', reason);
            return fetchPromise;
        });
    });
}
registerScriptlet(jsonEditFetchResponseFn, {
    name: 'json-edit-fetch-response.fn',
    dependencies: [
        JSONPath,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet json-edit-fetch-response.js
 * 
 * @description
 * Edit the object fetched through the fetch API.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function jsonEditFetchResponse(jsonq = '', ...args) {
    jsonEditFetchResponseFn(false, jsonq, ...args);
}
registerScriptlet(jsonEditFetchResponse, {
    name: 'json-edit-fetch-response.js',
    dependencies: [
        jsonEditFetchResponseFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-json-edit-fetch-response.js
 * 
 * @description
 * Edit the object fetched through the fetch API. The trusted version allows
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function trustedJsonEditFetchResponse(jsonq = '', ...args) {
    jsonEditFetchResponseFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonEditFetchResponse, {
    name: 'trusted-json-edit-fetch-response.js',
    requiresTrust: true,
    dependencies: [
        jsonEditFetchResponseFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonEditFetchRequestFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}json-edit-fetch-request`,
        jsonq
    );
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    const filterBody = body => {
        if ( typeof body !== 'string' ) { return; }
        let data;
        try { data = safe.JSON_parse(body); }
        catch { }
        if ( data instanceof Object === false ) { return; }
        const objAfter = jsonp.apply(data);
        if ( objAfter === undefined ) { return; }
        return safe.JSON_stringify(objAfter);
    }
    const proxyHandler = context => {
        const args = context.callArgs;
        const [ resource, options ] = args;
        const bodyBefore = options?.body;
        if ( Boolean(bodyBefore) === false ) { return context.reflect(); }
        const bodyAfter = filterBody(bodyBefore);
        if ( bodyAfter === undefined || bodyAfter === bodyBefore ) {
            return context.reflect();
        }
        if ( propNeedles.size !== 0 ) {
            const objs = [
                resource instanceof Object ? resource : { url: `${resource}` }
            ];
            if ( objs[0] instanceof Request ) {
                try {
                    objs[0] = safe.Request_clone.call(objs[0]);
                } catch(ex) {
                    safe.uboErr(logPrefix, 'Error:', ex);
                }
            }
            const matched = matchObjectPropertiesFn(propNeedles, ...objs);
            if ( matched === undefined ) { return context.reflect(); }
            if ( safe.logLevel > 1 ) {
                safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
            }
        }
        safe.uboLog(logPrefix, 'Edited');
        if ( safe.logLevel > 1 ) {
            safe.uboLog(logPrefix, `After edit:\n${bodyAfter}`);
        }
        options.body = bodyAfter;
        return context.reflect();
    };
    proxyApplyFn('fetch', proxyHandler);
    proxyApplyFn('Request', proxyHandler);
}
registerScriptlet(jsonEditFetchRequestFn, {
    name: 'json-edit-fetch-request.fn',
    dependencies: [
        JSONPath,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet json-edit-fetch-request.js
 * 
 * @description
 * Edit the request body sent through the fetch API.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when fetch() is called.
 * 
 * */

function jsonEditFetchRequest(jsonq = '', ...args) {
    jsonEditFetchRequestFn(false, jsonq, ...args);
}
registerScriptlet(jsonEditFetchRequest, {
    name: 'json-edit-fetch-request.js',
    dependencies: [
        jsonEditFetchRequestFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-json-edit-fetch-request.js
 * 
 * @description
 * Edit the request body sent through the fetch API.
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when fetch() is called.
 * 
 * */

function trustedJsonEditFetchRequest(jsonq = '', ...args) {
    jsonEditFetchRequestFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonEditFetchRequest, {
    name: 'trusted-json-edit-fetch-request.js',
    requiresTrust: true,
    dependencies: [
        jsonEditFetchRequestFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonlEditFn(jsonp, text = '') {
    const safe = safeSelf();
    const lineSeparator = /\r?\n/.exec(text)?.[0] || '\n';
    const linesBefore = text.split('\n');
    const linesAfter = [];
    for ( const lineBefore of linesBefore ) {
        let obj;
        try { obj = safe.JSON_parse(lineBefore); } catch { }
        if ( typeof obj !== 'object' || obj === null ) {
            linesAfter.push(lineBefore);
            continue;
        }
        const objAfter = jsonp.apply(obj);
        if ( objAfter === undefined ) {
            linesAfter.push(lineBefore);
            continue;
        }
        const lineAfter = safe.JSON_stringify(objAfter);
        linesAfter.push(lineAfter);
    }
    return linesAfter.join(lineSeparator);
}
registerScriptlet(jsonlEditFn, {
    name: 'jsonl-edit.fn',
    dependencies: [
        JSONPath,
        safeSelf,
    ],
});

/******************************************************************************/

function jsonlEditXhrResponseFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}jsonl-edit-xhr-response`,
        jsonq
    );
    const xhrInstances = new WeakMap();
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    self.XMLHttpRequest = class extends self.XMLHttpRequest {
        open(method, url, ...args) {
            const xhrDetails = { method, url };
            const matched = propNeedles.size === 0 ||
                matchObjectPropertiesFn(propNeedles, xhrDetails);
            if ( matched ) {
                if ( safe.logLevel > 1 && Array.isArray(matched) ) {
                    safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
                }
                xhrInstances.set(this, xhrDetails);
            }
            return super.open(method, url, ...args);
        }
        get response() {
            const innerResponse = super.response;
            const xhrDetails = xhrInstances.get(this);
            if ( xhrDetails === undefined ) {
                return innerResponse;
            }
            const responseLength = typeof innerResponse === 'string'
                ? innerResponse.length
                : undefined;
            if ( xhrDetails.lastResponseLength !== responseLength ) {
                xhrDetails.response = undefined;
                xhrDetails.lastResponseLength = responseLength;
            }
            if ( xhrDetails.response !== undefined ) {
                return xhrDetails.response;
            }
            if ( typeof innerResponse !== 'string' ) {
                return (xhrDetails.response = innerResponse);
            }
            const outerResponse = jsonlEditFn(jsonp, innerResponse);
            if ( outerResponse !== innerResponse ) {
                safe.uboLog(logPrefix, 'Pruned');
            }
            return (xhrDetails.response = outerResponse);
        }
        get responseText() {
            const response = this.response;
            return typeof response !== 'string'
                ? super.responseText
                : response;
        }
    };
}
registerScriptlet(jsonlEditXhrResponseFn, {
    name: 'jsonl-edit-xhr-response.fn',
    dependencies: [
        JSONPath,
        jsonlEditFn,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet jsonl-edit-xhr-response.js
 * 
 * @description
 * Edit the objects found in a JSONL resource fetched through a XHR instance.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function jsonlEditXhrResponse(jsonq = '', ...args) {
    jsonlEditXhrResponseFn(false, jsonq, ...args);
}
registerScriptlet(jsonlEditXhrResponse, {
    name: 'jsonl-edit-xhr-response.js',
    dependencies: [
        jsonlEditXhrResponseFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-jsonl-edit-xhr-response.js
 * 
 * @description
 * Edit the objects found in a JSONL resource fetched through a XHR instance.
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function trustedJsonlEditXhrResponse(jsonq = '', ...args) {
    jsonlEditXhrResponseFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonlEditXhrResponse, {
    name: 'trusted-jsonl-edit-xhr-response.js',
    requiresTrust: true,
    dependencies: [
        jsonlEditXhrResponseFn,
    ],
});

/******************************************************************************/
/******************************************************************************/

function jsonlEditFetchResponseFn(trusted, jsonq = '') {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix(
        `${trusted ? 'trusted-' : ''}jsonl-edit-fetch-response`,
        jsonq
    );
    const jsonp = JSONPath.create(jsonq);
    if ( jsonp.valid === false || jsonp.value !== undefined && trusted !== true ) {
        return safe.uboLog(logPrefix, 'Bad JSONPath query');
    }
    const extraArgs = safe.getExtraArgs(Array.from(arguments), 2);
    const propNeedles = parsePropertiesToMatchFn(extraArgs.propsToMatch, 'url');
    const logall = jsonq === '';
    proxyApplyFn('fetch', function(context) {
        const args = context.callArgs;
        const fetchPromise = context.reflect();
        if ( propNeedles.size !== 0 ) {
            const objs = [ args[0] instanceof Object ? args[0] : { url: args[0] } ];
            if ( objs[0] instanceof Request ) {
                try {
                    objs[0] = safe.Request_clone.call(objs[0]);
                } catch(ex) {
                    safe.uboErr(logPrefix, 'Error:', ex);
                }
            }
            if ( args[1] instanceof Object ) {
                objs.push(args[1]);
            }
            const matched = matchObjectPropertiesFn(propNeedles, ...objs);
            if ( matched === undefined ) { return fetchPromise; }
            if ( safe.logLevel > 1 ) {
                safe.uboLog(logPrefix, `Matched "propsToMatch":\n\t${matched.join('\n\t')}`);
            }
        }
        return fetchPromise.then(responseBefore => {
            const response = responseBefore.clone();
            return response.text().then(textBefore => {
                if ( typeof textBefore !== 'string' ) { return textBefore; }
                if ( logall ) {
                    safe.uboLog(logPrefix, textBefore);
                    return responseBefore;
                }
                const textAfter = jsonlEditFn(jsonp, textBefore);
                if ( textAfter === textBefore ) { return responseBefore; }
                safe.uboLog(logPrefix, 'Pruned');
                const responseAfter = new Response(textAfter, {
                    status: responseBefore.status,
                    statusText: responseBefore.statusText,
                    headers: responseBefore.headers,
                });
                Object.defineProperties(responseAfter, {
                    ok: { value: responseBefore.ok },
                    redirected: { value: responseBefore.redirected },
                    type: { value: responseBefore.type },
                    url: { value: responseBefore.url },
                });
                return responseAfter;
            }).catch(reason => {
                safe.uboErr(logPrefix, 'Error:', reason);
                return responseBefore;
            });
        }).catch(reason => {
            safe.uboErr(logPrefix, 'Error:', reason);
            return fetchPromise;
        });
    });
}
registerScriptlet(jsonlEditFetchResponseFn, {
    name: 'jsonl-edit-fetch-response.fn',
    dependencies: [
        JSONPath,
        jsonlEditFn,
        matchObjectPropertiesFn,
        parsePropertiesToMatchFn,
        proxyApplyFn,
        safeSelf,
    ],
});

/******************************************************************************/
/**
 * @scriptlet jsonl-edit-fetch-response.js
 * 
 * @description
 * Edit the objects found in a JSONL resource fetched through the fetch API.
 * Properties can only be removed.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function jsonlEditFetchResponse(jsonq = '', ...args) {
    jsonlEditFetchResponseFn(false, jsonq, ...args);
}
registerScriptlet(jsonlEditFetchResponse, {
    name: 'jsonl-edit-fetch-response.js',
    dependencies: [
        jsonlEditFetchResponseFn,
    ],
});

/******************************************************************************/
/**
 * @scriptlet trusted-jsonl-edit-fetch-response.js
 * 
 * @description
 * Edit the objects found in a JSONL resource fetched through the fetch API.
 * Properties can be assigned new values.
 * 
 * @param jsonq
 * A uBO-flavored JSONPath query.
 * 
 * @param [propsToMatch, value]
 * An optional vararg detailing the arguments to match when xhr.open() is
 * called.
 * 
 * */

function trustedJsonlEditFetchResponse(jsonq = '', ...args) {
    jsonlEditFetchResponseFn(true, jsonq, ...args);
}
registerScriptlet(trustedJsonlEditFetchResponse, {
    name: 'trusted-jsonl-edit-fetch-response.js',
    requiresTrust: true,
    dependencies: [
        jsonlEditFetchResponseFn,
    ],
});

/******************************************************************************/
