;;
;; uBlock Origin - a browser extension to block requests.
;; Copyright (C) 2019-present Raymond Hill
;;
;; License: pick the one which suits you:
;;   GPL v3 see <https://www.gnu.org/licenses/gpl.html>
;;   APL v2 see <http://www.apache.org/licenses/LICENSE-2.0>
;;
;; Home: https://github.com/gorhill/publicsuffixlist.js
;; File: publicsuffixlist.wat
;;
;; Description: WebAssembly implementation for core lookup method in
;;              publicsuffixlist.js
;;
;; How to compile:
;;
;;     wat2wasm publicsuffixlist.wat -o publicsuffixlist.wasm
;;
;; The `wat2wasm` tool can be downloaded from an official WebAssembly
;; project:
;; https://github.com/WebAssembly/wabt/releases


(module
;;
;; module start
;;

(memory (import "imports" "memory") 1)

;;
;; Tree encoding in array buffer:
;;
;;  Node:
;;  +  u8: length of char data
;;  +  u8: flags => bit 0: is_publicsuffix, bit 1: is_exception
;;  + u16: length of array of children
;;  + u32: char data or offset to char data
;;  + u32: offset to array of children
;;  = 12 bytes
;;
;;                                      // i32 /  i8
;; const HOSTNAME_SLOT         = 0;     // jshint ignore:line
;; const LABEL_INDICES_SLOT    = 256;   //  -- / 256
;; const RULES_PTR_SLOT        = 100;   // 100 / 400
;; const SUFFIX_NOT_FOUND_SLOT = 399;   //  -- / 399
;; const CHARDATA_PTR_SLOT     = 101;   // 101 / 404
;; const EMPTY_STRING          = '';
;; const SELFIE_MAGIC          = 2;
;;

;;
;; Public functions
;;

;;
;; unsigned int getPublicSuffixPos()
;;
;; Returns an offset to the start of the public suffix.
;;
(func (export "getPublicSuffixPos")
    (result i32)                ;; result = match index, -1 = miss
    (local $iCharData i32)      ;; offset to start of character data
    (local $iNode i32)          ;; offset to current node
    (local $iLabel i32)         ;; offset to label indices
    (local $cursorPos i32)      ;; position of cursor within hostname argument
    (local $labelBeg i32)
    (local $labelLen i32)
    (local $nCandidates i32)
    (local $iCandidates i32)
    (local $iFound i32)
    (local $l i32)
    (local $r i32)
    (local $d i32)
    (local $iCandidate i32)
    (local $iCandidateNode i32)
    (local $candidateLen i32)
    (local $iCandidateChar i32)
    (local $_1 i32)
    (local $_2 i32)
    (local $_3 i32)
    ;;
    ;; const iCharData = buf32[CHARDATA_PTR_SLOT];
    i32.const 404
    i32.load
    local.set $iCharData
    ;; let iNode = pslBuffer32[RULES_PTR_SLOT];
    i32.const 400
    i32.load
    i32.const 2
    i32.shl
    local.set $iNode
    ;; let iLabel = LABEL_INDICES_SLOT;
    i32.const 256
    local.set $iLabel
    ;; let cursorPos = -1;
    i32.const -1
    local.set $cursorPos
    ;; label-lookup loop
    ;; for (;;) {
    block $labelLookupDone loop $labelLookup
        ;; // Extract label indices
        ;; const labelBeg = buf8[iLabel+1];
        ;; const labelLen = buf8[iLabel+0] - labelBeg;
        local.get $iLabel
        i32.load8_u
        local.get $iLabel
        i32.load8_u offset=1
        local.tee $labelBeg
        i32.sub
        local.set $labelLen
        ;; // Match-lookup loop: binary search
        ;; let r = buf32[iNode+0] >>> 16;
        ;; if ( r === 0 ) { break; }
        local.get $iNode
        i32.load16_u offset=2
        local.tee $r
        i32.eqz
        br_if $labelLookupDone
        ;; const iCandidates = buf32[iNode+2];
        local.get $iNode
        i32.load offset=8
        i32.const 2
        i32.shl
        local.set $iCandidates
        ;; let l = 0;
        ;; let iFound = 0;
        i32.const 0
        local.tee $l
        local.set $iFound
        ;; while ( l < r ) {
        block $binarySearchDone loop $binarySearch
            local.get $l
            local.get $r
            i32.ge_u
            br_if $binarySearchDone
            ;; const iCandidate = l + r >>> 1;
            local.get $l
            local.get $r
            i32.add
            i32.const 1
            i32.shr_u
            local.tee $iCandidate
            ;; const iCandidateNode = iCandidates + iCandidate + (iCandidate << 1);
            i32.const 2
            i32.shl
            local.tee $_1
            local.get $_1
            i32.const 1
            i32.shl
            i32.add
            local.get $iCandidates
            i32.add
            local.tee $iCandidateNode
            ;; const candidateLen = buf32[iCandidateNode+0] & 0x000000FF;
            i32.load8_u
            local.set $candidateLen
            ;; let d = labelLen - candidateLen;
            local.get $labelLen
            local.get $candidateLen
            i32.sub
            local.tee $d
            ;; if ( d === 0 ) {
            i32.eqz
            if
                ;; const iCandidateChar = candidateLen <= 4
                local.get $candidateLen
                i32.const 4
                i32.le_u
                if
                    ;; ? iCandidateNode + 1 << 2
                    local.get $iCandidateNode
                    i32.const 4
                    i32.add
                    local.set $iCandidateChar
                else
                    ;; : buf32[CHARDATA_PTR_SLOT] + buf32[iCandidateNode+1];
                    local.get $iCharData
                    local.get $iCandidateNode
                    i32.load offset=4
                    i32.add
                    local.set $iCandidateChar
                end
                ;; for ( let i = 0; i < labelLen; i++ ) {
                local.get $labelBeg
                local.tee $_1
                local.get $labelLen
                i32.add
                local.set $_3
                local.get $iCandidateChar
                local.set $_2
                block $findDiffDone loop $findDiff
                    ;; d = buf8[labelBeg+i] - buf8[iCandidateChar+i];
                    ;; if ( d !== 0 ) { break; }
                    local.get $_1
                    i32.load8_u
                    local.get $_2
                    i32.load8_u
                    i32.sub
                    local.tee $d
                    br_if $findDiffDone
                    local.get $_1
                    i32.const 1
                    i32.add
                    local.tee $_1
                    local.get $_3
                    i32.eq
                    br_if $findDiffDone
                    local.get $_2
                    i32.const 1
                    i32.add
                    local.set $_2
                    br $findDiff
                ;; }
                end end
            ;; }
            end
            ;; if ( d < 0 ) {
            ;;     r = iCandidate;
            local.get $d
            i32.const 0
            i32.lt_s
            if
                local.get $iCandidate
                local.set $r
                br $binarySearch
            end
            ;; } else if ( d > 0 ) {
            ;;     l = iCandidate + 1;
            local.get $d
            i32.const 0
            i32.gt_s
            if
                local.get $iCandidate
                i32.const 1
                i32.add
                local.set $l
                br $binarySearch
            end
            ;; } else /* if ( d === 0 ) */ {
            ;;     iFound = iCandidateNode;
            ;;     break;
            ;; }
            local.get $iCandidateNode
            local.set $iFound
        end end
        ;; }
        ;; // 2. If no rules match, the prevailing rule is "*".
        ;; if ( iFound === 0 ) {
        ;;     if ( buf32[iCandidates + 1] !== 0x2A /* '*' */ ) { break; }
        ;;     buf8[SUFFIX_NOT_FOUND_SLOT] = 1;
        ;;     iFound = iCandidates;
        ;; }
        local.get $iFound
        i32.eqz
        if
            local.get $iCandidates
            i32.load offset=4
            i32.const 0x2A
            i32.ne
            br_if $labelLookupDone
            i32.const 399
            i32.const 1
            i32.store8
            local.get $iCandidates
            local.set $iFound
        end
        ;; iNode = iFound;
        local.get $iFound
        local.tee $iNode
        ;; // 5. If the prevailing rule is a exception rule, modify it by
        ;; //    removing the leftmost label.
        ;; if ( (buf32[iNode+0] & 0x00000200) !== 0 ) {
        ;;     if ( iLabel > LABEL_INDICES_SLOT ) {
        ;;         return iLabel - 2;
        ;;     }
        ;;     break;
        ;; }
        i32.load8_u offset=1
        local.tee $_1
        i32.const 0x02
        i32.and
        if
            local.get $iLabel
            i32.const 256
            i32.gt_u
            if
                local.get $iLabel
                i32.const -2
                i32.add
                return
            end
            br $labelLookupDone
        end
        ;; if ( (buf32[iNode+0] & 0x00000100) !== 0 ) {
        ;;     cursorPos = labelBeg;
        ;; }
        local.get $_1
        i32.const 0x01
        i32.and
        if
            local.get $iLabel
            local.set $cursorPos
        end
        ;; if ( labelBeg === 0 ) { break; }
        local.get $labelBeg
        i32.eqz
        br_if $labelLookupDone
        ;; iLabel += 2;
        local.get $iLabel
        i32.const 2
        i32.add
        local.set $iLabel
        br $labelLookup
    end end
    local.get $cursorPos
)

;;
;; module end
;;
)
