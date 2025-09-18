/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-2015 The uBlock Origin authors
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

// For non-background page

/******************************************************************************/

// https://github.com/chrisaljoudi/uBlock/issues/456
//   Skip if already injected.

// >>>>>>>> start of HUGE-IF-BLOCK
if (
    typeof vAPI === 'object' &&
    vAPI.randomToken instanceof Function === false
) {

/******************************************************************************/
/******************************************************************************/

vAPI.randomToken = function() {
    const n = Math.random();
    return String.fromCharCode(n * 25 + 97) +
        Math.floor(
            (0.25 + n * 0.75) * Number.MAX_SAFE_INTEGER
        ).toString(36).slice(-8);
};

vAPI.sessionId = vAPI.randomToken();
vAPI.setTimeout = vAPI.setTimeout || self.setTimeout.bind(self);

/******************************************************************************/

vAPI.shutdown = {
    jobs: [],
    add: function(job) {
        this.jobs.push(job);
    },
    exec: function() {
        // Shutdown asynchronously, to ensure shutdown jobs are called from
        // the top context.
        self.requestIdleCallback(( ) => {
            const jobs = this.jobs.slice();
            this.jobs.length = 0;
            while ( jobs.length !== 0 ) {
                (jobs.pop())();
            }
        });
    },
    remove: function(job) {
        let pos;
        while ( (pos = this.jobs.indexOf(job)) !== -1 ) {
            this.jobs.splice(pos, 1);
        }
    }
};

/******************************************************************************/

vAPI.messaging = {
    port: null,
    portTimer: null,
    portTimerDelay: 10000,
    msgIdGenerator: 1,
    pending: new Map(),
    waitStartTime: 0,
    shuttingDown: false,

    shutdown: function() {
        this.shuttingDown = true;
        this.destroyPort();
    },

    // https://github.com/uBlockOrigin/uBlock-issues/issues/403
    //   Spurious disconnection can happen, so do not consider such events
    //   as world-ending, i.e. stay around. Except for embedded frames.

    disconnectListener: function() {
        void browser.runtime.lastError;
        this.port = null;
        if ( window !== window.top ) {
            vAPI.shutdown.exec();
        } else {
            this.destroyPort();
        }
    },
    disconnectListenerBound: null,

    // 2020-09-01:
    //   In Firefox, `details instanceof Object` resolves to `false` despite
    //   `details` being a valid object. Consequently, falling back to use
    //   `typeof details`.
    //   This is an issue which surfaced when the element picker code was
    //   revisited to isolate the picker dialog DOM from the page DOM.
    messageListener: function(details) {
        if ( typeof details !== 'object' || details === null ) { return; }
        if ( details.msgId === undefined ) { return; }
        const resolver = this.pending.get(details.msgId);
        if ( resolver === undefined ) { return; }
        this.pending.delete(details.msgId);
        resolver(details.msg);
    },
    messageListenerBound: null,

    canDestroyPort: function() {
        return this.pending.size === 0;
    },

    portPoller: function() {
        this.portTimer = null;
        if ( this.port !== null && this.canDestroyPort() ) {
            return this.destroyPort();
        }
        this.portTimer = vAPI.setTimeout(this.portPollerBound, this.portTimerDelay);
        this.portTimerDelay = Math.min(this.portTimerDelay * 2, 60 * 60 * 1000);
    },
    portPollerBound: null,

    destroyPort: function() {
        if ( this.portTimer !== null ) {
            clearTimeout(this.portTimer);
            this.portTimer = null;
        }
        const port = this.port;
        if ( port !== null ) {
            port.disconnect();
            port.onMessage.removeListener(this.messageListenerBound);
            port.onDisconnect.removeListener(this.disconnectListenerBound);
            this.port = null;
        }
        // service pending callbacks
        if ( this.pending.size !== 0 ) {
            const pending = this.pending;
            this.pending = new Map();
            for ( const resolver of pending.values() ) {
                resolver();
            }
        }
    },

    createPort: function() {
        if ( this.shuttingDown ) { return null; }
        if ( this.messageListenerBound === null ) {
            this.messageListenerBound = this.messageListener.bind(this);
            this.disconnectListenerBound = this.disconnectListener.bind(this);
            this.portPollerBound = this.portPoller.bind(this);
        }
        try {
            this.port = browser.runtime.connect({name: vAPI.sessionId}) || null;
        } catch {
            this.port = null;
        }
        // Not having a valid port at this point means the main process is
        // not available: no point keeping the content scripts alive.
        if ( this.port === null ) {
            vAPI.shutdown.exec();
            return null;
        }
        this.port.onMessage.addListener(this.messageListenerBound);
        this.port.onDisconnect.addListener(this.disconnectListenerBound);
        this.portTimerDelay = 10000;
        if ( this.portTimer === null ) {
            this.portTimer = vAPI.setTimeout(
                this.portPollerBound,
                this.portTimerDelay
            );
        }
        return this.port;
    },

    getPort: function() {
        return this.port !== null ? this.port : this.createPort();
    },

    send: function(channel, msg) {
        // Too large a gap between the last request and the last response means
        // the main process is no longer reachable: memory leaks and bad
        // performance become a risk -- especially for long-lived, dynamic
        // pages. Guard against this.
        if ( this.pending.size > 64 ) {
            if ( (Date.now() - this.waitStartTime) > 60000 ) {
                vAPI.shutdown.exec();
            }
        }
        const port = this.getPort();
        if ( port === null ) {
            return Promise.resolve();
        }
        if ( this.pending.size === 0 ) {
            this.waitStartTime = Date.now();
        }
        const msgId = this.msgIdGenerator++;
        const promise = new Promise(resolve => {
            this.pending.set(msgId, resolve);
        });
        port.postMessage({ channel, msgId, msg });
        return promise;
    },
};

vAPI.shutdown.add(( ) => {
    vAPI.messaging.shutdown();
    window.vAPI = undefined;
});

/******************************************************************************/
/******************************************************************************/

}
// <<<<<<<< end of HUGE-IF-BLOCK








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;
