/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015-2018 Raymond Hill

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

(( ) => {

/******************************************************************************/

self.cloud = {
    options: {},
    datakey: '',
    data: undefined,
    onPush: null,
    onPull: null,
};

/******************************************************************************/

const widget = qs$('#cloudWidget');
if ( widget === null ) { return; }

self.cloud.datakey = dom.attr(widget, 'data-cloud-entry') || '';
if ( self.cloud.datakey === '' ) { return; }

/******************************************************************************/

const fetchStorageUsed = async function() {
    let elem = qs$(widget, '#cloudCapacity');
    if ( dom.cl.has(elem, 'hide') ) { return; }
    const result = await vAPI.messaging.send('cloudWidget', {
        what: 'cloudUsed',
        datakey: self.cloud.datakey,
    });
    if ( result instanceof Object === false ) {
        dom.cl.add(elem, 'hide');
        return;
    }
    const units = ' ' + i18n$('genericBytes');
    elem.title = result.max.toLocaleString() + units;
    const total = (result.total / result.max * 100).toFixed(1);
    elem = elem.firstElementChild;
    elem.style.width = `${total}%`;
    elem.title = result.total.toLocaleString() + units;
    const used = (result.used / result.total * 100).toFixed(1);
    elem = elem.firstElementChild;
    elem.style.width = `${used}%`;
    elem.title = result.used.toLocaleString() + units;
};

/******************************************************************************/

const fetchCloudData = async function() {
    const info = qs$(widget, '#cloudInfo');

    const entry = await vAPI.messaging.send('cloudWidget', {
        what: 'cloudPull',
        datakey: self.cloud.datakey,
    });

    const hasData = entry instanceof Object;
    if ( hasData === false ) {
        dom.attr('#cloudPull', 'disabled', '');
        dom.attr('#cloudPullAndMerge', 'disabled', '');
        info.textContent = '...\n...';
        return entry;
    }

    self.cloud.data = entry.data;

    dom.attr('#cloudPull', 'disabled', null);
    dom.attr('#cloudPullAndMerge', 'disabled', null);

    const timeOptions = {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
        timeZoneName: 'short'
    };

    const time = new Date(entry.tstamp);
    info.textContent =
        entry.source + '\n' +
        time.toLocaleString('fullwide', timeOptions);
};

/******************************************************************************/

const pushData = async function() {
    if ( typeof self.cloud.onPush !== 'function' ) { return; }

    const error = await vAPI.messaging.send('cloudWidget', {
        what: 'cloudPush',
        datakey: self.cloud.datakey,
        data: self.cloud.onPush(),
    });
    const failed = typeof error === 'string';
    dom.cl.toggle('#cloudPush', 'error', failed);
    dom.text('#cloudError', failed ? error : '');
    if ( failed ) { return; }
    fetchCloudData();
    fetchStorageUsed();
};

/******************************************************************************/

const pullData = function() {
    if ( typeof self.cloud.onPull === 'function' ) {
        self.cloud.onPull(self.cloud.data, false);
    }
    dom.cl.remove('#cloudPush', 'error');
    dom.text('#cloudError', '');
};

/******************************************************************************/

const pullAndMergeData = function() {
    if ( typeof self.cloud.onPull === 'function' ) {
        self.cloud.onPull(self.cloud.data, true);
    }
};

/******************************************************************************/

const openOptions = function() {
    const input = qs$('#cloudDeviceName');
    input.value = self.cloud.options.deviceName;
    dom.attr(input, 'placeholder', self.cloud.options.defaultDeviceName);
    dom.cl.add('#cloudOptions', 'show');
};

/******************************************************************************/

const closeOptions = function(ev) {
    const root = qs$('#cloudOptions');
    if ( ev.target !== root ) { return; }
    dom.cl.remove(root, 'show');
};

/******************************************************************************/

const submitOptions = async function() {
    dom.cl.remove('#cloudOptions', 'show');

    const options = await vAPI.messaging.send('cloudWidget', {
        what: 'cloudSetOptions',
        options: {
            deviceName: qs$('#cloudDeviceName').value
        },
    });
    if ( options instanceof Object ) {
        self.cloud.options = options;
    }
};

/******************************************************************************/

const onInitialize = function(options) {
    if ( options instanceof Object === false ) { return; }
    if ( options.enabled !== true ) { return; }
    self.cloud.options = options;

    const xhr = new XMLHttpRequest();
    xhr.open('GET', 'cloud-ui.html', true);
    xhr.overrideMimeType('text/html;charset=utf-8');
    xhr.responseType = 'text';
    xhr.onload = function() {
        this.onload = null;
        const parser = new DOMParser(),
            parsed = parser.parseFromString(this.responseText, 'text/html'),
            fromParent = parsed.body;
        while ( fromParent.firstElementChild !== null ) {
            widget.appendChild(
                document.adoptNode(fromParent.firstElementChild)
            );
        }

        faIconsInit(widget);

        i18n.render(widget);
        dom.cl.remove(widget, 'hide');

        dom.on('#cloudPush', 'click', ( ) => { pushData(); });
        dom.on('#cloudPull', 'click', pullData);
        dom.on('#cloudPullAndMerge', 'click', pullAndMergeData);
        dom.on('#cloudCog', 'click', openOptions);
        dom.on('#cloudOptions', 'click', closeOptions);
        dom.on('#cloudOptionsSubmit', 'click', ( ) => { submitOptions(); });

        fetchCloudData().then(result => {
            if ( typeof result !== 'string' ) { return; }
            dom.cl.add('#cloudPush', 'error');
            dom.text('#cloudError', result);
        });
        fetchStorageUsed();
    };
    xhr.send();
};

vAPI.messaging.send('cloudWidget', {
    what: 'cloudGetOptions',
}).then(options => {
    onInitialize(options);
});

/******************************************************************************/

})();
