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

export class MRUCache {
    constructor(maxSize) {
        this.maxSize = maxSize;
        this.array = [];
        this.map = new Map();
        this.resetTime = Date.now();
    }
    add(key, value) {
        const found = this.map.has(key);
        this.map.set(key, value);
        if ( found ) { return; }
        if ( this.array.length === this.maxSize ) {
            this.map.delete(this.array.pop());
        }
        this.array.unshift(key);
    }
    remove(key) {
        if ( this.map.delete(key) === false ) { return; }
        this.array.splice(this.array.indexOf(key), 1);
    }
    lookup(key) {
        const value = this.map.get(key);
        if ( value === undefined ) { return; }
        if ( this.array[0] === key ) { return value; }
        const i = this.array.indexOf(key);
        this.array.copyWithin(1, 0, i);
        this.array[0] = key;
        return value;
    }
    reset() {
        this.array = [];
        this.map.clear();
        this.resetTime = Date.now();
    }
}
