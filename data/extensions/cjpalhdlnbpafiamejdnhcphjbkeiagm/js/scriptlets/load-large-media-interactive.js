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

(( ) => {

/******************************************************************************/

// This can happen
if ( typeof vAPI !== 'object' || vAPI.loadAllLargeMedia instanceof Function ) {
    return;
}

const largeMediaElementAttribute = 'data-' + vAPI.sessionId;
const largeMediaElementSelector =
    ':root   audio[' + largeMediaElementAttribute + '],\n' +
    ':root     img[' + largeMediaElementAttribute + '],\n' +
    ':root picture[' + largeMediaElementAttribute + '],\n' +
    ':root   video[' + largeMediaElementAttribute + ']';

const isMediaElement = elem =>
    (/^(?:audio|img|picture|video)$/.test(elem.localName));

const isPlayableMediaElement = elem =>
    (/^(?:audio|video)$/.test(elem.localName));

/******************************************************************************/

const mediaNotLoaded = function(elem) {
    switch ( elem.localName ) {
    case 'audio':
    case 'video':
        return elem.readyState === 0 || elem.error !== null;
    case 'img': {
        if ( elem.naturalWidth !== 0 || elem.naturalHeight !== 0 ) {
            break;
        }
        const style = window.getComputedStyle(elem);
        // For some reason, style can be null with Pale Moon.
        return style !== null ?
            style.getPropertyValue('display') !== 'none' :
            elem.offsetHeight !== 0 && elem.offsetWidth !== 0;
    }
    default:
        break;
    }
    return false;
};

/******************************************************************************/

// For all media resources which have failed to load, trigger a reload.

// <audio> and <video> elements.
// https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement

const surveyMissingMediaElements = function() {
    let largeMediaElementCount = 0;
    for ( const elem of document.querySelectorAll('audio,img,video') ) {
        if ( mediaNotLoaded(elem) === false ) { continue; }
        elem.setAttribute(largeMediaElementAttribute, '');
        largeMediaElementCount += 1;
        switch ( elem.localName ) {
        case 'img': {
            const picture = elem.closest('picture');
            if ( picture !== null ) {
                picture.setAttribute(largeMediaElementAttribute, '');
            }
        } break;
        default:
            break;
        }
    }
    return largeMediaElementCount;
};

if ( surveyMissingMediaElements() ) {
    // Insert CSS to highlight blocked media elements.
    if ( vAPI.largeMediaElementStyleSheet === undefined ) {
        vAPI.largeMediaElementStyleSheet = [
            largeMediaElementSelector + ' {',
                'border: 2px dotted red !important;',
                'box-sizing: border-box !important;',
                'cursor: zoom-in !important;',
                'display: inline-block;',
                'filter: none !important;',
                'font-size: 1rem !important;',
                'min-height: 1em !important;',
                'min-width: 1em !important;',
                'opacity: 1 !important;',
                'outline: none !important;',
                'transform: none !important;',
                'visibility: visible !important;',
                'z-index: 2147483647',
            '}',
        ].join('\n');
        vAPI.userStylesheet.add(vAPI.largeMediaElementStyleSheet);
        vAPI.userStylesheet.apply();
    }
}

/******************************************************************************/

const loadMedia = async function(elem) {
    const src = elem.getAttribute('src') || '';
    if ( src === '' ) { return; }
    elem.removeAttribute('src');
    await vAPI.messaging.send('scriptlets', {
        what: 'temporarilyAllowLargeMediaElement',
    });
    elem.setAttribute('src', src);
    elem.load();
};

/******************************************************************************/

const loadImage = async function(elem) {
    const src = elem.getAttribute('src') || '';
    const srcset = src === '' && elem.getAttribute('srcset') || '';
    if ( src === '' && srcset === '' ) { return; }
    if ( src !== '' ) {
        elem.removeAttribute('src');
    }
    if ( srcset !== '' ) {
        elem.removeAttribute('srcset');
    }
    await vAPI.messaging.send('scriptlets', {
        what: 'temporarilyAllowLargeMediaElement',
    });
    if ( src !== '' ) {
        elem.setAttribute('src', src);
    } else if ( srcset !== '' ) {
        elem.setAttribute('srcset', srcset);
    }
};

/******************************************************************************/

const loadMany = function(elems) {
    for ( const elem of elems ) {
        switch ( elem.localName ) {
        case 'audio':
        case 'video':
            loadMedia(elem);
            break;
        case 'img':
            loadImage(elem);
            break;
        default:
            break;
        }
    }
};

/******************************************************************************/

const onMouseClick = function(ev) {
    if ( ev.button !== 0 || ev.isTrusted === false ) { return; }

    const toLoad = [];
    const elems = document.elementsFromPoint instanceof Function
        ? document.elementsFromPoint(ev.clientX, ev.clientY)
        : [ ev.target ];
    for ( const elem of elems ) {
        if ( elem.matches(largeMediaElementSelector) === false ) { continue; }
        elem.removeAttribute(largeMediaElementAttribute);
        if ( mediaNotLoaded(elem) ) {
            toLoad.push(elem);
        }
    }

    if ( toLoad.length === 0 ) { return; }

    loadMany(toLoad);

    ev.preventDefault();
    ev.stopPropagation();
};

document.addEventListener('click', onMouseClick, true);

/******************************************************************************/

const onLoadedData = function(ev) {
    const media = ev.target;
    if ( media.localName !== 'audio' && media.localName !== 'video' ) {
        return;
    }
    const src = media.src;
    if ( typeof src === 'string' && src.startsWith('blob:') === false ) {
        return;
    }
    media.autoplay = false;
    media.pause();
};

// https://www.reddit.com/r/uBlockOrigin/comments/mxgpmc/
//   Support cases where the media source is not yet set.
for ( const media of document.querySelectorAll('audio,video') ) {
    const src = media.src;
    if (
        (typeof src === 'string') &&
        (src === '' || src.startsWith('blob:'))
    ) {
        media.autoplay = false;
        media.pause();
    }
}

document.addEventListener('loadeddata', onLoadedData);

/******************************************************************************/

const onLoad = function(ev) {
    const elem = ev.target;
    if ( isMediaElement(elem) === false ) { return; }
    elem.removeAttribute(largeMediaElementAttribute);
};

document.addEventListener('load', onLoad, true);

/******************************************************************************/

const onLoadError = function(ev) {
    const elem = ev.target;
    if ( isMediaElement(elem) === false ) { return; }
    if ( mediaNotLoaded(elem) ) {
        elem.setAttribute(largeMediaElementAttribute, '');
    }
};

document.addEventListener('error', onLoadError, true);

/******************************************************************************/

const autoPausedMedia = new WeakMap();

for ( const elem of document.querySelectorAll('audio,video') ) {
    elem.setAttribute('autoplay', 'false');
}

const preventAutoplay = function(ev) {
    const elem = ev.target;
    if ( isPlayableMediaElement(elem) === false ) { return; }
    const currentSrc = elem.getAttribute('src') || '';
    const pausedSrc = autoPausedMedia.get(elem);
    if ( pausedSrc === currentSrc ) { return; }
    autoPausedMedia.set(elem, currentSrc);
    elem.setAttribute('autoplay', 'false');
    elem.pause();
};

document.addEventListener('timeupdate', preventAutoplay, true);

/******************************************************************************/

vAPI.loadAllLargeMedia = function() {
    document.removeEventListener('click', onMouseClick, true);
    document.removeEventListener('loadeddata', onLoadedData, true);
    document.removeEventListener('load', onLoad, true);
    document.removeEventListener('error', onLoadError, true);

    const toLoad = [];
    for ( const elem of document.querySelectorAll(largeMediaElementSelector) ) {
        elem.removeAttribute(largeMediaElementAttribute);
        if ( mediaNotLoaded(elem) ) {
            toLoad.push(elem);
        }
    }
    loadMany(toLoad);
};

/******************************************************************************/

})();








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;
