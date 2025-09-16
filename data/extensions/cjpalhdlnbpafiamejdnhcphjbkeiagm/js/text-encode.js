/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2018 Raymond Hill

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

const textEncode = (( ) => {

    if ( µb.canFilterResponseData !== true ) { return; }

    // charset aliases extracted from:
    // https://github.com/inexorabletash/text-encoding/blob/b4e5bc26e26e51f56e3daa9f13138c79f49d3c34/lib/encoding.js#L342
    const normalizedCharset = new Map([
        [ 'utf8', 'utf-8' ],
        [ 'unicode-1-1-utf-8', 'utf-8' ],
        [ 'utf-8', 'utf-8' ],

        [ 'windows-1250', 'windows-1250' ],
        [ 'cp1250', 'windows-1250' ],
        [ 'x-cp1250', 'windows-1250' ],

        [ 'windows-1251', 'windows-1251' ],
        [ 'cp1251', 'windows-1251' ],
        [ 'x-cp1251', 'windows-1251' ],

        [ 'windows-1252', 'windows-1252' ],
        [ 'ansi_x3.4-1968', 'windows-1252' ],
        [ 'ascii', 'windows-1252' ],
        [ 'cp1252', 'windows-1252' ],
        [ 'cp819', 'windows-1252' ],
        [ 'csisolatin1', 'windows-1252' ],
        [ 'ibm819', 'windows-1252' ],
        [ 'iso-8859-1', 'windows-1252' ],
        [ 'iso-ir-100', 'windows-1252' ],
        [ 'iso8859-1', 'windows-1252' ],
        [ 'iso88591', 'windows-1252' ],
        [ 'iso_8859-1', 'windows-1252' ],
        [ 'iso_8859-1:1987', 'windows-1252' ],
        [ 'l1', 'windows-1252' ],
        [ 'latin1', 'windows-1252' ],
        [ 'us-ascii', 'windows-1252' ],
        [ 'x-cp1252', 'windows-1252' ],
    ]);

    // http://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WINDOWS/CP1250.TXT
    const cp1250_range0 = new Uint8Array([
    /* 0x0100 */ 0x00, 0x00, 0xC3, 0xE3, 0xA5, 0xB9, 0xC6, 0xE6,
    /* 0x0108 */ 0x00, 0x00, 0x00, 0x00, 0xC8, 0xE8, 0xCF, 0xEF,
    /* 0x0110 */ 0xD0, 0xF0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0118 */ 0xCA, 0xEA, 0xCC, 0xEC, 0x00, 0x00, 0x00, 0x00,
    /* 0x0120 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0128 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0130 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0138 */ 0x00, 0xC5, 0xE5, 0x00, 0x00, 0xBC, 0xBE, 0x00,
    /* 0x0140 */ 0x00, 0xA3, 0xB3, 0xD1, 0xF1, 0x00, 0x00, 0xD2,
    /* 0x0148 */ 0xF2, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0150 */ 0xD5, 0xF5, 0x00, 0x00, 0xC0, 0xE0, 0x00, 0x00,
    /* 0x0158 */ 0xD8, 0xF8, 0x8C, 0x9C, 0x00, 0x00, 0xAA, 0xBA,
    /* 0x0160 */ 0x8A, 0x9A, 0xDE, 0xFE, 0x8D, 0x9D, 0x00, 0x00,
    /* 0x0168 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xD9, 0xF9,
    /* 0x0170 */ 0xDB, 0xFB, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0178 */ 0x00, 0x8F, 0x9F, 0xAF, 0xBF, 0x8E, 0x9E, 0x00
    ]);

    // http://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WINDOWS/CP1251.TXT
    const cp1251_range0 = new Uint8Array([
    /* 0x0400 */ 0x00, 0xA8, 0x80, 0x81, 0xAA, 0xBD, 0xB2, 0xAF,
    /* 0x0408 */ 0xA3, 0x8A, 0x8C, 0x8E, 0x8D, 0x00, 0xA1, 0x8F,
    /* 0x0410 */ 0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    /* 0x0418 */ 0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF,
    /* 0x0420 */ 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
    /* 0x0428 */ 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE, 0xDF,
    /* 0x0430 */ 0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
    /* 0x0438 */ 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF,
    /* 0x0440 */ 0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    /* 0x0448 */ 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
    /* 0x0450 */ 0x00, 0xB8, 0x90, 0x83, 0xBA, 0xBE, 0xB3, 0xBF,
    /* 0x0458 */ 0xBC, 0x9A, 0x9C, 0x9E, 0x9D, 0x00, 0xA2, 0x9F,
    /* 0x0460 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0468 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0470 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0478 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0480 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0488 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0490 */ 0xA5, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    ]);

    // https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WINDOWS/CP1252.TXT
    const cp1252_range0 = new Uint8Array([
    /* 0x0150 */ 0x00, 0x00, 0x8C, 0x9C, 0x00, 0x00, 0x00, 0x00,
    /* 0x0158 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0160 */ 0x8A, 0x9A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0168 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0170 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x0178 */ 0x9F, 0x00, 0x00, 0x00, 0x00, 0x8E, 0x9E, 0x00
    ]);

    const cp125x_range0 = new Uint8Array([
    /* 0x2010 */ 0x00, 0x00, 0x00, 0x96, 0x97, 0x00, 0x00, 0x00,
    /* 0x2018 */ 0x91, 0x92, 0x82, 0x00, 0x93, 0x94, 0x84, 0x00,
    /* 0x2020 */ 0x86, 0x87, 0x95, 0x00, 0x00, 0x00, 0x85, 0x00,
    /* 0x2028 */ 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x2030 */ 0x89, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    /* 0x2038 */ 0x00, 0x8B, 0x9B, 0x00, 0x00, 0x00, 0x00, 0x00
    ]);

    const encoders = {
        'windows-1250': function(buf) {
            let i = 0, n = buf.byteLength, o = 0, c;
            while ( i < n ) {
                c = buf[i++];
                if ( c < 0x80 ) {
                    buf[o++] = c;
                } else {
                    if ( (c & 0xE0) === 0xC0 ) {
                        c  = (c        & 0x1F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF0) === 0xE0 ) {
                        c  = (c        & 0x0F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF8) === 0xF0 ) {
                        c  = (c        & 0x07) << 18;
                        c |= (buf[i++] & 0x3F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    }
                    if ( c < 0x100 ) {
                        buf[o++] = c;
                    } else if ( c < 0x180 ) {
                        buf[o++] = cp1250_range0[c - 0x100];
                    } else if ( c >= 0x2010 && c < 0x2040 ) {
                        buf[o++] = cp125x_range0[c - 0x2010];
                    } else if ( c === 0x02C7 ) {
                        buf[o++] = 0xA1;
                    } else if ( c === 0x02D8 ) {
                        buf[o++] = 0xA2;
                    } else if ( c === 0x02D9 ) {
                        buf[o++] = 0xFF;
                    } else if ( c === 0x02DB ) {
                        buf[o++] = 0xB2;
                    } else if ( c === 0x02DD ) {
                        buf[o++] = 0xBD;
                    } else if ( c === 0x20AC ) {
                        buf[o++] = 0x88;
                    } else if ( c === 0x2122 ) {
                        buf[o++] = 0x99;
                    }
                }
            }
            return buf.slice(0, o);
        },
        'windows-1251': function(buf) {
            let i = 0, n = buf.byteLength, o = 0, c;
            while ( i < n ) {
                c = buf[i++];
                if ( c < 0x80 ) {
                    buf[o++] = c;
                } else {
                    if ( (c & 0xE0) === 0xC0 ) {
                        c  = (c        & 0x1F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF0) === 0xE0 ) {
                        c  = (c        & 0x0F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF8) === 0xF0 ) {
                        c  = (c        & 0x07) << 18;
                        c |= (buf[i++] & 0x3F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    }
                    if ( c < 0x100 ) {
                        buf[o++] = c;
                    } else if ( c >= 0x400 && c < 0x4A0 ) {
                        buf[o++] = cp1251_range0[c - 0x400];
                    } else if ( c >= 0x2010 && c < 0x2040 ) {
                        buf[o++] = cp125x_range0[c - 0x2010];
                    } else if ( c === 0x20AC ) {
                        buf[o++] = 0x88;
                    } else if ( c === 0x2116 ) {
                        buf[o++] = 0xB9;
                    } else if ( c === 0x2122 ) {
                        buf[o++] = 0x99;
                    }
                }
            }
            return buf.slice(0, o);
        },
        'windows-1252': function(buf) {
            let i = 0, n = buf.byteLength, o = 0, c;
            while ( i < n ) {
                c = buf[i++];
                if ( c < 0x80 ) {
                    buf[o++] = c;
                } else {
                    if ( (c & 0xE0) === 0xC0 ) {
                        c  = (c        & 0x1F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF0) === 0xE0 ) {
                        c  = (c        & 0x0F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    } else if ( (c & 0xF8) === 0xF0 ) {
                        c  = (c        & 0x07) << 18;
                        c |= (buf[i++] & 0x3F) << 12;
                        c |= (buf[i++] & 0x3F) << 6;
                        c |= (buf[i++] & 0x3F);
                    }
                    if ( c < 0x100 ) {
                        buf[o++] = c;
                    } else if ( c >= 0x150 && c < 0x180 ) {
                        buf[o++] = cp1252_range0[c - 0x150];
                    } else if ( c >= 0x2010 && c < 0x2040 ) {
                        buf[o++] = cp125x_range0[c - 0x2010];
                    } else if ( c === 0x192 ) {
                        buf[o++] = 0x83;
                    } else if ( c === 0x2C6 ) {
                        buf[o++] = 0x88;
                    } else if ( c === 0x2DC ) {
                        buf[o++] = 0x98;
                    } else if ( c === 0x20AC ) {
                        buf[o++] = 0x80;
                    } else if ( c === 0x2122 ) {
                        buf[o++] = 0x99;
                    }
                }
            }
            return buf.slice(0, o);
        }
    };

    return {
        encode: function(charset, buf) {
            return Object.hasOwn(encoders, charset) ?
                encoders[charset](buf) :
                buf;
        },
        normalizeCharset: function(charset) {
            if ( charset === undefined ) {
                return 'utf-8';
            }
            return normalizedCharset.get(charset.toLowerCase());
        }
    };
})();

/******************************************************************************/

export default textEncode;

/******************************************************************************/
