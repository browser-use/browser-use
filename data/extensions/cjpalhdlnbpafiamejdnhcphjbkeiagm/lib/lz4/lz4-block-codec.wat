;;
;; lz4-block-codec.wat: a WebAssembly implementation of LZ4 block format codec
;; Copyright (C) 2018 Raymond Hill
;;
;; BSD-2-Clause License (http://www.opensource.org/licenses/bsd-license.php)
;;
;; Redistribution and use in source and binary forms, with or without
;; modification, are permitted provided that the following conditions are
;; met:
;; 
;;   1. Redistributions of source code must retain the above copyright
;; notice, this list of conditions and the following disclaimer.
;; 
;;   2. Redistributions in binary form must reproduce the above
;; copyright notice, this list of conditions and the following disclaimer
;; in the documentation and/or other materials provided with the
;; distribution.
;; 
;; THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
;; "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
;; LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
;; A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
;; OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
;; SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
;; LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
;; DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
;; THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
;; (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
;; OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
;;
;; Home: https://github.com/gorhill/lz4-wasm
;;
;; I used the same license as the one picked by creator of LZ4 out of respect
;; for his creation, see https://lz4.github.io/lz4/
;;

(module
;;
;; module start
;;

;; (func $log (import "imports" "log") (param i32 i32 i32))

(memory (export "memory") 1)

;;
;; Public functions
;;

;;
;; Return an offset to the first byte of usable linear memory.
;; Might be useful in the future to reserve memory space for whatever purpose,
;; like config variables, etc.
;;
(func $getLinearMemoryOffset (export "getLinearMemoryOffset") 
    (result i32)
    i32.const 0
)

;;
;; unsigned int lz4BlockEncodeBound()
;;
;; Return the maximum size of the output buffer holding the compressed data.
;;
;; Reference implementation:
;; https://github.com/lz4/lz4/blob/dev/lib/lz4.h#L156
;;
(func (export "lz4BlockEncodeBound")
    (param $ilen i32)
    (result i32)
    local.get $ilen
    i32.const 0x7E000000
    i32.gt_u
    if
        i32.const 0
        return
    end
    local.get $ilen
    local.get $ilen
    i32.const 255
    i32.div_u
    i32.add
    i32.const 16
    i32.add
)

;;
;; unsigned int lz4BlockEncode(
;;     unsigned int inPtr,
;;     unsigned int ilen,
;;     unsigned int outPtr
;; )
;;
;; https://github.com/lz4/lz4/blob/dev/lib/lz4.c#L651
;;
;; The implementation below is modified from the reference one.
;; 
;; - There is no skip adjustment for repeated failure to find a match.
;; 
;; - All configurable values are hard-coded to match the generic version
;;   of the compressor.
;;
;; Note the size of the input block is NOT encoded in the output buffer, it
;; is for the caller to figure how they will save that information on
;; their side. At this point it is probably a trivial amount of work to
;; implement the LZ4 frame format, which encode the content size, but this
;; is for another day.
;;
(func $lz4BlockEncode (export "lz4BlockEncode")
    (param $inPtr i32)                  ;; pointer to start of input buffer
    (param $ilen i32)                   ;; size of input buffer
    (param $outPtr i32)                 ;; pointer to start of output buffer
    (result i32)
    (local $hashPtrBeg i32)             ;; start of hash buffer
    (local $hashPtr i32)                ;; current hash entry
    (local $anchorPtr i32)              ;; anchor position in input
    (local $inPtrEnd1 i32)              ;; point in input at which match-finding must cease
    (local $inPtrEnd2 i32)              ;; point in input at which match-length finding must cease
    (local $inPtrEnd i32)               ;; point to end of input
    (local $outPtrBeg i32)              ;; start of output buffer
    (local $refPtr i32)                 ;; start of match in input
    (local $seq32 i32)                  ;; 4-byte value from current input position
    (local $llen i32)                   ;; length of found literals
    (local $moffset i32)                ;; offset to found match from current input position
    (local $mlen i32)                   ;; length of found match
    local.get $ilen                     ;; empty input = empty output
    i32.const 0x7E000000                ;; max input size: 0x7E000000
    i32.gt_u
    if
        i32.const 0
        return
    end
    local.get $ilen                     ;; "blocks < 13 bytes cannot be compressed"
    i32.const 13
    i32.lt_u
    if
        i32.const 0
        return
    end
    call $getLinearMemoryOffset         ;; hash table is at start of usable memory
    local.set $hashPtrBeg
    local.get $inPtr
    local.tee $anchorPtr
    local.get $ilen
    i32.add
    local.tee $inPtrEnd
    i32.const -5                        ;; "The last 5 bytes are always literals."
    i32.add
    local.tee $inPtrEnd2
    i32.const -7                        ;; "The last match must start at least 12 bytes before end of block"
    i32.add
    local.set $inPtrEnd1
    local.get $outPtr
    local.set $outPtrBeg
    ;;
    ;; sequence processing loop
    ;;
    block $noMoreSequence loop $nextSequence
        local.get $inPtr
        local.get $inPtrEnd1
        i32.ge_u                        ;; 5 or less bytes left?
        br_if $noMoreSequence
        local.get $inPtr                ;; first sequence of 3 bytes before match-finding loop
        i32.load8_u
        i32.const 8
        i32.shl
        local.get $inPtr
        i32.load8_u offset=1
        i32.const 16
        i32.shl
        i32.or
        local.get $inPtr
        i32.load8_u offset=2
        i32.const 24
        i32.shl
        i32.or
        local.set $seq32
        ;;
        ;; match-finding loop
        ;;
        loop $findMatch block $noMatchFound
            local.get $inPtr
            local.get $inPtrEnd2
            i32.gt_u                    ;; less than 12 bytes left?
            br_if $noMoreSequence
            local.get $seq32            ;; update last byte of current sequence
            i32.const 8
            i32.shr_u
            local.get $inPtr
            i32.load8_u offset=3
            i32.const 24
            i32.shl
            i32.or
            local.tee $seq32
            i32.const 0x9E3779B1        ;; compute 16-bit hash
            i32.mul
            i32.const 16
            i32.shr_u                   ;; hash value is at top of stack
            i32.const 2                 ;; lookup refPtr at hash entry
            i32.shl
            local.get $hashPtrBeg
            i32.add
            local.tee $hashPtr
            i32.load
            local.set $refPtr
            local.get $hashPtr          ;; update hash entry with inPtr
            local.get $inPtr
            i32.store
            local.get $inPtr
            local.get $refPtr
            i32.sub
            local.tee $moffset          ;; remember match offset, we will need it in case of match
            i32.const 0xFFFF
            i32.gt_s                    ;; match offset > 65535 = unusable match
            br_if $noMatchFound
            ;;
            ;; confirm match: different sequences can yield same hash
            ;; compare-branch each byte to potentially save memory read ops
            ;;
            local.get $seq32            ;; byte 0
            i32.const 0xFF
            i32.and
            local.get $refPtr
            i32.load8_u
            i32.ne                      ;; refPtr[0] !== inPtr[0]
            br_if $noMatchFound
            local.get $seq32            ;; byte 1
            i32.const 8
            i32.shr_u
            i32.const 0xFF
            i32.and
            local.get $refPtr
            i32.load8_u offset=1
            i32.ne
            br_if $noMatchFound         ;; refPtr[1] !== inPtr[1]
            local.get $seq32            ;; byte 2
            i32.const 16
            i32.shr_u
            i32.const 0xFF
            i32.and
            local.get $refPtr
            i32.load8_u offset=2
            i32.ne                      ;; refPtr[2] !== inPtr[2]
            br_if $noMatchFound
            local.get $seq32            ;; byte 3
            i32.const 24
            i32.shr_u
            i32.const 0xFF
            i32.and
            local.get $refPtr
            i32.load8_u offset=3
            i32.ne                      ;; refPtr[3] !== inPtr[3]
            br_if $noMatchFound
            ;;
            ;; a valid match has been found at this point
            ;;
            local.get $inPtr            ;; compute length of literals
            local.get $anchorPtr
            i32.sub
            local.set $llen
            local.get $inPtr            ;; find match length
            i32.const 4                 ;; skip over confirmed 4-byte match
            i32.add
            local.set $inPtr
            local.get $refPtr
            i32.const 4
            i32.add
            local.tee $mlen             ;; remember refPtr to later compute match length
            local.set $refPtr
            block $endOfMatch loop      ;; scan input buffer until match ends
                local.get $inPtr
                local.get $inPtrEnd2
                i32.ge_u
                br_if $endOfMatch
                local.get $inPtr
                i32.load8_u
                local.get $refPtr
                i32.load8_u
                i32.ne
                br_if $endOfMatch
                local.get $inPtr
                i32.const 1
                i32.add
                local.set $inPtr
                local.get $refPtr
                i32.const 1
                i32.add
                local.set $refPtr
                br 0
            end end $endOfMatch
            ;; encode token
            local.get $outPtr           ;; output token
            local.get $llen
            local.get $refPtr
            local.get $mlen
            i32.sub
            local.tee $mlen
            call $writeToken
            local.get $outPtr
            i32.const 1
            i32.add
            local.set $outPtr
            local.get $llen             ;; encode/write length of literals if needed
            i32.const 15
            i32.ge_s
            if
                local.get $outPtr
                local.get $llen
                call $writeLength
                local.set $outPtr
            end
            ;; copy literals
            local.get $outPtr
            local.get $anchorPtr
            local.get $llen
            call $copy
            local.get $outPtr
            local.get $llen
            i32.add
            local.set $outPtr
            ;; encode match offset
            local.get $outPtr
            local.get $moffset
            i32.store8
            local.get $outPtr
            local.get $moffset
            i32.const 8
            i32.shr_u
            i32.store8 offset=1
            local.get $outPtr
            i32.const 2
            i32.add
            local.set $outPtr
            local.get $mlen             ;; encode/write length of match if needed
            i32.const 15
            i32.ge_s
            if
                local.get $outPtr
                local.get $mlen
                call $writeLength
                local.set $outPtr
            end
            local.get $inPtr            ;; advance anchor to current position
            local.set $anchorPtr
            br $nextSequence
        end $noMatchFound
        local.get $inPtr                ;; no match found: advance to next byte
        i32.const 1
        i32.add
        local.set $inPtr
        br $findMatch end               ;; match offset > 65535 = unusable match
    end end $noMoreSequence
    ;;
    ;; generate last (match-less) sequence if compression succeeded
    ;;
    local.get $outPtr
    local.get $outPtrBeg
    i32.eq
    if
        i32.const 0
        return
    end
    local.get $outPtr
    local.get $inPtrEnd
    local.get $anchorPtr
    i32.sub
    local.tee $llen
    i32.const 0
    call $writeToken
    local.get $outPtr
    i32.const 1
    i32.add
    local.set $outPtr
    local.get $llen
    i32.const 15
    i32.ge_u
    if
        local.get $outPtr
        local.get $llen
        call $writeLength
        local.set $outPtr
    end
    local.get $outPtr
    local.get $anchorPtr
    local.get $llen
    call $copy
    local.get $outPtr                   ;; return number of written bytes
    local.get $llen
    i32.add
    local.get $outPtrBeg
    i32.sub
)

;;
;; unsigned int lz4BlockDecode(
;;     unsigned int inPtr,
;;     unsigned int ilen
;;     unsigned int outPtr
;; )
;;
;; Reference:
;; https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md
;;
(func (export "lz4BlockDecode")
    (param $inPtr0 i32)                 ;; start of input buffer
    (param $ilen i32)                   ;; length of input buffer
    (param $outPtr0 i32)                ;; start of output buffer
    (result i32)
    (local $inPtr i32)                  ;; current position in input buffer
    (local $inPtrEnd i32)               ;; end of input buffer
    (local $outPtr i32)                 ;; current position in output buffer
    (local $matchPtr i32)               ;; position of current match
    (local $token i32)                  ;; sequence token
    (local $clen i32)                   ;; number of bytes to copy 
    (local $_ i32)                      ;; general purpose variable
    local.get $ilen                     ;; if ( ilen == 0 ) { return 0; }
    i32.eqz
    if
        i32.const 0
        return
    end
    local.get $inPtr0
    local.tee $inPtr                    ;; current position in input buffer
    local.get $ilen
    i32.add
    local.set $inPtrEnd
    local.get $outPtr0                  ;; start of output buffer
    local.set $outPtr                   ;; current position in output buffer
    block $noMoreSequence loop          ;; iterate through all sequences
        local.get $inPtr
        local.get $inPtrEnd
        i32.ge_u
        br_if $noMoreSequence           ;; break when nothing left to read in input buffer
        local.get $inPtr                ;; read token -- consume one byte
        i32.load8_u
        local.get $inPtr
        i32.const 1
        i32.add
        local.set $inPtr
        local.tee $token                ;; extract length of literals from token
        i32.const 4
        i32.shr_u
        local.tee $clen                 ;; consume extra length bytes if present
        i32.eqz
        if else
            local.get $clen
            i32.const 15
            i32.eq
            if loop
                local.get $inPtr
                i32.load8_u
                local.get $inPtr
                i32.const 1
                i32.add
                local.set $inPtr
                local.tee $_
                local.get $clen
                i32.add
                local.set $clen
                local.get $_
                i32.const 255
                i32.eq
                br_if 0
            end end
            local.get $outPtr           ;; copy literals to output buffer
            local.get $inPtr
            local.get $clen
            call $copy
            local.get $outPtr           ;; advance output buffer pointer past copy
            local.get $clen
            i32.add
            local.set $outPtr
            local.get $clen             ;; advance input buffer pointer past literals
            local.get $inPtr
            i32.add
            local.tee $inPtr
            local.get $inPtrEnd         ;; exit if this is the last sequence
            i32.eq
            br_if $noMoreSequence
        end
        local.get $outPtr               ;; read match offset
        local.get $inPtr
        i32.load8_u
        local.get $inPtr
        i32.load8_u offset=1
        i32.const 8
        i32.shl
        i32.or
        i32.sub
        local.tee $matchPtr
        local.get $outPtr               ;; match position can't be outside input buffer bounds
        i32.eq
        br_if $noMoreSequence
        local.get $matchPtr
        local.get $inPtrEnd
        i32.lt_u
        br_if $noMoreSequence
        local.get $inPtr                ;; advance input pointer past match offset bytes
        i32.const 2
        i32.add
        local.set $inPtr
        local.get $token                ;; extract length of match from token
        i32.const 15
        i32.and
        i32.const 4
        i32.add
        local.tee $clen
        i32.const 19                    ;; consume extra length bytes if present
        i32.eq
        if loop
            local.get $inPtr
            i32.load8_u
            local.get $inPtr
            i32.const 1
            i32.add
            local.set $inPtr
            local.tee $_
            local.get $clen
            i32.add
            local.set $clen
            local.get $_
            i32.const 255
            i32.eq
            br_if 0
        end end
        local.get $outPtr               ;; copy match to output buffer
        local.get $matchPtr
        local.get $clen
        call $copy
        local.get $clen                 ;; advance output buffer pointer past copy
        local.get $outPtr
        i32.add
        local.set $outPtr
        br 0
    end end $noMoreSequence
    local.get $outPtr                   ;; return number of written bytes
    local.get $outPtr0
    i32.sub
)

;;
;; Private functions
;;

;;
;; Encode a sequence token
;;
;; Reference documentation:
;; https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md
;;
(func $writeToken
    (param $outPtr i32)
    (param $llen i32)
    (param $mlen i32)
    local.get $outPtr
    local.get $llen
    i32.const 15
    local.get $llen
    i32.const 15
    i32.lt_u
    select
    i32.const 4
    i32.shl
    local.get $mlen
    i32.const 15
    local.get $mlen
    i32.const 15
    i32.lt_u
    select
    i32.or
    i32.store8
)

;;
;; Encode and output length bytes. The return value is the pointer following
;; the last byte written.
;;
;; Reference documentation:
;; https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md
;;
(func $writeLength
    (param $outPtr i32)
    (param $len i32)
    (result i32)
    local.get $len
    i32.const 15
    i32.sub
    local.set $len
    loop
        local.get $outPtr
        local.get $len
        i32.const 255
        local.get $len
        i32.const 255
        i32.lt_u
        select
        i32.store8
        local.get $outPtr
        i32.const 1
        i32.add
        local.set $outPtr
        local.get $len
        i32.const 255
        i32.sub
        local.tee $len
        i32.const 0
        i32.ge_s
        br_if 0
    end
    local.get $outPtr
)

;;
;; Copy n bytes from source to destination.
;;
;; It is overlap-safe only from left-to-right -- which is only what is
;; required in the current module.
;;
(func $copy
    (param $dst i32)
    (param $src i32)
    (param $len i32)
    block $lessThan8 loop
        local.get $len
        i32.const 8
        i32.lt_u
        br_if $lessThan8
        local.get $dst
        local.get $src
        i32.load8_u
        i32.store8
        local.get $dst
        local.get $src
        i32.load8_u offset=1
        i32.store8 offset=1
        local.get $dst
        local.get $src
        i32.load8_u offset=2
        i32.store8 offset=2
        local.get $dst
        local.get $src
        i32.load8_u offset=3
        i32.store8 offset=3
        local.get $dst
        local.get $src
        i32.load8_u offset=4
        i32.store8 offset=4
        local.get $dst
        local.get $src
        i32.load8_u offset=5
        i32.store8 offset=5
        local.get $dst
        local.get $src
        i32.load8_u offset=6
        i32.store8 offset=6
        local.get $dst
        local.get $src
        i32.load8_u offset=7
        i32.store8 offset=7
        local.get $dst
        i32.const 8
        i32.add
        local.set $dst
        local.get $src
        i32.const 8
        i32.add
        local.set $src
        local.get $len
        i32.const -8
        i32.add
        local.set $len
        br 0
    end end $lessThan8
    local.get $len
    i32.const 4
    i32.ge_u
    if
        local.get $dst
        local.get $src
        i32.load8_u
        i32.store8
        local.get $dst
        local.get $src
        i32.load8_u offset=1
        i32.store8 offset=1
        local.get $dst
        local.get $src
        i32.load8_u offset=2
        i32.store8 offset=2
        local.get $dst
        local.get $src
        i32.load8_u offset=3
        i32.store8 offset=3
        local.get $dst
        i32.const 4
        i32.add
        local.set $dst
        local.get $src
        i32.const 4
        i32.add
        local.set $src
        local.get $len
        i32.const -4
        i32.add
        local.set $len
    end
    local.get $len
    i32.const 2
    i32.ge_u
    if
        local.get $dst
        local.get $src
        i32.load8_u
        i32.store8
        local.get $dst
        local.get $src
        i32.load8_u offset=1
        i32.store8 offset=1
        local.get $dst
        i32.const 2
        i32.add
        local.set $dst
        local.get $src
        i32.const 2
        i32.add
        local.set $src
        local.get $len
        i32.const -2
        i32.add
        local.set $len
    end
    local.get $len
    i32.eqz
    if else
        local.get $dst
        local.get $src
        i32.load8_u
        i32.store8
    end
)

;;
;; module end
;;
)
