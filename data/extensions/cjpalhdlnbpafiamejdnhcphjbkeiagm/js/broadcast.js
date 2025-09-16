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

import webext from './webext.js';

/******************************************************************************/

// Broadcast a message to all uBO contexts

let broadcastChannel;

export function broadcast(message) {
    if ( broadcastChannel === undefined ) {
        broadcastChannel = new self.BroadcastChannel('uBO');
    }
    broadcastChannel.postMessage(message);
}

/******************************************************************************/

// Broadcast a message to all uBO contexts and all uBO's content scripts

export async function broadcastToAll(message) {
    broadcast(message);
    const tabs = await vAPI.tabs.query({
        discarded: false,
    });
    const bcmessage = Object.assign({ broadcast: true }, message);
    for ( const tab of tabs ) {
        webext.tabs.sendMessage(tab.id, bcmessage).catch(( ) => { });
    }
}

/******************************************************************************/

export function onBroadcast(listener) {
    const bc = new self.BroadcastChannel('uBO');
    bc.onmessage = ev => listener(ev.data || {});
    return bc;
}

/******************************************************************************/

export function filteringBehaviorChanged(details = {}) {
    if ( typeof details.direction !== 'number' || details.direction >= 0 ) {
        filteringBehaviorChanged.throttle.offon(727);
    }
    broadcast(Object.assign({ what: 'filteringBehaviorChanged' }, details));
}

filteringBehaviorChanged.throttle = vAPI.defer.create(( ) => {
    const { history, max } = filteringBehaviorChanged;
    const now = (Date.now() / 1000) | 0;
    if ( history.length >= max ) {
        if ( (now - history[0]) <= (10 * 60) ) { return; }
        history.shift();
    }
    history.push(now);
    vAPI.net.handlerBehaviorChanged();
});
filteringBehaviorChanged.history = [];
filteringBehaviorChanged.max = Math.min(
    browser.webRequest.MAX_HANDLER_BEHAVIOR_CHANGED_CALLS_PER_10_MINUTES - 1,
    19
);

/******************************************************************************/
