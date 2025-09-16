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

import µb from './background.js';

/******************************************************************************/

µb.formatCount = function(count) {
    if ( typeof count !== 'number' ) { return ''; }
    const s = `${count}`;
    if ( count < 1000 ) { return s; }
    if ( count < 10000 ) {
        return '>' + s.slice(0,1) + 'k';
    }
    if ( count < 100000 ) {
        return s.slice(0,2) + 'k';
    }
    if ( count < 1000000 ) {
        return s.slice(0,3) + 'k';
    }
    return s.slice(0,-6) + 'M';
};

/******************************************************************************/

µb.dateNowToSensibleString = function() {
    const now = new Date(Date.now() - (new Date()).getTimezoneOffset() * 60000);
    return now.toISOString().replace(/\.\d+Z$/, '')
                            .replace(/:/g, '.')
                            .replace('T', '_');
};

/******************************************************************************/

µb.openNewTab = function(details) {
    if ( details.url.startsWith('logger-ui.html') ) {
        if ( details.shiftKey ) {
            this.changeUserSettings(
                'alwaysDetachLogger',
                !this.userSettings.alwaysDetachLogger
            );
        }
        if ( this.userSettings.alwaysDetachLogger ) {
            details.popup = this.hiddenSettings.loggerPopupType;
            const url = new URL(vAPI.getURL(details.url));
            url.searchParams.set('popup', '1');
            details.url = url.href;
            let popupLoggerBox;
            try {
                popupLoggerBox = JSON.parse(
                    vAPI.localStorage.getItem('popupLoggerBox')
                );
            } catch {
            }
            if ( popupLoggerBox !== undefined ) {
                details.box = popupLoggerBox;
            }
        }
    }
    vAPI.tabs.open(details);
};

/******************************************************************************/

// https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_Expressions

µb.escapeRegex = function(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
};

/******************************************************************************/

// TODO: properly compare arrays

µb.getModifiedSettings = function(edit, orig = {}) {
    const out = {};
    for ( const prop in edit ) {
        if ( Object.hasOwn(orig, prop) && edit[prop] !== orig[prop] ) {
            out[prop] = edit[prop];
        }
    }
    return out;
};

µb.settingValueFromString = function(orig, name, s) {
    if ( typeof name !== 'string' || typeof s !== 'string' ) { return; }
    if ( Object.hasOwn(orig, name) === false ) { return; }
    let r;
    switch ( typeof orig[name] ) {
    case 'boolean':
        if ( s === 'true' ) {
            r = true;
        } else if ( s === 'false' ) {
            r = false;
        }
        break;
    case 'string':
        r = s.trim();
        break;
    case 'number':
        if ( s.startsWith('0b') ) {
            r = parseInt(s.slice(2), 2);
        } else if ( s.startsWith('0x') ) {
            r = parseInt(s.slice(2), 16);
        } else {
            r = parseInt(s, 10);
        }
        if ( isNaN(r) ) { r = undefined; }
        break;
    default:
        break;
    }
    return r;
};
