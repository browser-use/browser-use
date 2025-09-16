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

// https://bugs.chromium.org/p/v8/issues/detail?id=2869
//   orphanizeString is to work around String.slice() potentially causing
//   the whole raw filter list to be held in memory just because we cut out
//   the title as a substring.

function orphanizeString(s) {
    return JSON.parse(JSON.stringify(s));
}

/******************************************************************************/

class LineIterator {
    constructor(text, offset) {
        this.text = text;
        this.textLen = this.text.length;
        this.offset = offset || 0;
    }
    next(offset) {
        if ( offset !== undefined ) {
            this.offset += offset;
        }
        let lineEnd = this.text.indexOf('\n', this.offset);
        if ( lineEnd === -1 ) {
            lineEnd = this.text.indexOf('\r', this.offset);
            if ( lineEnd === -1 ) {
                lineEnd = this.textLen;
            }
        }
        const line = this.text.slice(this.offset, lineEnd);
        this.offset = lineEnd + 1;
        return line;
    }
    peek(n) {
        const offset = this.offset;
        return this.text.slice(offset, offset + n);
    }
    charCodeAt(offset) {
        return this.text.charCodeAt(this.offset + offset);
    }
    eot() {
        return this.offset >= this.textLen;
    }
}

/******************************************************************************/

// The field iterator is less CPU-intensive than when using native
// String.split().

class FieldIterator {
    constructor(sep) {
        this.text = '';
        this.sep = sep;
        this.sepLen = sep.length;
        this.offset = 0;
    }
    first(text) {
        this.text = text;
        this.offset = 0;
        return this.next();
    }
    next() {
        let end = this.text.indexOf(this.sep, this.offset);
        if ( end === -1 ) {
            end = this.text.length;
        }
        const field = this.text.slice(this.offset, end);
        this.offset = end + this.sepLen;
        return field;
    }
    remainder() {
        return this.text.slice(this.offset);
    }
}

/******************************************************************************/

export {
    FieldIterator,
    LineIterator,
    orphanizeString,
};
