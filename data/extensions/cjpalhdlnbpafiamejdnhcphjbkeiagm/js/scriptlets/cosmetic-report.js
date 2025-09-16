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

/******************************************************************************/

(( ) => {
// >>>>>>>> start of private namespace

/******************************************************************************/

if ( typeof vAPI !== 'object' ) { return; }
if ( typeof vAPI.domFilterer !== 'object' ) { return; }
if ( vAPI.domFilterer === null ) { return; }

/******************************************************************************/

const rePseudoElements = /:(?::?after|:?before|:[a-z-]+)$/;

const hasSelector = selector => {
    try {
        return document.querySelector(selector) !== null;
    }
    catch {
    }
    return false;
};

const safeQuerySelector = selector => {
    const safeSelector = rePseudoElements.test(selector)
        ? selector.replace(rePseudoElements, '')
        : selector;
    try {
        return document.querySelector(safeSelector);
    }
    catch {
    }
    return null;
};

const safeGroupSelectors = selectors => {
    const arr = Array.isArray(selectors)
        ? selectors
        : Array.from(selectors);
    return arr.map(s => {
        return rePseudoElements.test(s)
            ? s.replace(rePseudoElements, '')
            : s;
    }).join(',\n');
};

const allSelectors = vAPI.domFilterer.getAllSelectors();
const matchedSelectors = [];

if ( Array.isArray(allSelectors.declarative) ) {
    const declarativeSet = new Set();
    for ( const block of allSelectors.declarative ) {
        for ( const selector of block.split(',\n') ) {
            declarativeSet.add(selector);
        }
    }
    if ( hasSelector(safeGroupSelectors(declarativeSet)) ) {
        for ( const selector of declarativeSet ) {
            if ( safeQuerySelector(selector) === null ) { continue; }
            matchedSelectors.push(`##${selector}`);
        }
    }
}

if (
    Array.isArray(allSelectors.procedural) &&
    allSelectors.procedural.length !== 0
) {
    for ( const pselector of allSelectors.procedural ) {
        if ( pselector.hit === false && pselector.exec().length === 0 ) { continue; }
        matchedSelectors.push(`##${pselector.raw}`);
    }
}

if ( Array.isArray(allSelectors.exceptions) ) {
    const exceptionDict = new Map();
    for ( const selector of allSelectors.exceptions ) {
        if ( selector.charCodeAt(0) !== 0x7B /* '{' */ ) {
            exceptionDict.set(selector, selector);
            continue;
        }
        const details = JSON.parse(selector);
        if (
            details.action !== undefined &&
            details.tasks === undefined &&
            details.action[0] === 'style'
        ) {
            exceptionDict.set(details.selector, details.raw);
            continue;
        }
        const pselector = vAPI.domFilterer.createProceduralFilter(details);
        if ( pselector.test() === false ) { continue; }
        matchedSelectors.push(`#@#${pselector.raw}`);
    }
    if (
        exceptionDict.size !== 0 &&
        hasSelector(safeGroupSelectors(exceptionDict.keys()))
    ) {
        for ( const [ selector, raw ] of exceptionDict ) {
            if ( safeQuerySelector(selector) === null ) { continue; }
            matchedSelectors.push(`#@#${raw}`);
        }
    }
}

if ( self.uBO_scriptletsInjected !== undefined ) {
    matchedSelectors.push(...self.uBO_scriptletsInjected);
}

if ( matchedSelectors.length === 0 ) { return; }

return matchedSelectors;

/******************************************************************************/

// <<<<<<<< end of private namespace
})();

