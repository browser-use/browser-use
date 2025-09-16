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

import { dom, qs$ } from './dom.js';
import { i18n, i18n$ } from './i18n.js';
import { faIconsInit } from './fa-icons.js';

/******************************************************************************/

const messaging = vAPI.messaging;
const details = {};

{
    const matches = /details=([^&]+)/.exec(window.location.search);
    if ( matches !== null ) {
        Object.assign(details, JSON.parse(decodeURIComponent(matches[1])));
    }
}

/******************************************************************************/

const urlToFragment = raw => {
    try {
        const fragment = new DocumentFragment();
        const url = new URL(raw);
        const hn = url.hostname;
        const i = raw.indexOf(hn);
        const b = document.createElement('b');
        b.append(hn);
        fragment.append(raw.slice(0,i), b, raw.slice(i+hn.length));
        return fragment;
    } catch {
    }
    return raw;
};

/******************************************************************************/

dom.clear('#theURL > p > span:first-of-type');
qs$('#theURL > p > span:first-of-type').append(urlToFragment(details.url));

/******************************************************************************/

const lookupFilterLists = async ( ) => {
    const response = await messaging.send('documentBlocked', {
        what: 'listsFromNetFilter',
        rawFilter: details.fs,
    });
    if ( response instanceof Object === false ) { return; }
    let lists;
    for ( const rawFilter in response ) {
        if ( Object.hasOwn(response, rawFilter) ) {
            lists = response[rawFilter];
            break;
        }
    }
    return lists;
};

/******************************************************************************/

if ( typeof details.to === 'string' && details.to.length !== 0 ) {
    const fragment = new DocumentFragment();
    const text = i18n$('docblockedRedirectPrompt');
    const linkPlaceholder = '{{url}}';
    let pos = text.indexOf(linkPlaceholder);
    if ( pos !== -1 ) {
        const link = document.createElement('a');
        link.href = details.to;
        dom.cl.add(link, 'code');
        link.append(urlToFragment(details.to)); 
        fragment.append(
            text.slice(0, pos),
            link,
            text.slice(pos + linkPlaceholder.length)
        );
        qs$('#urlskip').append(fragment);
        dom.attr('#urlskip', 'hidden', null);
    }
}

/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/691
//   Parse URL to extract as much useful information as possible. This is
//   useful to assist the user in deciding whether to navigate to the web page.
(( ) => {
    if ( typeof URL !== 'function' ) { return; }

    const reURL = /^https?:\/\//;

    const liFromParam = function(name, value) {
        if ( value === '' ) {
            value = name;
            name = '';
        }
        const li = dom.create('li');
        let span = dom.create('span');
        dom.text(span, name);
        li.appendChild(span);
        if ( name !== '' && value !== '' ) {
            li.appendChild(document.createTextNode(' = '));
        }
        span = dom.create('span');
        if ( reURL.test(value) ) {
            const a = dom.create('a');
            dom.attr(a, 'href', value);
            dom.text(a, value);
            span.appendChild(a);
        } else {
            dom.text(span, value);
        }
        li.appendChild(span);
        return li;
    };

    // https://github.com/uBlockOrigin/uBlock-issues/issues/1649
    //   Limit recursion.
    const renderParams = function(parentNode, rawURL, depth = 0) {
        let url;
        try {
            url = new URL(rawURL);
        } catch {
            return false;
        }

        const search = url.search.slice(1);
        if ( search === '' ) { return false; }

        url.search = '';
        const li = liFromParam(i18n$('docblockedNoParamsPrompt'), url.href);
        parentNode.appendChild(li);

        const params = new self.URLSearchParams(search);
        for ( const [ name, value ] of params ) {
            const li = liFromParam(name, value);
            if ( depth < 2 && reURL.test(value) ) {
                const ul = dom.create('ul');
                renderParams(ul, value, depth + 1);
                li.appendChild(ul);
            }
            parentNode.appendChild(li);
        }

        return true;
    };

    if ( renderParams(qs$('#parsed'), details.url) === false ) {
        return;
    }

    dom.cl.remove('#toggleParse', 'hidden');

    dom.on('#toggleParse', 'click', ( ) => {
        dom.cl.toggle('#theURL', 'collapsed');
        vAPI.localStorage.setItem(
            'document-blocked-expand-url',
            (dom.cl.has('#theURL', 'collapsed') === false).toString()
        );
    });

    vAPI.localStorage.getItemAsync('document-blocked-expand-url').then(value => {
        dom.cl.toggle('#theURL', 'collapsed', value !== 'true' && value !== true);
    });
})();

/******************************************************************************/

// https://www.reddit.com/r/uBlockOrigin/comments/breeux/close_this_window_doesnt_work_on_firefox/

if ( window.history.length > 1 ) {
    dom.on('#back', 'click', ( ) => {
        window.history.back();
    });
    qs$('#bye').style.display = 'none';
} else {
    dom.on('#bye', 'click', ( ) => {
        messaging.send('documentBlocked', {
            what: 'closeThisTab',
        });
    });
    qs$('#back').style.display = 'none';
}

/******************************************************************************/

const proceedToURL = function() {
    window.location.replace(details.url);
};

const proceedTemporary = async function() {
    await messaging.send('documentBlocked', {
        what: 'temporarilyWhitelistDocument',
        hostname: details.hn,
    });
    proceedToURL();
};

const proceedPermanent = async function() {
    await messaging.send('documentBlocked', {
        what: 'toggleHostnameSwitch',
        name: 'no-strict-blocking',
        hostname: details.hn,
        deep: true,
        state: true,
        persist: true,
    });
    proceedToURL();
};

dom.on('#disableWarning', 'change', ev => {
    const checked = ev.target.checked;
    dom.cl.toggle('[data-i18n="docblockedBack"]', 'disabled', checked);
    dom.cl.toggle('[data-i18n="docblockedClose"]', 'disabled', checked);
});

dom.on('#proceed', 'click', ( ) => {
    if ( qs$('#disableWarning').checked ) {
        proceedPermanent();
    } else {
        proceedTemporary();
    }
});

lookupFilterLists().then((lists = []) => {
    let reason = details.reason;
    if ( Boolean(reason) === false ) {
        reason = lists.reduce((a, b) => a || b.reason, undefined);
    }
    if ( reason ) {
        const msg = i18n$(`docblockedReason${reason.charAt(0).toUpperCase()}${reason.slice(1)}`);
        if ( msg ) { reason = msg };
    }
    const why = qs$(reason ? 'template.why-reason' : 'template.why')
        .content
        .cloneNode(true);
    i18n.render(why);
    dom.text(qs$(why, '.why'), details.fs);
    if ( reason ) {
        dom.text(qs$(why, 'summary'), `Reason: ${reason}`);
    }
    qs$('#why').append(why);
    dom.cl.remove(dom.body, 'loading');

    if ( lists.length === 0 ) { return; }

    const whyExtra = qs$('template.why-extra').content.cloneNode(true);
    i18n.render(whyExtra);

    const listTemplate = qs$('template.filterList');
    const parent = qs$(whyExtra, '.why-extra');
    let separator = '';
    for ( const list of lists ) {
        const listElem = listTemplate.content.cloneNode(true);
        const sourceElem = qs$(listElem, '.filterListSource');
        sourceElem.href += encodeURIComponent(list.assetKey);
        sourceElem.append(i18n.patchUnicodeFlags(list.title));
        if ( typeof list.supportURL === 'string' && list.supportURL !== '' ) {
            const supportElem = qs$(listElem, '.filterListSupport');
            dom.attr(supportElem, 'href', list.supportURL);
            dom.cl.remove(supportElem, 'hidden');
        }
        parent.append(separator, listElem);
        separator = '\u00A0\u2022\u00A0';
    }
    faIconsInit(whyExtra);
    qs$('#why .why').after(whyExtra);
});

/******************************************************************************/
