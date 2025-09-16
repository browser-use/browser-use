;;
;; uBlock Origin - a comprehensive, efficient content blocker
;; Copyright (C) 2019-present Raymond Hill
;;
;; This program is free software: you can redistribute it and/or modify
;; it under the terms of the GNU General Public License as published by
;; the Free Software Foundation, either version 3 of the License, or
;; (at your option) any later version.
;;
;; This program is distributed in the hope that it will be useful,
;; but WITHOUT ANY WARRANTY; without even the implied warranty of
;; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
;; GNU General Public License for more details.
;;
;; You should have received a copy of the GNU General Public License
;; along with this program.  If not, see {http://www.gnu.org/licenses/}.
;;
;; Home: https://github.com/gorhill/uBlock
;; File: biditrie.wat
;; Description: WebAssembly code used by src/js/biditrie.js
;; How to compile: See README.md in this directory.

(module
;;
;; module start
;;

(memory (import "imports" "memory") 1)
(func $extraHandler (import "imports" "extraHandler") (param i32 i32 i32) (result i32))

;; Trie container
;;
;; Memory layout, byte offset:
;; const HAYSTACK_START = 0;
;; const HAYSTACK_SIZE = 8192;                         //   i32 /   i8
;; const HAYSTACK_SIZE_SLOT = HAYSTACK_SIZE >>> 2;     //  2048 / 8192
;; const TRIE0_SLOT     = HAYSTACK_SIZE_SLOT + 1;      //  2049 / 8196
;; const TRIE1_SLOT     = HAYSTACK_SIZE_SLOT + 2;      //  2050 / 8200
;; const CHAR0_SLOT     = HAYSTACK_SIZE_SLOT + 3;      //  2051 / 8204
;; const CHAR1_SLOT     = HAYSTACK_SIZE_SLOT + 4;      //  2052 / 8208
;; const RESULT_L_SLOT  = HAYSTACK_SIZE_SLOT + 5;      //  2053 / 8212
;; const RESULT_R_SLOT  = HAYSTACK_SIZE_SLOT + 6;      //  2054 / 8216
;; const RESULT_IU_SLOT = HAYSTACK_SIZE_SLOT + 7;      //  2055 / 8220
;; const TRIE0_START    = HAYSTACK_SIZE_SLOT + 8 << 2; //         8224
;;

;;
;; Public functions
;;

;;
;; unsigned int matches(icell, ai)
;;
;; Test whether the trie at icell matches the haystack content at position ai.
;;
(func (export "matches")
    (param $icell i32)          ;; start offset in haystack
    (param $ai i32)             ;; offset in haystack
    (result i32)                ;; result: 0 = no match, 1 = match
    (local $char0 i32)
    (local $aR i32)
    (local $al i32)
    (local $bl i32)
    (local $x i32)
    (local $y i32)
    ;; trie index is a uint32 offset, need to convert to uint8 offset
    local.get $icell
    i32.const 2
    i32.shl
    local.set $icell
    ;; const buf32 = this.buf32;
    ;; const buf8 = this.buf8;
    ;; const char0 = buf32[CHAR0_SLOT];
    i32.const 8204
    i32.load align=4
    local.set $char0
    ;; const aR = buf32[HAYSTACK_SIZE_SLOT];
    i32.const 8192
    i32.load align=4
    local.set $aR
    ;; let al = ai;
    local.get $ai
    local.set $al
    block $matchFound
    block $matchNotFound
    ;; for (;;) {
    loop $mainLoop
        ;; x = buf8[al];
        local.get $al
        i32.load8_u
        local.set $x
        ;; al += 1;
        local.get $al
        i32.const 1
        i32.add
        local.set $al
        ;; // find matching segment
        ;; for (;;) {
        block $nextSegment loop $findSegment
            ;; y = buf32[icell+SEGMENT_INFO];
            local.get $icell
            i32.load offset=8 align=4
            local.tee $y
            ;; bl = char0 + (y & 0x00FFFFFF);
            i32.const 0x00FFFFFF
            i32.and
            local.get $char0
            i32.add
            local.tee $bl
            ;; if ( buf8[bl] === x ) {
            i32.load8_u
            local.get $x
            i32.eq
            if
                ;; y = (y >>> 24) - 1;
                local.get $y
                i32.const 24
                i32.shr_u
                i32.const 1
                i32.sub
                local.tee $y
                ;; if ( n !== 0 ) {
                if
                    ;; x = al + y;
                    local.get $y
                    local.get $al
                    i32.add
                    local.tee $x
                    ;; if ( x > aR ) { return 0; }
                    local.get $aR
                    i32.gt_u
                    br_if $matchNotFound
                    ;; for (;;) {
                    loop
                        ;; bl += 1;
                        local.get $bl
                        i32.const 1
                        i32.add
                        local.tee $bl
                        ;; if ( buf8[bl] !== buf8[al] ) { return 0; }
                        i32.load8_u
                        local.get $al
                        i32.load8_u
                        i32.ne
                        br_if $matchNotFound
                        ;; al += 1;
                        local.get $al
                        i32.const 1
                        i32.add
                        local.tee $al
                        ;; if ( al === x ) { break; }
                        local.get $x
                        i32.ne
                        br_if 0
                    end
                ;; }
                end
                br $nextSegment
            end
            ;; icell = buf32[icell+CELL_OR];
            local.get $icell
            i32.load offset=4 align=4
            i32.const 2
            i32.shl
            local.tee $icell
            ;; if ( icell === 0 ) { return 0; }
            i32.eqz
            br_if $matchNotFound
            br $findSegment
        ;; }
        end end
        ;; // next segment
        ;; icell = buf32[icell+CELL_AND];
        local.get $icell
        i32.load align=4
        i32.const 2
        i32.shl
        local.tee $icell
        ;; const x = buf32[icell+BCELL_EXTRA];
        i32.load offset=8 align=4
        local.tee $x
        ;; if ( x <= BCELL_EXTRA_MAX ) {
        i32.const 0x00FFFFFF
        i32.le_u
        if
            ;; if ( x !== 0 && this.matchesExtra(ai, al, x) !== 0 ) {
            ;;     return 1;
            ;; }
            local.get $x
            if
                local.get $ai
                local.get $al
                local.get $x
                call $matchesExtra
                br_if $matchFound
            end
            ;; x = buf32[icell+BCELL_ALT_AND];
            local.get $icell
            i32.load offset=4 align=4
            i32.const 2
            i32.shl
            local.tee $x
            ;; if ( x !== 0 && this.matchesLeft(x, ai, al) !== 0 ) {
            if
                local.get $x
                local.get $ai
                local.get $al
                call $matchesLeft
                br_if $matchFound
            ;; }
            end
            ;; icell = buf32[icell+BCELL_NEXT_AND];
            local.get $icell
            i32.load align=4
            i32.const 2
            i32.shl
            local.tee $icell
            ;; if ( icell === 0 ) { return 0; }
            i32.eqz
            br_if $matchNotFound
        ;; }
        end
        ;; if ( al === aR ) { return 0; }
        local.get $al
        local.get $aR
        i32.ne
        br_if $mainLoop
    ;; }
    end ;; $mainLoop
    end ;; $matchNotFound
    i32.const 0
    return
    end ;; $matchFound
    i32.const 1
    return
)

;;
;; unsigned int matchesLeft(icell, ar, r)
;;
;; Test whether the trie at icell matches the haystack content at position ai.
;;
(func $matchesLeft
    (param $icell i32)          ;; start offset in haystack
    (param $ar i32)             ;; offset of where to start in haystack
    (param $r i32)              ;; right bound of match so far
    (result i32)                ;; result: 0 = no match, 1 = match
    (local $char0 i32)
    (local $bl i32)
    (local $br i32)
    (local $x i32)
    (local $y i32)
    ;; const buf32 = this.buf32;
    ;; const buf8 = this.buf8;
    ;; const char0 = buf32[CHAR0_SLOT];
    i32.const 8204
    i32.load align=4
    local.set $char0
    block $matchFound
    block $matchNotFound
    ;; for (;;) {
    loop $mainLoop
        ;; if ( ar === 0 ) { return 0; }
        local.get $ar
        i32.eqz
        br_if $matchNotFound
        ;; ar -= 1;
        local.get $ar
        i32.const 1
        i32.sub
        local.tee $ar
        ;; x = buf8[ar];
        i32.load8_u
        local.set $x
        ;; // find matching segment
        ;; for (;;) {
        block $nextSegment loop $findSegment
            ;; y = buf32[icell+SEGMENT_INFO];
            local.get $icell
            i32.load offset=8 align=4
            local.tee $y
            ;; br = char0 + (y & 0x00FFFFFF);
            i32.const 0x00FFFFFF
            i32.and
            local.get $char0
            i32.add
            local.tee $br
            ;; y = (y >>> 24) - 1;
            local.get $y
            i32.const 24
            i32.shr_u
            i32.const 1
            i32.sub
            local.tee $y
            ;; br += y;
            i32.add
            local.tee $br
            ;; if ( buf8[br] === x ) {
            i32.load8_u
            local.get $x
            i32.eq
            if
                ;; // all characters in segment must match
                ;; if ( y !== 0 ) {
                local.get $y
                if
                    ;; x = ar - y;
                    local.get $ar
                    local.get $y
                    i32.sub
                    local.tee $x
                    ;; if ( x < 0 ) { return 0; }
                    i32.const 0
                    i32.lt_s
                    br_if $matchNotFound
                    ;; for (;;) {
                    loop
                        ;; ar -= 1; br -= 1;
                        ;; if ( buf8[ar] !== buf8[br] ) { return 0; }
                        local.get $ar
                        i32.const 1
                        i32.sub
                        local.tee $ar
                        i32.load8_u
                        local.get $br
                        i32.const 1
                        i32.sub
                        local.tee $br
                        i32.load8_u
                        i32.ne
                        br_if $matchNotFound
                        ;; if ( ar === x ) { break; }
                        local.get $ar
                        local.get $x
                        i32.ne
                        br_if 0
                    end
                ;; }
                end
                br $nextSegment
            end
            ;; icell = buf32[icell+CELL_OR];
            local.get $icell
            i32.load offset=4 align=4
            i32.const 2
            i32.shl
            local.tee $icell
            ;; if ( icell === 0 ) { return 0; }
            i32.eqz
            br_if $matchNotFound
            br $findSegment
        ;; }
        end end
        ;; // next segment
        ;; icell = buf32[icell+CELL_AND];
        local.get $icell
        i32.load align=4
        i32.const 2
        i32.shl
        local.tee $icell
        ;; const x = buf32[icell+BCELL_EXTRA];
        i32.load offset=8 align=4
        local.tee $x
        ;; if ( x <= BCELL_EXTRA_MAX ) {
        i32.const 0x00FFFFFF
        i32.le_u
        if
            ;; if ( x !== 0 && this.matchesExtra(ar, r, x) !== 0 ) {
            ;;     return 1;
            ;; }
            local.get $x
            if
                local.get $ar
                local.get $r
                local.get $x
                call $matchesExtra
                br_if $matchFound
            end
            ;; icell = buf32[icell+BCELL_NEXT_AND];
            local.get $icell
            i32.load align=4
            i32.const 2
            i32.shl
            local.tee $icell
            ;; if ( icell === 0 ) { return 0; }
            i32.eqz
            br_if $matchNotFound
        ;; }
        end
        br $mainLoop
    ;; }
    end ;; $mainLoop
    end ;; $matchNotFound
    i32.const 0
    return
    end ;; $matchFound
    i32.const 1
    return
)

;;
;; int matchExtra(l, r, ix)
;;
;; Test whether extra handler returns a match.
;;
(func $matchesExtra
    (param $l i32)              ;; left bound of match so far
    (param $r i32)              ;; right bound of match so far
    (param $ix i32)             ;; extra token
    (result i32)                ;; result: 0 = no match, 1 = match
    (local $iu i32)             ;; filter unit
    block $fail
    block $succeed
    ;; if ( ix !== 1 ) {
    ;;     const iu = this.extraHandler(l, r, ix);
    ;;     if ( iu === 0 ) { return 0; }
    local.get $ix
    i32.const 1
    i32.ne
    if
        local.get $l
        local.get $r
        local.get $ix
        call $extraHandler
        local.tee $iu
        i32.eqz
        br_if $fail
    ;; } else {
    ;;     iu = -1;
    else
        i32.const -1
        local.set $iu
    ;; }
    end
    ;; this.buf32[RESULT_IU_SLOT] = iu;
    i32.const 8220
    local.get $iu
    i32.store align=4
    ;; this.buf32[RESULT_L_SLOT] = l;
    i32.const 8212
    local.get $l
    i32.store align=4
    ;; this.buf32[RESULT_R_SLOT] = r;
    i32.const 8216
    local.get $r
    i32.store align=4
    end ;; $succeed
    i32.const 1
    return
    end ;; $fail
    i32.const 0
)

;;
;; unsigned int startsWith(haystackLeft, haystackRight, needleLeft, needleLen)
;;
;; Test whether the string at needleOffset and of length needleLen matches
;; the haystack at offset haystackOffset.
;;
(func (export "startsWith")
    (param $haystackLeft i32)   ;; start offset in haystack
    (param $haystackRight i32)  ;; end offset in haystack
    (param $needleLeft i32)     ;; start of needle in character buffer
    (param $needleLen i32)      ;; number of characters to match
    (result i32)                ;; result: 0 = no match, 1 = match
    (local $needleRight i32)
    block $fail
    block $succeed
    ;;
    ;; if ( haystackLeft < 0 || (haystackLeft + needleLen) > haystackRight ) {
    ;;     return 0;
    ;; }
    local.get $haystackLeft
    i32.const 0
    i32.lt_s
    br_if $fail
    local.get $haystackLeft
    local.get $needleLen
    i32.add
    local.get $haystackRight
    i32.gt_u
    br_if $fail
    ;; const charCodes = this.buf8;
    ;; needleLeft += this.buf32[CHAR0_SLOT];
    local.get $needleLeft
    i32.const 8204              ;; CHAR0_SLOT memory address
    i32.load align=4            ;; CHAR0 memory address
    i32.add                     ;; needle memory address
    local.tee $needleLeft
    ;; const needleRight = needleLeft + needleLen;
    local.get $needleLen
    i32.add
    local.set $needleRight
    ;; while ( charCodes[haystackLeft] === charCodes[needleLeft] ) {
    loop $compare
        local.get $haystackLeft
        i32.load8_u
        local.get $needleLeft
        i32.load8_u
        i32.ne
        br_if $fail
        ;; needleLeft += 1;
        local.get $needleLeft
        i32.const 1
        i32.add
        local.tee $needleLeft
        ;; if ( needleLeft === needleRight ) { return 1; }
        local.get $needleRight
        i32.eq
        br_if $succeed
        ;; haystackLeft += 1;
        i32.const 1
        local.get $haystackLeft
        i32.add
        local.set $haystackLeft
        br $compare
    end
    ;; }
    ;; return 1;
    end ;; $succeed
    i32.const 1
    return
    ;; return 0;
    end ;; $fail
    i32.const 0
)

;;
;; int indexOf(haystackLeft, haystackEnd, needleLeft, needleLen)
;;
;; Test whether the string at needleOffset and of length needleLen is found in
;; the haystack at or to the left of haystackLeft, but not farther than
;; haystackEnd.
;;
(func (export "indexOf")
    (param $haystackLeft i32)   ;; start offset in haystack
    (param $haystackEnd i32)    ;; end offset in haystack
    (param $needleLeft i32)     ;; start of needle in character buffer
    (param $needleLen i32)      ;; number of characters to match
    (result i32)                ;; result: index of match, -1 = no match
    (local $needleRight i32)
    (local $i i32)
    (local $j i32)
    (local $c0 i32)
    block $fail
    block $succeed
    ;; if ( needleLen === 0 ) { return haystackLeft; }
    local.get $needleLen
    i32.eqz
    br_if $succeed
    ;; haystackEnd -= needleLen;
    local.get $haystackEnd
    local.get $needleLen
    i32.sub
    local.tee $haystackEnd
    ;; if ( haystackEnd < haystackLeft ) { return -1; }
    local.get $haystackLeft
    i32.lt_s
    br_if $fail
    ;; needleLeft += this.buf32[CHAR0_SLOT];
    local.get $needleLeft
    i32.const 8204              ;; CHAR0_SLOT memory address
    i32.load align=4            ;; CHAR0 memory address
    i32.add                     ;; needle memory address
    local.tee $needleLeft
    ;; const needleRight = needleLeft + needleLen;
    local.get $needleLen
    i32.add
    local.set $needleRight
    ;; const charCodes = this.buf8;
    ;; for (;;) {
    loop $mainLoop
        ;; let i = haystackLeft;
        ;; let j = needleLeft;
        local.get $haystackLeft
        local.set $i
        local.get $needleLeft
        local.set $j
        ;; while ( charCodes[i] === charCodes[j] ) {
        block $breakMatchChars loop $matchChars
            local.get $i
            i32.load8_u
            local.get $j
            i32.load8_u
            i32.ne
            br_if $breakMatchChars
            ;; j += 1;
            local.get $j
            i32.const 1
            i32.add
            local.tee $j
            ;; if ( j === needleRight ) { return haystackLeft; }
            local.get $needleRight
            i32.eq
            br_if $succeed
            ;; i += 1;
            local.get $i
            i32.const 1
            i32.add
            local.set $i
            br $matchChars
        ;; }
        end end
        ;; haystackLeft += 1;
        local.get $haystackLeft
        i32.const 1
        i32.add
        local.tee $haystackLeft
        ;; if ( haystackLeft > haystackEnd ) { break; }
        local.get $haystackEnd
        i32.gt_u
        br_if $fail
        br $mainLoop
    ;; }
    end
    end ;; $succeed
    local.get $haystackLeft
    return
    end ;; $fail
    ;; return -1;
    i32.const -1
)

;;
;; int lastIndexOf(haystackBeg, haystackEnd, needleLeft, needleLen)
;;
;; Test whether the string at needleOffset and of length needleLen is found in
;; the haystack at or to the right of haystackBeg, but not farther than
;; haystackEnd.
;;
(func (export "lastIndexOf")
    (param $haystackBeg i32)    ;; start offset in haystack
    (param $haystackEnd i32)    ;; end offset in haystack
    (param $needleLeft i32)     ;; start of needle in character buffer
    (param $needleLen i32)      ;; number of characters to match
    (result i32)                ;; result: index of match, -1 = no match
    (local $haystackLeft i32)
    (local $needleRight i32)
    (local $i i32)
    (local $j i32)
    (local $c0 i32)
    ;; if ( needleLen === 0 ) { return haystackBeg; }
    local.get $needleLen
    i32.eqz
    if
        local.get $haystackBeg
        return
    end
    block $fail
    block $succeed
    ;; let haystackLeft = haystackEnd - needleLen;
    local.get $haystackEnd
    local.get $needleLen
    i32.sub
    local.tee $haystackLeft
    ;; if ( haystackLeft < haystackBeg ) { return -1; }
    local.get $haystackBeg
    i32.lt_s
    br_if $fail
    ;; needleLeft += this.buf32[CHAR0_SLOT];
    local.get $needleLeft
    i32.const 8204              ;; CHAR0_SLOT memory address
    i32.load align=4            ;; CHAR0 memory address
    i32.add                     ;; needle memory address
    local.tee $needleLeft
    ;; const needleRight = needleLeft + needleLen;
    local.get $needleLen
    i32.add
    local.set $needleRight
    ;; const charCodes = this.buf8;
    ;; for (;;) {
    loop $mainLoop
        ;; let i = haystackLeft;
        ;; let j = needleLeft;
        local.get $haystackLeft
        local.set $i
        local.get $needleLeft
        local.set $j
        ;; while ( charCodes[i] === charCodes[j] ) {
        block $breakMatchChars loop $matchChars
            local.get $i
            i32.load8_u
            local.get $j
            i32.load8_u
            i32.ne
            br_if $breakMatchChars
            ;; j += 1;
            local.get $j
            i32.const 1
            i32.add
            local.tee $j
            ;; if ( j === needleRight ) { return haystackLeft; }
            local.get $needleRight
            i32.eq
            br_if $succeed
            ;; i += 1;
            local.get $i
            i32.const 1
            i32.add
            local.set $i
            br $matchChars
        ;; }
        end end
        ;; if ( haystackLeft === haystackBeg ) { break; }
        ;; haystackLeft -= 1;
        local.get $haystackLeft
        local.get $haystackBeg
        i32.eq
        br_if $fail
        local.get $haystackLeft
        i32.const 1
        i32.sub
        local.set $haystackLeft
        br $mainLoop
    ;; }
    end
    end ;; $succeed
    local.get $haystackLeft
    return
    end ;; $fail
    ;; return -1;
    i32.const -1
)

;;
;; module end
;;
)
