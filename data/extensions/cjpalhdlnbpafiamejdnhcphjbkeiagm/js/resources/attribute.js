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

import { registerScriptlet } from './base.js';
import { runAt } from './run-at.js';
import { safeSelf } from './safe-self.js';

/******************************************************************************/

export function setAttrFn(
    trusted = false,
    logPrefix,
    selector = '',
    attr = '',
    value = ''
) {
    if ( selector === '' ) { return; }
    if ( attr === '' ) { return; }

    const safe = safeSelf();
    const copyFrom = trusted === false && /^\[.+\]$/.test(value)
        ? value.slice(1, -1)
        : '';

    const extractValue = elem => copyFrom !== ''
        ? elem.getAttribute(copyFrom) || ''
        : value;

    const applySetAttr = ( ) => {
        let elems;
        try {
            elems = document.querySelectorAll(selector);
        } catch {
            return false;
        }
        for ( const elem of elems ) {
            const before = elem.getAttribute(attr);
            const after = extractValue(elem);
            if ( after === before ) { continue; }
            if ( after !== '' && /^on/i.test(attr) ) {
                if ( attr.toLowerCase() in elem ) { continue; }
            }
            elem.setAttribute(attr, after);
            safe.uboLog(logPrefix, `${attr}="${after}"`);
        }
        return true;
    };

    let observer, timer;
    const onDomChanged = mutations => {
        if ( timer !== undefined ) { return; }
        let shouldWork = false;
        for ( const mutation of mutations ) {
            if ( mutation.addedNodes.length === 0 ) { continue; }
            for ( const node of mutation.addedNodes ) {
                if ( node.nodeType !== 1 ) { continue; }
                shouldWork = true;
                break;
            }
            if ( shouldWork ) { break; }
        }
        if ( shouldWork === false ) { return; }
        timer = self.requestAnimationFrame(( ) => {
            timer = undefined;
            applySetAttr();
        });
    };

    const start = ( ) => {
        if ( applySetAttr() === false ) { return; }
        observer = new MutationObserver(onDomChanged);
        observer.observe(document.body, {
            subtree: true,
            childList: true,
        });
    };
    runAt(( ) => { start(); }, 'idle');
}
registerScriptlet(setAttrFn, {
    name: 'set-attr.fn',
    dependencies: [
        runAt,
        safeSelf,
    ],
});

/**
 * @scriptlet set-attr
 * 
 * @description
 * Sets the specified attribute on the specified elements. This scriptlet runs
 * once when the page loads then afterward on DOM mutations.
 * 
 * Reference: https://github.com/AdguardTeam/Scriptlets/blob/master/src/scriptlets/set-attr.js
 * 
 * @param selector
 * A CSS selector for the elements to target.
 * 
 * @param attr
 * The name of the attribute to modify.
 * 
 * @param value
 * The new value of the attribute. Supported values:
 * - `''`: empty string (default)
 * - `true`
 * - `false`
 * - positive decimal integer 0 <= value < 32768
 * - `[other]`: copy the value from attribute `other` on the same element
 * 
 * */

export function setAttr(
    selector = '',
    attr = '',
    value = ''
) {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('set-attr', selector, attr, value);
    const validValues = [ '', 'false', 'true' ];

    if ( validValues.includes(value.toLowerCase()) === false ) {
        if ( /^\d+$/.test(value) ) {
            const n = parseInt(value, 10);
            if ( n >= 32768 ) { return; }
            value = `${n}`;
        } else if ( /^\[.+\]$/.test(value) === false ) {
            return;
        }
    }

    setAttrFn(false, logPrefix, selector, attr, value);
}
registerScriptlet(setAttr, {
    name: 'set-attr.js',
    dependencies: [
        safeSelf,
        setAttrFn,
    ],
    world: 'ISOLATED',
});

/**
 * @trustedScriptlet trusted-set-attr
 * 
 * @description
 * Sets the specified attribute on the specified elements. This scriptlet runs
 * once when the page loads then afterward on DOM mutations.
 * 
 * Reference: https://github.com/AdguardTeam/Scriptlets/blob/master/wiki/about-trusted-scriptlets.md#-%EF%B8%8F-trusted-set-attr
 * 
 * @param selector
 * A CSS selector for the elements to target.
 * 
 * @param attr
 * The name of the attribute to modify.
 * 
 * @param value
 * The new value of the attribute. Since the scriptlet requires a trusted
 * source, the value can be anything.
 * 
 * */

export function trustedSetAttr(
    selector = '',
    attr = '',
    value = ''
) {
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('trusted-set-attr', selector, attr, value);
    setAttrFn(true, logPrefix, selector, attr, value);
}
registerScriptlet(trustedSetAttr, {
    name: 'trusted-set-attr.js',
    requiresTrust: true,
    dependencies: [
        safeSelf,
        setAttrFn,
    ],
    world: 'ISOLATED',
});

/**
 * @scriptlet remove-attr
 * 
 * @description
 * Remove one or more attributes from a set of elements.
 * 
 * @param attribute
 * The name of the attribute(s) to remove. This can be a list of space-
 * separated attribute names.
 * 
 * @param [selector]
 * Optional. A CSS selector for the elements to target. Default to
 * `[attribute]`, or `[attribute1],[attribute2],...` if more than one
 * attribute name is specified.
 * 
 * @param [behavior]
 * Optional. Space-separated tokens which modify the default behavior.
 * - `asap`: Try to remove the attribute as soon as possible. Default behavior
 *   is to remove the attribute(s) asynchronously. 
 * - `stay`: Keep trying to remove the specified attribute(s) on DOM mutations.
 * */

export function removeAttr(
    rawToken = '',
    rawSelector = '',
    behavior = ''
) {
    if ( typeof rawToken !== 'string' ) { return; }
    if ( rawToken === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('remove-attr', rawToken, rawSelector, behavior);
    const tokens = safe.String_split.call(rawToken, /\s*\|\s*/);
    const selector = tokens
        .map(a => `${rawSelector}[${CSS.escape(a)}]`)
        .join(',');
    if ( safe.logLevel > 1 ) {
        safe.uboLog(logPrefix, `Target selector:\n\t${selector}`);
    }
    const asap = /\basap\b/.test(behavior);
    let timerId;
    const rmattrAsync = ( ) => {
        if ( timerId !== undefined ) { return; }
        timerId = safe.onIdle(( ) => {
            timerId = undefined;
            rmattr();
        }, { timeout: 17 });
    };
    const rmattr = ( ) => {
        if ( timerId !== undefined ) {
            safe.offIdle(timerId);
            timerId = undefined;
        }
        try {
            const nodes = document.querySelectorAll(selector);
            for ( const node of nodes ) {
                for ( const attr of tokens ) {
                    if ( node.hasAttribute(attr) === false ) { continue; }
                    node.removeAttribute(attr);
                    safe.uboLog(logPrefix, `Removed attribute '${attr}'`);
                }
            }
        } catch {
        }
    };
    const mutationHandler = mutations => {
        if ( timerId !== undefined ) { return; }
        let skip = true;
        for ( let i = 0; i < mutations.length && skip; i++ ) {
            const { type, addedNodes, removedNodes } = mutations[i];
            if ( type === 'attributes' ) { skip = false; }
            for ( let j = 0; j < addedNodes.length && skip; j++ ) {
                if ( addedNodes[j].nodeType === 1 ) { skip = false; break; }
            }
            for ( let j = 0; j < removedNodes.length && skip; j++ ) {
                if ( removedNodes[j].nodeType === 1 ) { skip = false; break; }
            }
        }
        if ( skip ) { return; }
        asap ? rmattr() : rmattrAsync();
    };
    const start = ( ) => {
        rmattr();
        if ( /\bstay\b/.test(behavior) === false ) { return; }
        const observer = new MutationObserver(mutationHandler);
        observer.observe(document, {
            attributes: true,
            attributeFilter: tokens,
            childList: true,
            subtree: true,
        });
    };
    runAt(( ) => { start(); }, safe.String_split.call(behavior, /\s+/));
}
registerScriptlet(removeAttr, {
    name: 'remove-attr.js',
    aliases: [
        'ra.js',
    ],
    dependencies: [
        runAt,
        safeSelf,
    ],
});

/******************************************************************************/
