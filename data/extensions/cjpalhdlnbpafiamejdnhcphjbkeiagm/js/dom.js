/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-present Raymond Hill

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

const normalizeTarget = target => {
    if ( typeof target === 'string' ) { return Array.from(qsa$(target)); }
    if ( target instanceof Element ) { return [ target ]; }
    if ( target === null ) { return []; }
    if ( Array.isArray(target) ) { return target; }
    return Array.from(target);
};

const makeEventHandler = (selector, callback) => {
    return function(event) {
        const dispatcher = event.currentTarget;
        if (
            dispatcher instanceof HTMLElement === false ||
            typeof dispatcher.querySelectorAll !== 'function'
        ) {
            return;
        }
        const receiver = event.target;
        const ancestor = receiver.closest(selector);
        if (
            ancestor === receiver &&
            ancestor !== dispatcher &&
            dispatcher.contains(ancestor)
        ) {
            callback.call(receiver, event);
        }
    };
};

/******************************************************************************/

class dom {
    static attr(target, attr, value = undefined) {
        for ( const elem of normalizeTarget(target) ) {
            if ( value === undefined ) {
                return elem.getAttribute(attr);
            }
            if ( value === null ) {
                elem.removeAttribute(attr);
            } else {
                elem.setAttribute(attr, value);
            }
        }
    }

    static clear(target) {
        for ( const elem of normalizeTarget(target) ) {
            while ( elem.firstChild !== null ) {
                elem.removeChild(elem.firstChild);
            }
        }
    }

    static clone(target) {
        const elements = normalizeTarget(target);
        if ( elements.length === 0 ) { return null; }
        return elements[0].cloneNode(true);
    }

    static create(a) {
        if ( typeof a === 'string' ) {
            return document.createElement(a);
        }
    }

    static prop(target, prop, value = undefined) {
        for ( const elem of normalizeTarget(target) ) {
            if ( value === undefined ) { return elem[prop]; }
            elem[prop] = value;
        }
    }

    static text(target, text) {
        const targets = normalizeTarget(target);
        if ( text === undefined ) {
            return targets.length !== 0 ? targets[0].textContent : undefined;
        }
        for ( const elem of targets ) {
            elem.textContent = text;
        }
    }

    static remove(target) {
        for ( const elem of normalizeTarget(target) ) {
            elem.remove();
        }
    }

    static empty(target) {
        for ( const elem of normalizeTarget(target) ) {
            while ( elem.firstElementChild !== null ) {
                elem.firstElementChild.remove();
            }
        }
    }

    // target, type, callback, [options]
    // target, type, subtarget, callback, [options]
    
    static on(target, type, subtarget, callback, options) {
        if ( typeof subtarget === 'function' ) {
            options = callback;
            callback = subtarget;
            subtarget = undefined;
            if ( typeof options === 'boolean' ) {
                options = { capture: true };
            }
        } else {
            callback = makeEventHandler(subtarget, callback);
            if ( options === undefined || typeof options === 'boolean' ) {
                options = { capture: true };
            } else {
                options.capture = true;
            }
        }
        const targets = target instanceof Window || target instanceof Document
            ? [ target ]
            : normalizeTarget(target);
        for ( const elem of targets ) {
            elem.addEventListener(type, callback, options);
        }
    }

    static off(target, type, callback, options) {
        if ( typeof callback !== 'function' ) { return; }
        if ( typeof options === 'boolean' ) {
            options = { capture: true };
        }
        const targets = target instanceof Window || target instanceof Document
            ? [ target ]
            : normalizeTarget(target);
        for ( const elem of targets ) {
            elem.removeEventListener(type, callback, options);
        }
    }
}

dom.cl = class {
    static add(target, name) {
        for ( const elem of normalizeTarget(target) ) {
            elem.classList.add(name);
        }
    }

    static remove(target, ...names) {
        for ( const elem of normalizeTarget(target) ) {
            elem.classList.remove(...names);
        }
    }

    static toggle(target, name, state) {
        let r;
        for ( const elem of normalizeTarget(target) ) {
            r = elem.classList.toggle(name, state);
        }
        return r;
    }

    static has(target, name) {
        for ( const elem of normalizeTarget(target) ) {
            if ( elem.classList.contains(name) ) {
                return true;
            }
        }
        return false;
    }
};

/******************************************************************************/

function qs$(a, b) {
    if ( typeof a === 'string') {
        return document.querySelector(a);
    }
    if ( a === null ) { return null; }
    return a.querySelector(b);
}

function qsa$(a, b) {
    if ( typeof a === 'string') {
        return document.querySelectorAll(a);
    }
    if ( a === null ) { return []; }
    return a.querySelectorAll(b);
}

dom.root = qs$(':root');
dom.html = document.documentElement;
dom.head = document.head;
dom.body = document.body;

/******************************************************************************/

export { dom, qs$, qsa$ };
