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

const i18n =
    self.browser instanceof Object &&
    self.browser instanceof Element === false
        ? self.browser.i18n
        : self.chrome.i18n;

const i18n$ = (...args) => i18n.getMessage(...args);

/******************************************************************************/

const isBackgroundProcess = document.title === 'uBlock Origin Background Page';

if ( isBackgroundProcess !== true ) {

    // http://www.w3.org/International/questions/qa-scripts#directions
    document.body.setAttribute(
        'dir',
        ['ar', 'he', 'fa', 'ps', 'ur'].indexOf(i18n$('@@ui_locale')) !== -1
            ? 'rtl'
            : 'ltr'
    );

    // https://github.com/gorhill/uBlock/issues/2084
    //   Anything else than <a>, <b>, <code>, <em>, <i>, and <span> will
    //   be rendered as plain text.
    //   For <a>, only href attribute must be present, and it MUST starts with
    //   `https://`, and includes no single- or double-quotes.
    //   No HTML entities are allowed, there is code to handle existing HTML
    //   entities already present in translation files until they are all gone.

    const allowedTags = new Set([
        'a',
        'b',
        'code',
        'em',
        'i',
        'span',
        'u',
    ]);

    const expandHtmlEntities = (( ) => {
        const entities = new Map([
            // TODO: Remove quote entities once no longer present in translation
            // files. Other entities must stay.
            [ '&shy;', '\u00AD' ],
            [ '&ldquo;', '“' ],
            [ '&rdquo;', '”' ],
            [ '&lsquo;', '‘' ],
            [ '&rsquo;', '’' ],
            [ '&lt;', '<' ],
            [ '&gt;', '>' ],
        ]);
        const decodeEntities = match => {
            return entities.get(match) || match;
        };
        return function(text) {
            if ( text.indexOf('&') !== -1 ) {
                text = text.replace(/&[a-z]+;/g, decodeEntities);
            }
            return text;
        };
    })();

    const safeTextToTextNode = function(text) {
        return document.createTextNode(expandHtmlEntities(text));
    };

    const sanitizeElement = function(node) {
        if ( allowedTags.has(node.localName) === false ) { return null; }
        node.removeAttribute('style');
        let child = node.firstElementChild;
        while ( child !== null ) {
            const next = child.nextElementSibling;
            if ( sanitizeElement(child) === null ) {
                child.remove();
            }
            child = next;
        }
        return node;
    };

    const safeTextToDOM = function(text, parent) {
        if ( text === '' ) { return; }

        // Fast path (most common).
        if ( text.indexOf('<') === -1 ) {
            const toInsert = safeTextToTextNode(text);
            let toReplace = parent.childCount !== 0
                ? parent.firstChild
                : null;
            while ( toReplace !== null ) {
                if ( toReplace.nodeType === 3 && toReplace.nodeValue === '_' ) {
                    break;
                }
                toReplace = toReplace.nextSibling;
            }
            if ( toReplace !== null ) {
                parent.replaceChild(toInsert, toReplace);
            } else {
                parent.appendChild(toInsert);
            }
            return;
        }

        // Slow path.
        // `<p>` no longer allowed. Code below can be removed once all <p>'s are
        // gone from translation files.
        text = text.replace(/^<p>|<\/p>/g, '')
                   .replace(/<p>/g, '\n\n');
        // Parse allowed HTML tags.
        const domParser = new DOMParser();
        const parsedDoc = domParser.parseFromString(text, 'text/html');
        let node = parsedDoc.body.firstChild;
        while ( node !== null ) {
            const next = node.nextSibling;
            switch ( node.nodeType ) {
            case 1: // element
                if ( sanitizeElement(node) === null ) { break; }
                parent.appendChild(node);
                break;
            case 3: // text
                parent.appendChild(node);
                break;
            default:
                break;
            }
            node = next;
        }
    };

    i18n.safeTemplateToDOM = function(id, dict, parent) {
        if ( parent === undefined ) {
            parent = document.createDocumentFragment();
        }
        let textin = i18n$(id);
        if ( textin === '' ) {
            return parent;
        }
        if ( textin.indexOf('{{') === -1 ) {
            safeTextToDOM(textin, parent);
            return parent;
        }
        const re = /\{\{\w+\}\}/g;
        let textout = '';
        for (;;) {
            const match = re.exec(textin);
            if ( match === null ) {
                textout += textin;
                break;
            }
            textout += textin.slice(0, match.index);
            let prop = match[0].slice(2, -2);
            if ( Object.hasOwn(dict, prop) ) {
                textout += dict[prop].replace(/</g, '&lt;')
                                     .replace(/>/g, '&gt;');
            } else {
                textout += prop;
            }
            textin = textin.slice(re.lastIndex);
        }
        safeTextToDOM(textout, parent);
        return parent;
    };

    // Helper to deal with the i18n'ing of HTML files.
    i18n.render = function(context) {
        const docu = document;
        const root = context || docu;

        for ( const elem of root.querySelectorAll('[data-i18n]') ) {
            let text = i18n$(elem.getAttribute('data-i18n'));
            if ( !text ) { continue; }
            if ( text.indexOf('{{') === -1 ) {
                safeTextToDOM(text, elem);
                continue;
            }
            // Handle selector-based placeholders: these placeholders tell where
            // existing child DOM element are to be positioned relative to the
            // localized text nodes.
            const parts = text.split(/(\{\{[^}]+\}\})/);
            const fragment = document.createDocumentFragment();
            let textBefore = '';
            for ( let part of parts ) {
                if ( part === '' ) { continue; }
                if ( part.startsWith('{{') && part.endsWith('}}') ) {
                    // TODO: remove detection of ':' once it no longer appears
                    //       in translation files.
                    const pos = part.indexOf(':');
                    if ( pos !== -1 ) {
                        part = part.slice(0, pos) + part.slice(-2);
                    }
                    const selector = part.slice(2, -2);
                    let node;
                    // Ideally, the i18n strings explicitly refer to the
                    // class of the element to insert. However for now we
                    // will create a class from what is currently found in
                    // the placeholder and first try to lookup the resulting
                    // selector. This way we don't have to revisit all
                    // translations just for the sake of declaring the proper
                    // selector in the placeholder field.
                    if ( selector.charCodeAt(0) !== 0x2E /* '.' */ ) {
                        node = elem.querySelector(`.${selector}`);
                    }
                    if ( node instanceof Element === false ) {
                        node = elem.querySelector(selector);
                    }
                    if ( node instanceof Element ) {
                        safeTextToDOM(textBefore, fragment);
                        fragment.appendChild(node);
                        textBefore = '';
                        continue;
                    }
                }
                textBefore += part;
            }
            if ( textBefore !== '' ) {
                safeTextToDOM(textBefore, fragment);
            }
            elem.appendChild(fragment);
        }

        for ( const elem of root.querySelectorAll('[data-i18n-title]') ) {
            const text = i18n$(elem.getAttribute('data-i18n-title'));
            if ( !text ) { continue; }
            elem.setAttribute('title', expandHtmlEntities(text));
        }

        for ( const elem of root.querySelectorAll('[placeholder]') ) {
            const text = i18n$(elem.getAttribute('placeholder'));
            if ( text === '' ) { continue; }
            elem.setAttribute('placeholder', text);
        }

        for ( const elem of root.querySelectorAll('[data-i18n-tip]') ) {
            const text = i18n$(elem.getAttribute('data-i18n-tip'))
                       .replace(/<br>/g, '\n')
                       .replace(/\n{3,}/g, '\n\n');
            elem.setAttribute('data-tip', text);
            if ( elem.getAttribute('aria-label') === 'data-tip' ) {
                elem.setAttribute('aria-label', text);
            }
        }

        for ( const elem of root.querySelectorAll('[data-i18n-label]') ) {
            const text = i18n$(elem.getAttribute('data-i18n-label'));
            elem.setAttribute('label', text);
        }
    };

    i18n.renderElapsedTimeToString = function(tstamp) {
        let value = (Date.now() - tstamp) / 60000;
        if ( value < 2 ) {
            return i18n$('elapsedOneMinuteAgo');
        }
        if ( value < 60 ) {
            return i18n$('elapsedManyMinutesAgo').replace('{{value}}', Math.floor(value).toLocaleString());
        }
        value /= 60;
        if ( value < 2 ) {
            return i18n$('elapsedOneHourAgo');
        }
        if ( value < 24 ) {
            return i18n$('elapsedManyHoursAgo').replace('{{value}}', Math.floor(value).toLocaleString());
        }
        value /= 24;
        if ( value < 2 ) {
            return i18n$('elapsedOneDayAgo');
        }
        return i18n$('elapsedManyDaysAgo').replace('{{value}}', Math.floor(value).toLocaleString());
    };

    const unicodeFlagToImageSrc = new Map([
        [ '🇦🇱', 'al' ], [ '🇦🇷', 'ar' ], [ '🇦🇹', 'at' ], [ '🇧🇦', 'ba' ],
        [ '🇧🇪', 'be' ], [ '🇧🇬', 'bg' ], [ '🇧🇷', 'br' ], [ '🇨🇦', 'ca' ],
        [ '🇨🇭', 'ch' ], [ '🇨🇳', 'cn' ], [ '🇨🇴', 'co' ], [ '🇨🇾', 'cy' ],
        [ '🇨🇿', 'cz' ], [ '🇩🇪', 'de' ], [ '🇩🇰', 'dk' ], [ '🇩🇿', 'dz' ],
        [ '🇪🇪', 'ee' ], [ '🇪🇬', 'eg' ], [ '🇪🇸', 'es' ], [ '🇫🇮', 'fi' ],
        [ '🇫🇴', 'fo' ], [ '🇫🇷', 'fr' ], [ '🇬🇷', 'gr' ], [ '🇭🇷', 'hr' ],
        [ '🇭🇺', 'hu' ], [ '🇮🇩', 'id' ], [ '🇮🇱', 'il' ], [ '🇮🇳', 'in' ],
        [ '🇮🇷', 'ir' ], [ '🇮🇸', 'is' ], [ '🇮🇹', 'it' ], [ '🇯🇵', 'jp' ],
        [ '🇰🇷', 'kr' ], [ '🇰🇿', 'kz' ], [ '🇱🇰', 'lk' ], [ '🇱🇹', 'lt' ],
        [ '🇱🇻', 'lv' ], [ '🇲🇦', 'ma' ], [ '🇲🇩', 'md' ], [ '🇲🇰', 'mk' ],
        [ '🇲🇽', 'mx' ], [ '🇲🇾', 'my' ], [ '🇳🇱', 'nl' ], [ '🇳🇴', 'no' ],
        [ '🇳🇵', 'np' ], [ '🇵🇱', 'pl' ], [ '🇵🇹', 'pt' ], [ '🇷🇴', 'ro' ],
        [ '🇷🇸', 'rs' ], [ '🇷🇺', 'ru' ], [ '🇸🇦', 'sa' ], [ '🇸🇮', 'si' ],
        [ '🇸🇰', 'sk' ], [ '🇸🇪', 'se' ], [ '🇸🇷', 'sr' ], [ '🇹🇭', 'th' ],
        [ '🇹🇯', 'tj' ], [ '🇹🇼', 'tw' ], [ '🇹🇷', 'tr' ], [ '🇺🇦', 'ua' ],
        [ '🇺🇿', 'uz' ], [ '🇻🇳', 'vn' ], [ '🇽🇰', 'xk' ],
    ]);
    const reUnicodeFlags = new RegExp(
        Array.from(unicodeFlagToImageSrc).map(a => a[0]).join('|'),
        'gu'
    );
    i18n.patchUnicodeFlags = function(text) {
        const fragment = document.createDocumentFragment();
        let i = 0;
        for (;;) {
            const match = reUnicodeFlags.exec(text);
            if ( match === null ) { break; }
            if ( match.index > i ) {
                fragment.append(text.slice(i, match.index));
            }
            const img = document.createElement('img');
            const countryCode = unicodeFlagToImageSrc.get(match[0]);
            img.src = `/img/flags-of-the-world/${countryCode}.png`;
            img.title = countryCode;
            img.classList.add('countryFlag');
            fragment.append(img, '\u200A');
            i = reUnicodeFlags.lastIndex;
        }
        if ( i < text.length ) {
            fragment.append(text.slice(i));
        }
        return fragment; 
    };

    i18n.render();
}

/******************************************************************************/

export { i18n, i18n$ };
