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

// https://www.reddit.com/r/uBlockOrigin/comments/oq6kt5/ubo_loads_generic_filter_instead_of_specific/
//   Ensure blocks of content are sorted in ascending id order, such that the
//   specific cosmetic filters will be found (and thus reported) before the
//   generic ones.

const serialize = JSON.stringify;
const unserialize = JSON.parse;

const blockStartPrefix = '#block-start-';  // ensure no special regex characters
const blockEndPrefix = '#block-end-';      // ensure no special regex characters

class CompiledListWriter {
    constructor() {
        this.blockId = undefined;
        this.block = undefined;
        this.blocks = new Map();
        this.properties = new Map();
    }
    push(args) {
        this.block.push(serialize(args));
    }
    pushMany(many) {
        for ( const args of many ) {
            this.block.push(serialize(args));
        }
    }
    last() {
        if ( Array.isArray(this.block) && this.block.length !== 0 ) {
            return this.block[this.block.length - 1];
        }
    }
    select(blockId) {
        if ( blockId === this.blockId ) { return; }
        this.blockId = blockId;
        this.block = this.blocks.get(blockId);
        if ( this.block === undefined ) {
            this.blocks.set(blockId, (this.block = []));
        }
        return this;
    }
    toString() {
        const result = [];
        const sortedBlocks =
            Array.from(this.blocks).sort((a, b) => a[0] - b[0]);
        for ( const [ id, lines ] of sortedBlocks ) {
            if ( lines.length === 0 ) { continue; }
            result.push(
                blockStartPrefix + id,
                lines.join('\n'),
                blockEndPrefix + id
            );
        }
        return result.join('\n');
    }
    static serialize(arg) {
        return serialize(arg);
    }
}

class CompiledListReader {
    constructor(raw, blockId) {
        this.block = '';
        this.len = 0;
        this.offset = 0;
        this.line = '';
        this.blocks = new Map();
        this.properties = new Map();
        const reBlockStart = new RegExp(`^${blockStartPrefix}([\\w:]+)\\n`, 'gm');
        let match = reBlockStart.exec(raw);
        while ( match !== null ) {
            const sectionId = match[1];
            const beg = match.index + match[0].length;
            const end = raw.indexOf(blockEndPrefix + sectionId, beg);
            this.blocks.set(sectionId, raw.slice(beg, end));
            reBlockStart.lastIndex = end;
            match = reBlockStart.exec(raw);
        }
        if ( blockId !== undefined ) {
            this.select(blockId);
        }
    }
    next() {
        if ( this.offset === this.len ) {
            this.line = '';
            return false;
        }
        let pos = this.block.indexOf('\n', this.offset);
        if ( pos !== -1 ) {
            this.line = this.block.slice(this.offset, pos);
            this.offset = pos + 1;
        } else {
            this.line = this.block.slice(this.offset);
            this.offset = this.len;
        }
        return true;
    }
    select(blockId) {
        this.block = this.blocks.get(blockId) || '';
        this.len = this.block.length;
        this.offset = 0;
        return this;
    }
    fingerprint() {
        return this.line;
    }
    args() {
        return unserialize(this.line);
    }
    static unserialize(arg) {
        return unserialize(arg);
    }
}

/******************************************************************************/

export {
    CompiledListReader,
    CompiledListWriter,
};
