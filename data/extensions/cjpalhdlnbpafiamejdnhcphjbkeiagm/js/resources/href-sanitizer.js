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
import { urlSkip } from '../urlskip.js';

/******************************************************************************/

registerScriptlet(urlSkip, {
    name: 'urlskip.fn',
});

/**
 * @scriptlet href-sanitizer
 * 
 * @description
 * Set the `href` attribute to a value found in the DOM at, or below the
 * targeted `a` element, and optionally with transformation steps.
 * 
 * @param selector
 * A plain CSS selector for elements which `href` property must be sanitized.
 * 
 * @param source
 * One or more tokens to lookup the source of the `href` property, and
 * optionally the transformation steps to perform:
 * - `text`: Use the text content of the element as the URL
 * - `[name]`: Use the value of the attribute `name` as the URL
 * - Transformation steps: see `urlskip` documentation
 * 
 * If `text` or `[name]` is not present, the URL will be the value of `href`
 * attribute.
 * 
 * @example
 * `example.org##+js(href-sanitizer, a)`
 * `example.org##+js(href-sanitizer, a[title], [title])`
 * `example.org##+js(href-sanitizer, a[href*="/away.php?to="], ?to)`
 * `example.org##+js(href-sanitizer, a[href*="/redirect"], ?url ?url -base64)`
 * 
 * */

function hrefSanitizer(
    selector = '',
    source = ''
) {
    if ( typeof selector !== 'string' ) { return; }
    if ( selector === '' ) { return; }
    const safe = safeSelf();
    const logPrefix = safe.makeLogPrefix('href-sanitizer', selector, source);
    if ( source === '' ) { source = 'text'; }
    const sanitizeCopycats = (href, text) => {
        let elems = [];
        try {
            elems = document.querySelectorAll(`a[href="${href}"`);
        }
        catch {
        }
        for ( const elem of elems ) {
            elem.setAttribute('href', text);
        }
        return elems.length;
    };
    const validateURL = text => {
        if ( typeof text !== 'string' ) { return ''; }
        if ( text === '' ) { return ''; }
        if ( /[\x00-\x20\x7f]/.test(text) ) { return ''; }
        try {
            const url = new URL(text, document.location);
            return url.href;
        } catch {
        }
        return '';
    };
    const extractParam = (href, source) => {
        if ( Boolean(source) === false ) { return href; }
        const recursive = source.includes('?', 1);
        const end = recursive ? source.indexOf('?', 1) : source.length;
        try {
            const url = new URL(href, document.location);
            let value = url.searchParams.get(source.slice(1, end));
            if ( value === null ) { return href }
            if ( recursive ) { return extractParam(value, source.slice(end)); }
            return value;
        } catch {
        }
        return href;
    };
    const extractURL = (elem, source) => {
        if ( /^\[.*\]$/.test(source) ) {
            return elem.getAttribute(source.slice(1,-1).trim()) || '';
        }
        if ( source === 'text' ) {
            return elem.textContent
                .replace(/^[^\x21-\x7e]+/, '') // remove leading invalid characters
                .replace(/[^\x21-\x7e]+$/, '') // remove trailing invalid characters
            ;
        }
        if ( source.startsWith('?') === false ) { return ''; }
        const steps = source.replace(/(\S)\?/g, '\\1?').split(/\s+/);
        const url = steps.length === 1
            ? extractParam(elem.href, source)
            : urlSkip(elem.href, false, steps);
        if ( url === undefined ) { return; }
        return url.replace(/ /g, '%20');
    };
    const sanitize = ( ) => {
        let elems = [];
        try {
            elems = document.querySelectorAll(selector);
        }
        catch {
            return false;
        }
        for ( const elem of elems ) {
            if ( elem.localName !== 'a' ) { continue; }
            if ( elem.hasAttribute('href') === false ) { continue; }
            const href = elem.getAttribute('href');
            const text = extractURL(elem, source);
            const hrefAfter = validateURL(text);
            if ( hrefAfter === '' ) { continue; }
            if ( hrefAfter === href ) { continue; }
            elem.setAttribute('href', hrefAfter);
            const count = sanitizeCopycats(href, hrefAfter);
            safe.uboLog(logPrefix, `Sanitized ${count+1} links to\n${hrefAfter}`);
        }
        return true;
    };
    let observer, timer;
    const onDomChanged = mutations => {
        if ( timer !== undefined ) { return; }
        let shouldSanitize = false;
        for ( const mutation of mutations ) {
            if ( mutation.addedNodes.length === 0 ) { continue; }
            for ( const node of mutation.addedNodes ) {
                if ( node.nodeType !== 1 ) { continue; }
                shouldSanitize = true;
                break;
            }
            if ( shouldSanitize ) { break; }
        }
        if ( shouldSanitize === false ) { return; }
        timer = safe.onIdle(( ) => {
            timer = undefined;
            sanitize();
        });
    };
    const start = ( ) => {
        if ( sanitize() === false ) { return; }
        observer = new MutationObserver(onDomChanged);
        observer.observe(document.body, {
            subtree: true,
            childList: true,
        });
    };
    runAt(( ) => { start(); }, 'interactive');
}
registerScriptlet(hrefSanitizer, {
    name: 'href-sanitizer.js',
    world: 'ISOLATED',
    aliases: [
        'urlskip.js',
    ],
    dependencies: [
        runAt,
        safeSelf,
        urlSkip,
    ],
});
