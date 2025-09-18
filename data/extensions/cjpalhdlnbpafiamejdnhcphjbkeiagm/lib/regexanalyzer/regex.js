/**
*
*   Regex
*   @version: 1.2.0
*
*   A simple & generic Regular Expression Analyzer & Composer for PHP, Python, Javascript
*   https://github.com/foo123/RegexAnalyzer
*
**/
export default (function(root, name, factory) {
"use strict";
var __version__ = "1.2.0",

    PROTO = 'prototype', OP = Object[PROTO], AP = Array[PROTO],
    Keys = Object.keys, to_string = OP.toString, HAS = OP.hasOwnProperty,
    fromCharCode = String.fromCharCode,
    fromCodePoint = String.fromCodePoint || String.fromCharCode,
    CHAR = 'charAt', CHARCODE = 'charCodeAt',
    CODEPOINT = String.prototype.codePointAt ? 'codePointAt' : CHARCODE,
    toJSON = JSON.stringify,
    INF = Infinity, ESC = '\\',
    specialChars = {
        "." : "MatchAnyChar",
        "|" : "MatchEither",
        "?" : "MatchZeroOrOne",
        "*" : "MatchZeroOrMore",
        "+" : "MatchOneOrMore",
        "^" : "MatchStart",
        "$" : "MatchEnd",
        "{" : "StartRepeats",
        "}" : "EndRepeats",
        "(" : "StartGroup",
        ")" : "EndGroup",
        "[" : "StartCharGroup",
        "]" : "EndCharGroup"
    },
    /*
        http://www.javascriptkit.com/javatutors/redev2.shtml

        \f matches form-feed.
        \r matches carriage return.
        \n matches linefeed.
        \t matches horizontal tab.
        \v matches vertical tab.
        \0 matches NUL character.
        [\b] matches backspace.
        \s matches whitespace (short for [\f\n\r\t\v\u00A0\u2028\u2029]).
        \S matches anything but a whitespace (short for [^\f\n\r\t\v\u00A0\u2028\u2029]).
        \w matches any alphanumerical character (word characters) including underscore (short for [a-zA-Z0-9_]).
        \W matches any non-word characters (short for [^a-zA-Z0-9_]).
        \d matches any digit (short for [0-9]).
        \D matches any non-digit (short for [^0-9]).
        \b matches a word boundary (the position between a word and a space).
        \B matches a non-word boundary (short for [^\b]).
        \cX matches a control character. E.g: \cm matches control-M.
        \xhh matches the character with two characters of hexadecimal code hh.
        \uhhhh matches the Unicode character with four characters of hexadecimal code hhhh.
    */
    specialCharsEscaped = {
        "\\" : "ESC",
        "/" : "/",
        "0" : "NULChar",
        "f" : "FormFeed",
        "n" : "LineFeed",
        "r" : "CarriageReturn",
        "t" : "HorizontalTab",
        "v" : "VerticalTab",
        "b" : "MatchWordBoundary",
        "B" : "MatchNonWordBoundary",
        "s" : "MatchSpaceChar",
        "S" : "MatchNonSpaceChar",
        "w" : "MatchWordChar",
        "W" : "MatchNonWordChar",
        "d" : "MatchDigitChar",
        "D" : "MatchNonDigitChar"
    },
    T_SEQUENCE = 1,
    T_ALTERNATION = 2,
    T_GROUP = 4,
    T_CHARGROUP = 8,
    T_QUANTIFIER = 16,
    T_UNICODECHAR = 32,
    T_HEXCHAR = 64,
    T_SPECIAL = 128,
    T_CHARS = 256,
    T_CHARRANGE = 512,
    T_STRING = 1024,
    T_COMMENT = 2048
;

function is_array(x)
{
    return (x instanceof Array) || ('[object Array]' === to_string.call(x));
}
function is_string(x)
{
    return (x instanceof String) || ('[object String]' === to_string.call(x));
}
function is_regexp(x)
{
    return (x instanceof RegExp) || ('[object RegExp]' === to_string.call(x));
}
function array(x)
{
    return is_array(x) ? x : [x];
}
function clone(obj, cloned)
{
    cloned = cloned || {};
    for (var p in obj) if (HAS.call(obj,p)) cloned[p] = obj[p];
    return cloned;
}
function RE_OBJ(re, flags, flavor)
{
    var self = this;
    self.re = re;
    self.flags = flags;
    self.flavor = flavor;
    self.len = re.length;
    self.pos = 0;
    self.index = 0;
    self.groupIndex = 0;
    self.group = {};
    self.inGroup = 0;
}
RE_OBJ[PROTO] = {
     constructor: RE_OBJ
    ,re: null
    ,flags: null
    ,flavor: ''
    ,len: null
    ,pos: null
    ,index: null
    ,groupIndex: null
    ,inGroup: null
    ,groups: null
    ,dispose: function() {
        var self = this;
        self.re = null;
        self.flags = null;
        self.flavor = null;
        self.len = null;
        self.pos = null;
        self.index = null;
        self.groupIndex = null;
        self.group = null;
        self.inGroup = null;
    }
};
function Node(type, value, flags)
{
    var self = this;
    if (!(self instanceof Node)) return new Node(type, value, flags);
    self.type = type;
    self.val = value;
    self.flags = flags || {};
    switch (type)
    {
        case T_SEQUENCE:
            self.typeName = "Sequence"; break;
        case T_ALTERNATION:
            self.typeName = "Alternation"; break;
        case T_GROUP:
            self.typeName = "Group"; break;
        case T_CHARGROUP:
            self.typeName = "CharacterGroup"; break;
        case T_CHARS:
            self.typeName = "Characters"; break;
        case T_CHARRANGE:
            self.typeName = "CharacterRange"; break;
        case T_STRING:
            self.typeName = "String"; break;
        case T_QUANTIFIER:
            self.typeName = "Quantifier"; break;
        case T_UNICODECHAR:
            self.typeName = "UnicodeChar"; break;
        case T_HEXCHAR:
            self.typeName = "HexChar"; break;
        case T_SPECIAL:
            self.typeName = "Special"; break;
        case T_COMMENT:
            self.typeName = "Comment"; break;
        default:
            self.typeName = "unspecified"; break;
    }
};
Node.toObjectStatic = function toObject(v) {
    if (v instanceof Node)
    {
        return v.flags && Object.keys(v.flags).length ? {
            type: v.typeName,
            value: toObject(v.val),
            flags: v.flags
        } : {
            type: v.typeName,
            value: toObject(v.val)
        };
    }
    else if (is_array(v))
    {
        return v.map(toObject);
    }
    return v;
};
Node[PROTO] = {
    constructor: Node
    ,type: null
    ,typeName: null
    ,val: null
    ,flags: null
    ,dispose: function() {
        var self = this;
        self.val = null;
        self.flags = null;
        self.type = null;
        self.typeName = null;
        return self;
    }
    ,toObject: function() {
        return Node.toObjectStatic(this);
    }
};

var rnd = function(a, b) {return Math.round((b-a)*Math.random()+a);},
    RE = function(re, fl) {return new RegExp(re, fl||'');},
    slice = function(a) {return AP.slice.apply(a, AP.slice.call(arguments, 1));},
    flatten = function(a) {
        var r = [], i = 0;
        while (i < a.length) r = r.concat(a[i++]);
        return r;
    },
    getArgs = function(args, asArray) {
        /*var a = slice(args);
        if ( asArray && a[0] &&
            ( a[0] instanceof Array || '[object Array]' == to_string.call(a[0]) )
        )
            a = a[0];*/
        return flatten(slice(args)); //a;
    },
    esc_re = function(s, esc, chargroup) {
        var es = '', l = s.length, i=0, c;
        //escaped_re = /([.*+?^${}()|[\]\/\\\-])/g
        if (chargroup)
        {
            while (i < l)
            {
                c = s[CHAR](i++);
                es += (/*('?' === c) || ('*' === c) || ('+' === c) ||*/
                        ('-' === c) || /*('.' === c) ||*/ ('^' === c) || ('$' === c) || ('|' === c) ||
                        ('{' === c) || ('}' === c) || ('(' === c) || (')' === c) ||
                        ('[' === c) || (']' === c) || ('/' === c) || (esc === c) ? esc : '') + c;
            }
        }
        else
        {
            while (i < l)
            {
                c = s[CHAR](i++);
                es += (('?' === c) || ('*' === c) || ('+' === c) ||
                    /*('-' === c) ||*/ ('.' === c) || ('^' === c) || ('$' === c) || ('|' === c) ||
                    ('{' === c) || ('}' === c) || ('(' === c) || (')' === c) ||
                    ('[' === c) || (']' === c) || ('/' === c) || (esc === c) ? esc : '') + c;
            }
        }
        return es;
    },
    pad = function(s, n, z) {
        var ps = String(s);
        z = z || '0';
        while (ps.length < n) ps = z + ps;
        return ps;
    },
    char_code = function(c) {return c[CODEPOINT](0);},
    char_code_range = function(s) {return [s[CODEPOINT](0), s[CODEPOINT](s.length-1)];},
    //char_codes = function( s_or_a ) { return (s_or_a.substr ? s_or_a.split("") : s_or_a).map( char_code ); },
    // http://stackoverflow.com/questions/12376870/create-an-array-of-characters-from-specified-range
    character_range = function(first, last) {
        if (first && is_array(first)) {last = first[1]; first = first[0];}
        var ch, chars, start = first[CODEPOINT](0), end = last[CODEPOINT](0);

        if (end === start) return [fromCodePoint(start)];

        chars = [];
        for (ch = start; ch <= end; ++ch) chars.push(fromCodePoint(ch));
        return chars;
    },
    concat = function(p1, p2) {
        if (p2)
        {
            var p, l;
            if (is_array(p2))
            {
                for (p=0,l=p2.length; p<l; ++p) p1[p2[p]] = 1;
            }
            else
            {
                for (p in p2) if (HAS.call(p2, p)) p1[p] = 1;
            }
        }
        return p1;
    },

    BSPACES = "\r\n", SPACES = " \t\v", PUNCTS = "~!@#$%^&*()-+=[]{}\\|;:,./<>?",
    DIGITS = "0123456789", DIGITS_RANGE = char_code_range(DIGITS),
    HEXDIGITS_RANGES = [DIGITS_RANGE, [char_code("a"), char_code("f")], [char_code("A"), char_code("F")]],
    ALPHAS = "_"+(character_range("a", "z").join(""))+(character_range("A", "Z").join("")),
    ALL = SPACES+PUNCTS+DIGITS+ALPHAS, ALL_ARY = ALL.split(""),

    match_chars = function(CHARS, s, pos, minlen, maxlen) {
        pos = pos || 0;
        minlen = minlen || 1;
        maxlen = maxlen || INF;
        var lp = pos, l = 0, sl = s.length, ch;
        while ((lp < sl) && (l <= maxlen) && -1 < CHARS.indexOf(ch=s[CHAR](lp)))
        {
            ++lp; ++l;
        }
        return l >= minlen ? l : false;
    },
    match_char_range = function(RANGE, s, pos, minlen, maxlen) {
        pos = pos || 0;
        minlen = minlen || 1;
        maxlen = maxlen || INF;
        var lp = pos, l = 0, sl = s.length, ch;
        while ((lp < sl) && (l <= maxlen) && ((ch=s[CHARCODE](lp)) >= RANGE[0] && ch <= RANGE[1]))
        {
            ++lp; ++l;
        }
        return l >= minlen ? l : false;
    },
    match_char_ranges = function(RANGES, s, pos, minlen, maxlen) {
        pos = pos || 0;
        minlen = minlen || 1;
        maxlen = maxlen || INF;
        var lp = pos, l = 0, sl = s.length, ch,
            i, Rl = RANGES.length, RANGE, found = true;
        while ((lp < sl) && (l <= maxlen) && found)
        {
            ch = s[CHARCODE](lp); found = false;
            for (i=0; i<Rl; ++i)
            {
                RANGE = RANGES[i];
                if (ch >= RANGE[0] && ch <= RANGE[1])
                {
                    ++lp; ++l; found = true;
                    break;
                }
            }
        }
        return l >= minlen ? l : false;
    },

    punct = function() {
        return PUNCTS[CHAR](rnd(0, PUNCTS.length-1));
    },
    space = function(positive) {
        return false !== positive
            ? SPACES[CHAR](rnd(0, SPACES.length-1))
            : (punct()+digit()+alpha())[CHAR](rnd(0, 2))
        ;
    },
    digit = function(positive) {
        return false !== positive
            ? DIGITS[CHAR](rnd(0, DIGITS.length-1))
            : (punct()+space()+alpha())[CHAR](rnd(0, 2))
        ;
    },
    alpha = function(positive) {
        return false !== positive
            ? ALPHAS[CHAR](rnd(0, ALPHAS.length-1))
            : (punct()+space()+digit())[CHAR](rnd(0, 2))
        ;
    },
    word = function(positive) {
        return false !== positive
            ? (ALPHAS+DIGITS)[CHAR](rnd(0, ALPHAS.length+DIGITS.length-1))
            : (punct()+space())[CHAR](rnd(0, 1))
        ;
    },
    any = function() {
        return ALL[CHAR](rnd(0, ALL.length-1));
    },
    character = function(chars, positive) {
        if (false !== positive) return chars.length ? chars[rnd(0, chars.length-1)] : '';
        var choices = ALL_ARY.filter(function(c) {return 0 > chars.indexOf(c);});
        return choices.length ? choices[rnd(0, choices.length-1)] : '';
    },
    random_upper_or_lower = function(c) {return 0.5 < Math.random() ? c.toLowerCase() : c.toUpperCase();},
    case_insensitive = function(chars, asArray) {
        if (asArray)
        {
            if (chars[CHAR]) chars = chars.split('');
            chars = chars.map(random_upper_or_lower);
            //if ( !asArray ) chars = chars.join('');
            return chars;
        }
        else
        {
            return random_upper_or_lower(chars);
        }
    },

    walk = function walk(ret, node, state) {
        if ((null == node) || !state) return ret;

        var i, l, r, type = node instanceof Node ? node.type : null;

        // walk the tree
        if (null === type)
        {
            // custom, let reduce handle it
            ret = state.reduce(ret, node, state);
        }

        else if (state.IGNORE & type)
        {
            /* nothing */
        }

        else if (state.MAP & type)
        {
            r = state.map(ret, node, state);
            if (null != state.ret)
            {
                ret = state.reduce(ret, node, state);
                state.ret = null;
            }
            else if (null != r)
            {
                r = array(r);
                for (i=0,l=r?r.length:0; i<l; ++i)
                {
                    state.node = node;
                    ret = walk(ret, r[i], state);
                    if (state.stop)
                    {
                        state.stop = null;
                        return ret;
                    }
                }
            }
        }

        else if (state.REDUCE & type)
        {
            ret = state.reduce(ret, node, state);
        }

        state.node = null;
        return ret;
    },
    /*map_all = function map_all( ret, node, state ) {
        return node.val;
    },*/
    map_src = function map_src(ret, node, state) {
        var type = node.type;
        if (T_ALTERNATION === type)
        {
            var r = [];
            for (var i=0,l=node.val.length-1; i<l; ++i) r.push(node.val[i], '|');
            r.push(node.val[l]);
            return r;
        }
        else if (T_CHARGROUP === type)
        {
            return [].concat('['+(node.flags.NegativeMatch?'^':'')).concat(array(node.val)).concat(']');
        }
        else if (T_QUANTIFIER === type)
        {
            var q = '';
            if (node.flags.MatchZeroOrOne) q = '?';
            else if (node.flags.MatchZeroOrMore) q = '*';
            else if (node.flags.MatchOneOrMore) q = '+';
            else q = node.flags.min === node.flags.max ? ('{'+node.flags.min+'}') : ('{'+node.flags.min+','+(-1===node.flags.max?'':node.flags.max)+'}');
            if ((node.flags.min !== node.flags.max) && !node.flags.isGreedy) q += '?';
            return [].concat(array(node.val)).concat(q);
        }
        else if (T_GROUP === type)
        {
            var g = null;
            if (node.flags.NotCaptured)
            {
                g = [].concat('(?:').concat(array(node.val)).concat(')');
            }
            else if (node.flags.LookAhead)
            {
                g = [].concat('(?=').concat(array(node.val)).concat(')');
            }
            else if (node.flags.NegativeLookAhead)
            {
                g = [].concat('(?!').concat(array(node.val)).concat(')');
            }
            else if (node.flags.LookBehind)
            {
                g = [].concat('(?<=').concat(array(node.val)).concat(')');
            }
            else if (node.flags.NegativeLookBehind)
            {
                g = [].concat('(?<!').concat(array(node.val)).concat(')');
            }
            else if (node.flags.NamedGroup && !state.compatibility)
            {
                g = [].concat('(?<'+node.flags.GroupName+'>').concat(array(node.val)).concat(')');
            }
            else
            {
                g = [].concat('(').concat(array(node.val)).concat(')');
            }
            if (null != node.flags.GroupIndex)
            {
                ret.group[node.flags.GroupIndex] = node.flags.GroupIndex;
                if (node.flags.GroupName) ret.group[node.flags.GroupName] = node.flags.GroupIndex;
            }
            return g;
        }
        return node.val;
    },
    map_any = function map_any(ret, node, state) {
        var type = node.type;
        if ((T_ALTERNATION === type) || (T_CHARGROUP === type))
        {
            return node.val.length ? node.val[rnd(0, node.val.length-1)] : null;
        }
        else if (T_QUANTIFIER === type)
        {
            var numrepeats, mmin, mmax, repeats;
            if (ret.length >= state.maxLength)
            {
                numrepeats = node.flags.min;
            }
            else
            {
                mmin = node.flags.min;
                mmax = -1 === node.flags.max ? (mmin+1+2*state.maxLength) : node.flags.max;
                numrepeats = rnd(mmin, mmax);
            }
            if (numrepeats)
            {
                repeats = new Array(numrepeats);
                for (var i=0; i<numrepeats; ++i) repeats[i] = node.val;
                return repeats;
            }
            else
            {
                return null;
            }
        }
        else if ((T_GROUP === type) && node.flags.GroupIndex)
        {
            var sample = walk('', node.val, state);
            state.group[node.flags.GroupIndex] = sample;
            state.ret = sample;
            return null;
        }
        else
        {
            return node.val;
        }
    },
    map_min = function map_min(ret, node, state) {
        var type = node.type;
        if (T_ALTERNATION === type)
        {
            var i, l = node.val.length, cur,
                min = l ? walk(0, node.val[0], state) : 0;
            for (i=1; i<l; ++i)
            {
                cur = walk(0, node.val[i], state);
                if (cur < min) min = cur;
            }
            if (l) state.ret = min;
            return null;
        }
        else if (T_CHARGROUP === type)
        {
            return node.val.length ? node.val[0] : null;
        }
        else if (T_QUANTIFIER === type)
        {
            if (0 === node.flags.min) return null;
            var i, nrepeats = node.flags.min, repeats = new Array(nrepeats);
            for (i=0; i<nrepeats; ++i) repeats[i] = node.val;
            return repeats;
        }
        else if ((T_GROUP === type) && node.flags.GroupIndex)
        {
            var min = walk(0, node.val, state);
            state.group[node.flags.GroupIndex] = min;
            state.ret = min;
            return null;
        }
        else
        {
            return node.val;
        }
    },
    map_max = function map_max(ret, node, state) {
        var type = node.type;
        if (T_ALTERNATION === type)
        {
            var i, l = node.val.length, cur, max = l ? walk(0, node.val[0], state) : 0;
            if (-1 !== max)
            {
                for (i=1; i<l; ++i)
                {
                    cur = walk(0, node.val[i], state);
                    if (-1 === cur)
                    {
                        max = -1;
                        break;
                    }
                    else if (cur > max)
                    {
                        max = cur;
                    }
                }
            }
            if (l) state.ret = max;
            return null;
        }
        else if (T_CHARGROUP === type)
        {
            return node.val.length ? node.val[0] : null;
        }
        else if (T_QUANTIFIER === type)
        {
            max = walk(0, node.val, state);
            if (-1 === max)
            {
                state.ret = -1;
            }
            else if (0 < max)
            {
                if (-1 === node.flags.max)
                {
                    state.ret = -1;
                }
                else if (0 < node.flags.max)
                {
                    state.ret = node.flags.max*max;
                }
                else
                {
                    state.ret = max;
                }
            }
            return null;
        }
        else if ((T_GROUP === type) && node.flags.GroupIndex)
        {
            var max = walk(0, node.val, state);
            state.group[node.flags.GroupIndex] = max;
            state.ret = max;
            return null;
        }
        else
        {
            return node.val;
        }
    },
    map_1st = function map_1st(ret, node, state) {
        var type = node.type;
        if (T_SEQUENCE === type)
        {
            var seq=[], i=0, l=node.val.length, n;
            for (i=0; i<l; ++i)
            {
                n = node.val[i];
                seq.push( n );
                if ((T_QUANTIFIER === n.type) && (0 === n.flags.min))
                    continue;
                else if ((T_SPECIAL === n.type) && (n.flags.MatchStart || n.flags.MatchEnd))
                    continue;
                break;
            }
            return seq.length ? seq : null;
        }
        else
        {
            return node.val;
        }
    },
    reduce_len = function reduce_len(ret, node, state) {
        if (null != state.ret)
        {
            if (-1 === state.ret) ret = -1;
            else ret += state.ret;
            return ret;
        }
        if (-1 === ret) return ret;

        if (node === +node)
        {
            ret += node;
            return ret;
        }

        if ((T_SPECIAL === node.type) && node.flags.MatchEnd)
        {
            state.stop = 1;
            return ret;
        }
        var type = node.type;

        if (
            (T_CHARS === type) || (T_CHARRANGE === type) ||
            (T_UNICODECHAR === type) || (T_HEXCHAR === type) ||
            ((T_SPECIAL === type) && !node.flags.MatchStart && !node.flags.MatchEnd)
        )
        {
            ret += node.flags.BackReference ? state.group[node.flags.GroupIndex]||0 : 1;
        }
        else if (T_STRING === type)
        {
            ret += node.val.length;
        }

        return ret;
    },
    reduce_str = function reduce_str(ret, node, state) {
        if (null != state.ret)
        {
            ret += state.ret;
            return ret;
        }

        if (is_string(node))
        {
            ret += node;
            return ret;
        }

        if ((T_SPECIAL === node.type) && node.flags.MatchEnd)
        {
            state.stop = 1;
            return ret;
        }
        var type = node.type, sample = null;

        if (T_CHARS === type)
        {
            sample = node.val;
        }
        else if (T_CHARRANGE === type)
        {
            var range = [node.val[0], node.val[1]];
            if (T_UNICODECHAR === range[0].type || T_HEXCHAR === range[0].type) range[0] = range[0].flags.Char;
            if (T_UNICODECHAR === range[1].type || T_HEXCHAR === range[1].type) range[1] = range[1].flags.Char;
            sample = character_range(range);
        }
        else if ((T_UNICODECHAR === type) || (T_HEXCHAR === type))
        {
            sample = [node.flags.Char];
        }
        else if ((T_SPECIAL === type) && !node.flags.MatchStart && !node.flags.MatchEnd)
        {
            var part = node.val;
            if (node.flags.BackReference)
            {
                part = node.flags.GroupIndex;
                ret += HAS.call(state.group, part) ? state.group[part] : '';
                return ret;
            }
            else if ('D' === part)
            {
                sample = [digit(false)];
            }
            else if ('W' === part)
            {
                sample = [word(false)];
            }
            else if ('S' === part)
            {
                sample = [space(false)];
            }
            else if ('d' === part)
            {
                sample = [digit()];
            }
            else if ('w' === part)
            {
                sample = [word()];
            }
            else if ('s' === part)
            {
                sample = [space()];
            }
            else if (('.' === part) && node.flags.MatchAnyChar)
            {
                sample = [any()];
            }
            else
            {
                sample = [ESC + part];
            }
        }
        else if (T_STRING === type)
        {
            sample = node.val;
        }

        if (sample)
        {
            ret += T_STRING === type ?
            (state.isCaseInsensitive ? case_insensitive(sample) : sample) :
            (character(state.isCaseInsensitive ? case_insensitive(sample, true) : sample, !state.node || !state.node.flags.NegativeMatch))
            ;
        }

        return ret;
    },
    reduce_src = function reduce_src(ret, node, state) {
        if (null != state.ret)
        {
            if (state.ret.src) ret.src += state.ret.src;
            if (state.ret.group) ret.group = clone(state.ret.group, ret.group);
            return ret;
        }

        if (is_string(node))
        {
            ret.src += node;
            return ret;
        }

        var type = node.type;
        if (T_CHARS === type)
        {
            ret.src += state.escaped ? esc_re(node.val.join(''), ESC, 1) : node.val.join('');
        }
        else if (T_CHARRANGE === type)
        {
            var range = [node.val[0], node.val[1]];
            if (state.escaped)
            {
                if (T_UNICODECHAR === range[0].type) range[0] = range[0].flags.UnicodePoint ? ESC+'u{'+range[0].flags.Code+'}' : ESC+'u'+pad(range[0].flags.Code,4);
                else if (T_HEXCHAR === range[0].type) range[0] = ESC+'x'+pad(range[0].flags.Code,2);
                else range[0] = esc_re(range[0], ESC, 1);
                if (T_UNICODECHAR === range[1].type) range[1] = range[1].flags.UnicodePoint ? ESC+'u{'+range[1].flags.Code+'}' : ESC+'u'+pad(range[1].flags.Code,4);
                else if (T_HEXCHAR === range[1].type) range[1] = ESC+'x'+pad(range[1].flags.Code,2);
                else range[1] = esc_re(range[1], ESC, 1);
            }
            else
            {
                if (T_UNICODECHAR === range[0].type || T_HEXCHAR === range[0].type) range[0] = range[0].flags.Char;
                if (T_UNICODECHAR === range[1].type || T_HEXCHAR === range[1].type) range[1] = range[1].flags.Char;
            }
            ret.src += range[0]+'-'+range[1];
        }
        else if (T_UNICODECHAR === type)
        {
            ret.src += node.flags.UnicodePoint ? ESC+'u{'+node.flags.Code+'}' : (state.escaped ? ESC+'u'+pad(node.flags.Code,4) : node.flags.Char);
        }
        else if (T_HEXCHAR === type)
        {
            ret.src += state.escaped ? ESC+'x'+pad(node.flags.Code,2) : node.flags.Char;
        }
        else if (T_SPECIAL === type)
        {
            if (node.flags.BackReference)
            {
                if (state.compatibility || (node.flags.GroupIndex === node.flags.GroupName))
                {
                    ret.src += ESC+node.flags.GroupIndex;
                }
                else
                {
                    ret.src += ESC+'k<'+node.flags.GroupName+'>';
                }
            }
            else
            {
                ret.src += node.flags.MatchAnyChar || node.flags.MatchStart || node.flags.MatchEnd ? (''+node.val) : (ESC+node.val);
            }
        }
        else if (T_STRING === type)
        {
            ret.src += state.escaped ? esc_re(node.val, ESC) : node.val;
        }

        return ret;
    },
    reduce_peek = function reduce_peek(ret, node, state) {
        if (null != state.ret)
        {
            ret.positive = concat(ret.positive, state.ret.positive);
            ret.negative = concat(ret.negative, state.ret.negative);
            return ret;
        }
        if ((T_SPECIAL === node.type) && node.flags.MatchEnd)
        {
            state.stop = 1;
            return ret;
        }

        var type = node.type, inCharGroup = state.node && (T_CHARGROUP === state.node.type),
            inNegativeCharGroup = inCharGroup && state.node.flags.NegativeMatch,
            peek = inNegativeCharGroup ? "negative" : "positive";

        if (T_CHARS === type)
        {
            ret[peek] = concat(ret[peek], node.val);
        }
        else if (T_CHARRANGE === type)
        {
            var range = [node.val[0],node.val[1]];
            if (T_UNICODECHAR === range[0].type || T_HEXCHAR === range[0].type) range[0] = range[0].flags.Char;
            if (T_UNICODECHAR === range[1].type || T_HEXCHAR === range[1].type) range[1] = range[1].flags.Char;
            ret[peek] = concat(ret[peek], character_range(range));
        }
        else if ((T_UNICODECHAR === type) || (T_HEXCHAR === type))
        {
            ret[peek][node.flags.Char] = 1;
        }
        else if ((T_SPECIAL === type) && !node.flags.BackReference && !node.flags.MatchStart && !node.flags.MatchEnd)
        {
            var part = node.val;
            if ('D' === part)
            {
                ret[inNegativeCharGroup?"positive":"negative"][ '\\d' ] = 1;
            }
            else if ('W' === part)
            {
                ret[inNegativeCharGroup?"positive":"negative"][ '\\w' ] = 1;
            }
            else if ('S' === part)
            {
                ret[inNegativeCharGroup?"positive":"negative"][ '\\s' ] = 1;
            }
            else if ('B' === part)
            {
                ret[inNegativeCharGroup?"positive":"negative"][ '\\b' ] = 1;
            }
            else
            {
                ret[peek][ESC + part] = 1;
            }
        }
        else if (T_STRING === type)
        {
            ret["positive"][node.val[CHAR](0)] = 1;
        }

        return ret;
    },

    match_hex = function(s) {
        var m = false;
        if ((s.length > 2) && ('x' === s[CHAR](0)))
        {
            if (match_char_ranges(HEXDIGITS_RANGES, s, 1, 2, 2)) return [m=s.slice(0,3), m.slice(1)];
        }
        return false;
    },
    match_unicode = function(s, flags) {
        var m = false, l;
        if ((s.length > 3) && ('u' === s[CHAR](0)))
        {
            if (flags.u && '{' === s[CHAR](1) && (l=match_char_ranges(HEXDIGITS_RANGES, s, 2, 1, 6)) && '}' === s[CHAR](l+2))
            {
                return [m=s.slice(0,l+3), m.slice(2, -1), 1];
            }
            else if (l=match_char_ranges(HEXDIGITS_RANGES, s, 1, 4, 4))
            {
                return [m=s.slice(0,l+1), m.slice(1), 0];
            }
        }
        return false;
    },
    match_repeats = function(s) {
        var l, sl = s.length, pos = 0, m = false, hasComma = false;
        if ((sl > 2) && ('{' === s[CHAR](pos)))
        {
            m = ['', '', null];
            ++pos;
            if (l=match_chars(SPACES, s, pos)) pos += l;
            if (l=match_char_range(DIGITS_RANGE, s, pos))
            {
                m[1] = s.slice(pos, pos+l);
                pos += l;
            }
            else
            {
                return false;
            }
            if (l=match_chars(SPACES, s, pos)) pos += l;
            if ((pos < sl) && (',' === s[CHAR](pos))) {pos += 1; hasComma = true;}
            if (l=match_chars(SPACES, s, pos)) pos += l;
            if (l=match_char_range(DIGITS_RANGE, s, pos))
            {
                m[2] = s.slice(pos, pos+l);
                pos += l;
            }
            if (l=match_chars(SPACES, s, pos)) pos += l;
            if ((pos < sl) && ('}' === s[CHAR](pos)))
            {
                pos++;
                m[0] = s.slice(0, pos);
                if (!hasComma) m[2] = m[1];
                return m;
            }
            else
            {
                return false;
            }
        }
        return false;
    },
    chargroup = function chargroup(re_obj) {
        var sequence = [], chars = [], allchars = [], flags = {}, flag, ch, lre,
        prevch = null, range, isRange = false, m, isUnicode, isHex, isSpecial, escaped = false;

        if ('^' === re_obj.re[CHAR](re_obj.pos))
        {
            flags["NegativeMatch"] = 1;
            ++re_obj.pos;
        }

        lre = re_obj.len;
        while (re_obj.pos < lre)
        {
            isUnicode = false;
            isHex = false;
            isSpecial = false;
            m = null;
            prevch = ch;
            ch = re_obj.re[CHAR](re_obj.pos++);

            escaped = ESC === ch;
            if (escaped) ch = re_obj.re[CHAR](re_obj.pos++);

            if (escaped)
            {
                // unicode character
                if ('u' === ch)
                {
                    m = match_unicode(re_obj.re.substr(re_obj.pos-1), re_obj.flags);
                    if (m)
                    {
                        re_obj.pos += m[0].length-1;
                        ch = Node(T_UNICODECHAR, m[0], {"Char": m[2] ? fromCodePoint(parseInt(m[1], 16)) : fromCharCode(parseInt(m[1], 16)), "Code": m[1], "UnicodePoint": !!m[2]});
                        isUnicode = true; isHex = false;
                    }
                }

                // hex character
                else if ('x' === ch)
                {
                    m = match_hex(re_obj.re.substr(re_obj.pos-1));
                    if (m)
                    {
                        re_obj.pos += m[0].length-1;
                        ch = Node(T_HEXCHAR, m[0], {"Char": fromCharCode(parseInt(m[1], 16)), "Code": m[1]});
                        isUnicode = true; isHex = true;
                    }
                }

                // special character
                else if (HAS.call(specialCharsEscaped, ch) && ('/' !== ch))
                {
                    isSpecial = true;
                    flag = {};
                    flag[specialCharsEscaped[ch]] = 1;
                    ch = Node(T_SPECIAL, ch, flag);
                }
            }

            if (isRange)
            {
                if (
                    (ch instanceof Node) &&
                    (ch.type === T_SPECIAL) &&
                    (-1 !== ['s','S','d','D','w','W'].indexOf(ch.val))
                )
                {
                    if (range[0] instanceof Node)
                    {
                        sequence.push(range[0]);
                    }
                    else
                    {
                        chars.push(range[0]);
                    }
                    chars.push('-');
                    sequence.push(ch);
                }
                else
                {
                    if (chars.length)
                    {
                        allchars = allchars.concat(chars);
                        chars = [];
                    }
                    range[1] = ch;
                    sequence.push(Node(T_CHARRANGE, range));
                }
                isRange = false;
            }
            else
            {
                if (escaped)
                {
                    if (isUnicode)
                    {
                        if (chars.length)
                        {
                            allchars = allchars.concat(chars);
                            chars = [];
                        }
                        sequence.push(ch);
                    }

                    else if (isSpecial)
                    {
                        if (chars.length)
                        {
                            allchars = allchars.concat(chars);
                            chars = [];
                        }
                        sequence.push(ch);
                    }

                    else
                    {
                        chars.push(ch);
                    }
                }

                else
                {
                    // end of char group
                    if (']' === ch)
                    {
                        if (chars.length)
                        {
                            allchars = allchars.concat(chars);
                            chars = [];
                        }
                        // map all chars into one node
                        if (allchars.length) sequence.push(Node(T_CHARS, allchars));
                        return Node(T_CHARGROUP, sequence, flags);
                    }

                    else if ('-' === ch)
                    {
                        if (
                            null == prevch ||
                            ']' === re_obj.re[CHAR](re_obj.pos) ||
                            (
                            (prevch instanceof Node) &&
                            (prevch.type === T_SPECIAL) &&
                            (-1 !== ['s','S','d','D','w','W'].indexOf(prevch.val))
                            )
                        )
                        {
                            // take it as literal
                            // https://github.com/foo123/RegexAnalyzer/issues/5
                            chars.push(ch);
                        }
                        else
                        {
                            range = [prevch, ''];
                            if (prevch instanceof Node) sequence.pop(); else chars.pop();
                            isRange = true;
                        }
                    }

                    else
                    {
                        chars.push(ch);
                    }
                }
            }
        }
        if (chars.length)
        {
            allchars = allchars.concat(chars);
            chars = [];
        }
        // map all chars into one node
        if (allchars.length) sequence.push(Node(T_CHARS, allchars));
        return Node(T_CHARGROUP, sequence, flags);
    },

    analyze_re = function analyze_re(re_obj) {
        var lre, ch, m, word = '', wordlen = 0,
            alternation = [], sequence = [], flags = {},
            flag, escaped = false, pre, pre3, captured;

        if (re_obj.inGroup > 0)
        {
            pre = re_obj.re.substr(re_obj.pos, 2);
            pre3 = re_obj.re.substr(re_obj.pos, 3);
            captured = 1;

            if ("?P=" === pre3)
            {
                flags["BackReference"] = 1;
                flags["GroupName"] = '';
                re_obj.pos += 3;
                lre = re_obj.len;
                while (re_obj.pos < lre)
                {
                    ch = re_obj.re[CHAR](re_obj.pos++);
                    if (")" === ch) break;
                    flags["GroupName"] += ch;
                }
                flags["GroupIndex"] = HAS.call(re_obj.group, flags["GroupName"]) ? re_obj.group[flags["GroupName"]] : null;
                return Node(T_SPECIAL, flags["GroupName"], flags);
            }

            else if ("?#" === pre)
            {
                flags["Comment"] = 1;
                re_obj.pos += 2;
                word = '';
                lre = re_obj.len;
                while (re_obj.pos < lre)
                {
                    ch = re_obj.re[CHAR](re_obj.pos++);
                    if (")" === ch) break;
                    word += ch;
                }
                return Node(T_COMMENT, word);
            }

            else if ("?:" === pre)
            {
                flags["NotCaptured"] = 1;
                re_obj.pos += 2;
                captured = 0;
            }

            else if ("?=" === pre)
            {
                flags["LookAhead"] = 1;
                re_obj.pos += 2;
                captured = 0;
            }

            else if ("?!" === pre)
            {
                flags["NegativeLookAhead"] = 1;
                re_obj.pos += 2;
                captured = 0;
            }

            else if ("?<=" === pre3)
            {
                flags["LookBehind"] = 1;
                re_obj.pos += 3;
                captured = 0;
            }

            else if ("?<!" === pre3)
            {
                flags["NegativeLookBehind"] = 1;
                re_obj.pos += 3;
                captured = 0;
            }

            else if (("?<" === pre) || ("?P<" === pre3))
            {
                // https://github.com/foo123/RegexAnalyzer/issues/6
                flags["NamedGroup"] = 1;
                flags["GroupName"] = '';
                re_obj.pos += "?<" === pre ? 2 : 3;
                lre = re_obj.len;
                while (re_obj.pos < lre)
                {
                    ch = re_obj.re[CHAR](re_obj.pos++);
                    if (">" === ch) break;
                    flags["GroupName"] += ch;
                }
            }

            ++re_obj.index;
            if (captured)
            {
                ++re_obj.groupIndex;
                flags["GroupIndex"] = re_obj.groupIndex;
                re_obj.group[flags["GroupIndex"]] = flags["GroupIndex"];
                if (flags["GroupName"]) re_obj.group[flags["GroupName"]] = flags["GroupIndex"];
            }
        }

        lre = re_obj.len;
        while (re_obj.pos < lre)
        {
            ch = re_obj.re[CHAR](re_obj.pos++);

            //   \\abc
            escaped = ESC === ch;
            if (escaped) ch = re_obj.re[CHAR](re_obj.pos++);

            if (escaped)
            {
                // unicode character
                if ('u' === ch)
                {
                    m = match_unicode(re_obj.re.substr(re_obj.pos-1), re_obj.flags);
                    if (m)
                    {
                        if (wordlen)
                        {
                            sequence.push(Node(T_STRING, word));
                            word = '';
                            wordlen = 0;
                        }
                        re_obj.pos += m[0].length-1;
                        sequence.push(Node(T_UNICODECHAR, m[0], {"Char": m[2] ? fromCodePoint(parseInt(m[1], 16)) : fromCharCode(parseInt(m[1], 16)), "Code": m[1], "UnicodePoint": !!m[2]}));
                    }
                    else
                    {
                        word += ch;
                        wordlen += 1;
                    }
                }

                // hex character
                else if ('x' === ch)
                {
                    m = match_hex(re_obj.re.substr(re_obj.pos-1));
                    if (m)
                    {
                        if (wordlen)
                        {
                            sequence.push(Node(T_STRING, word));
                            word = '';
                            wordlen = 0;
                        }
                        re_obj.pos += m[0].length-1;
                        sequence.push(Node(T_HEXCHAR, m[0], {"Char": fromCharCode(parseInt(m[1], 16)), "Code": m[1]}));
                    }
                    else
                    {
                        word += ch;
                        wordlen += 1;
                    }
                }

                // js back-reference
                else if ('k' === ch && '<' === re_obj.re[CHAR](re_obj.pos))
                {
                    // https://github.com/foo123/RegexAnalyzer/issues/6
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    re_obj.pos++;
                    word = '';
                    while (re_obj.pos < lre)
                    {
                        ch = re_obj.re[CHAR](re_obj.pos);
                        if ('>' === ch) {re_obj.pos++; break;}
                        else {word += ch; re_obj.pos++;}
                    }
                    flag = {};
                    flag["BackReference"] = 1;
                    flag["GroupName"] = word;
                    flag["GroupIndex"] = HAS.call(re_obj.group, word) ? re_obj.group[word] : null;
                    sequence.push(Node(T_SPECIAL, word, flag));
                    word = '';
                }

                else if (HAS.call(specialCharsEscaped, ch) && ('/' !== ch))
                {
                    if (wordlen)
                    {
                        sequence.push( Node(T_STRING, word) );
                        word = '';
                        wordlen = 0;
                    }
                    flag = {};
                    flag[ specialCharsEscaped[ch] ] = 1;
                    sequence.push( Node(T_SPECIAL, ch, flag) );
                }

                else if (('1' <= ch) && ('9' >= ch))
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    word = ch;
                    while (re_obj.pos < lre)
                    {
                        ch = re_obj.re[CHAR](re_obj.pos);
                        if (('0' <= ch) && ('9' >= ch)) {word += ch; re_obj.pos++;}
                        else break;
                    }
                    flag = {};
                    flag['BackReference'] = 1;
                    flag['GroupName'] = word;
                    flag['GroupIndex'] = parseInt(word, 10);
                    sequence.push(Node(T_SPECIAL, word, flag));
                    word = '';
                }

                else
                {
                    word += ch;
                    wordlen += 1;
                }
            }

            else
            {
                // group end
                if ((re_obj.inGroup > 0) && (')' === ch))
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    if (alternation.length)
                    {
                        alternation.push(Node(T_SEQUENCE, sequence));
                        sequence = [];
                        flag = {};
                        flag[specialChars['|']] = 1;
                        return Node(T_GROUP, Node(T_ALTERNATION, alternation, flag), flags);
                    }
                    else
                    {
                        return Node(T_GROUP, Node(T_SEQUENCE, sequence), flags);
                    }
                }

                // parse alternation
                else if ('|' === ch)
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    alternation.push(Node(T_SEQUENCE, sequence));
                    sequence = [];
                }

                // parse character group
                else if ('[' === ch)
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    sequence.push(chargroup(re_obj));
                }

                // parse sub-group
                else if ('(' === ch)
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    re_obj.inGroup += 1;
                    sequence.push(analyze_re(re_obj));
                    re_obj.inGroup -= 1;
                }

                // parse num repeats
                else if ('{' === ch)
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    m = match_repeats(re_obj.re.substr(re_obj.pos-1));
                    re_obj.pos += m[0].length-1;
                    flag = {val: m[0], "MatchMinimum": m[1], "MatchMaximum": m[2] || "unlimited", "min": parseInt(m[1],10), "max": m[2] ? parseInt(m[2],10) : -1};
                    flag[specialChars[ch]] = 1;
                    if ((re_obj.pos < lre) && ('?' === re_obj.re[CHAR](re_obj.pos)))
                    {
                        flag["isGreedy"] = 0;
                        re_obj.pos++;
                    }
                    else
                    {
                        flag["isGreedy"] = 1;
                    }
                    var prev = sequence.pop();
                    if ((T_STRING === prev.type) && (prev.val.length > 1))
                    {
                        sequence.push(Node(T_STRING, prev.val.slice(0, -1)));
                        prev.val = prev.val.slice(-1);
                    }
                    sequence.push(Node(T_QUANTIFIER, prev, flag));
                }

                // quantifiers
                else if (('*' === ch) || ('+' === ch) || ('?' === ch))
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    flag = {};
                    flag[specialChars[ch]] = 1;
                    flag["min"] = '+' === ch ? 1 : 0;
                    flag["max"] = '?' === ch ? 1 : -1;
                    if ((re_obj.pos < lre) && ('?' === re_obj.re[CHAR](re_obj.pos)))
                    {
                        flag["isGreedy"] = 0;
                        re_obj.pos++;
                    }
                    else
                    {
                        flag["isGreedy"] = 1;
                    }
                    var prev = sequence.pop();
                    if ((T_STRING === prev.type) && (prev.val.length > 1))
                    {
                        sequence.push(Node(T_STRING, prev.val.slice(0, -1)));
                        prev.val = prev.val.slice(-1);
                    }
                    sequence.push(Node(T_QUANTIFIER, prev, flag));
                }

                // special characters like ^, $, ., etc..
                else if (HAS.call(specialChars,ch))
                {
                    if (wordlen)
                    {
                        sequence.push(Node(T_STRING, word));
                        word = '';
                        wordlen = 0;
                    }
                    flag = {};
                    flag[specialChars[ch]] = 1;
                    sequence.push(Node(T_SPECIAL, ch, flag));
                }

                else
                {
                    word += ch;
                    wordlen += 1;
                }
            }
        }

        if (wordlen)
        {
            sequence.push(Node(T_STRING, word));
            word = '';
            wordlen = 0;
        }

        if (alternation.length)
        {
            alternation.push(Node(T_SEQUENCE, sequence));
            sequence = [];
            flag = {};
            flags[specialChars['|']] = 1;
            return Node(T_ALTERNATION, alternation, flag);
        }
        return Node(T_SEQUENCE, sequence);
    }
;

// https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_Expressions
// https://docs.python.org/3/library/re.html
// http://php.net/manual/en/reference.pcre.pattern.syntax.php
// A simple regular expression analyzer
function Analyzer(re, delim, flavor)
{
    if (!(this instanceof Analyzer)) return new Analyzer(re, delim, flavor);
    if (re) this.input(re, delim, flavor);
}
Analyzer.VERSION = __version__;
Analyzer[PROTO] = {

    constructor: Analyzer,

    ast: null,
    flavor: '',
    re: null,
    fl: null,
    src: null,
    grp: null,
    min: null,
    max: null,
    ch: null,
    bc: true,

    dispose: function() {
        var self = this;
        self.ast = null;
        self.flavor = null;
        self.re = null;
        self.fl = null;
        self.src = null;
        self.grp = null;
        self.min = null;
        self.max = null;
        self.ch = null;
        return self;
    },

    reset: function() {
        var self = this;
        self.ast = null;
        self.src = null;
        self.grp = null;
        self.min = null;
        self.max = null;
        self.ch = null;
        return self;
    },

    backwardsCompatible: function(enable) {
        this.bc = !!enable;
        return this;
    },

    input: function(re, delim, flavor) {
        var self = this;
        if (!arguments.length) return self.re;
        if (re)
        {
            delim = false === delim ? false : (delim || '/');
            var l, ch, fl = {};
            re = re.toString();
            l = re.length;

            if (delim)
            {
                // parse re flags, if any
                while (0 < l)
                {
                    ch = re[CHAR](l-1);
                    if (delim === ch) break;
                    else {fl[ch] = 1; --l;}
                }

                if (0 < l)
                {
                    // remove re delimiters
                    if ((delim === re[CHAR](0)) && (delim === re[CHAR](l-1))) re = re.slice(1, l-1);
                    else re = re.slice(0, l);
                }
                else
                {
                    re = '';
                }
            }

            // re is different, reset the ast, etc
            if (self.re !== re) self.reset();
            self.re = re; self.fl = fl; self.flavor = String(flavor || '');
        }
        return self;
    },

    analyze: function() {
        var self = this;
        if ((null != self.re) && (null === self.ast))
        {
            var re = new RE_OBJ(self.re, self.fl, self.flavor);
            self.ast = analyze_re(re);
            re.dispose();
        }
        return self;
    },

    synthesize: function(escaped) {
        var self = this, state, re;
        if (null == self.re) return self;
        if (null === self.ast)
        {
            self.analyze();
            self.src = null;
            self.grp = null;
        }
        if (null === self.src)
        {
            state = {
                MAP                 : T_SEQUENCE|T_ALTERNATION|T_GROUP|T_CHARGROUP|T_QUANTIFIER,
                REDUCE              : T_UNICODECHAR|T_HEXCHAR|T_SPECIAL|T_CHARS|T_CHARRANGE|T_STRING,
                IGNORE              : T_COMMENT,
                map                 : map_src,
                reduce              : reduce_src,
                escaped             : false !== escaped,
                compatibility       : self.bc,
                group               : {}
            };
            re = walk({src:'',group:{}}, self.ast, state);
            self.src = re.src; self.grp = re.group;
        }
        return self;
    },

    source: function() {
        var self = this;
        if (null == self.re) return null;
        if (null === self.src) self.synthesize();
        return self.src;
    },

    groups: function(raw) {
        var self = this;
        if (null == self.re) return null;
        if (null === self.grp) self.synthesize();
        return true === raw ? sel.grp : clone(self.grp);
    },

    compile: function(flags, notBackwardsCompatible) {
        var self = this;
        if (null == self.re) return null;
        flags = flags || self.fl || {};
        return new RegExp(self.source(), (flags.g||flags.G?'g':'')+(flags.i||flags.I?'i':'')+(flags.m||flags.M?'m':'')+(flags.y||flags.Y?'y':'')+(flags.u?'u':'')+(flags.d?'d':'')+(flags.s?'s':''));
    },

    tree: function(flat) {
        var self = this;
        if (null == self.re) return null;
        if (null === self.ast) self.analyze();
        return true===flat ? self.ast.toObject() : self.ast;
    },

    // experimental feature
    sample: function(maxlen, numsamples) {
        var self = this, state;
        if (null == self.re) return null;
        if (null === self.ast) self.analyze();
        state = {
            MAP                 : T_SEQUENCE|T_ALTERNATION|T_GROUP|T_CHARGROUP|T_QUANTIFIER,
            REDUCE              : T_UNICODECHAR|T_HEXCHAR|T_SPECIAL|T_CHARS|T_CHARRANGE|T_STRING,
            IGNORE              : T_COMMENT,
            map                 : map_any,
            reduce              : reduce_str,
            maxLength           : (maxlen|0) || 1,
            isCaseInsensitive   : null != self.fl.i,
            group               : {}
        };
        numsamples = (numsamples|0) || 1;
        if (1 < numsamples)
        {
            var samples = new Array(numsamples);
            for (var i=0; i<numsamples; ++i) samples[i] = walk('', self.ast, state);
            return samples;
        }
        return walk('', self.ast, state);
    },

    // experimental feature
    minimum: function() {
        var self = this, state;
        if (null == self.re) return 0;
        if (null === self.ast)
        {
            self.analyze( );
            self.min = null;
        }
        if (null === self.min)
        {
            state = {
                MAP                 : T_SEQUENCE|T_ALTERNATION|T_GROUP|T_CHARGROUP|T_QUANTIFIER,
                REDUCE              : T_UNICODECHAR|T_HEXCHAR|T_SPECIAL|T_CHARS|T_CHARRANGE|T_STRING,
                IGNORE              : T_COMMENT,
                map                 : map_min,
                reduce              : reduce_len,
                group               : {}
            };
            self.min = walk(0, self.ast, state)|0;
        }
        return self.min;
    },

    // experimental feature
    maximum: function() {
        var self = this, state;
        if (null == self.re) return 0;
        if (null === self.ast)
        {
            self.analyze();
            self.max = null;
        }
        if (null === self.max)
        {
            state = {
                MAP                 : T_SEQUENCE|T_ALTERNATION|T_GROUP|T_CHARGROUP|T_QUANTIFIER,
                REDUCE              : T_UNICODECHAR|T_HEXCHAR|T_SPECIAL|T_CHARS|T_CHARRANGE|T_STRING,
                IGNORE              : T_COMMENT,
                map                 : map_max,
                reduce              : reduce_len,
                group               : {}
            };
            self.max = walk(0, self.ast, state);
        }
        return self.max;
    },

    // experimental feature
    peek: function() {
        var self = this, state, isCaseInsensitive, peek, n, c, p, cases;
        if (null == self.re) return null;
        if (null === self.ast)
        {
            self.analyze();
            self.ch = null;
        }
        if (null === self.ch)
        {
            state = {
                MAP                 : T_SEQUENCE|T_ALTERNATION|T_GROUP|T_CHARGROUP|T_QUANTIFIER,
                REDUCE              : T_UNICODECHAR|T_HEXCHAR|T_SPECIAL|T_CHARS|T_CHARRANGE|T_STRING,
                IGNORE              : T_COMMENT,
                map                 : map_1st,
                reduce              : reduce_peek,
                group               : {},
            };
            self.ch = walk({positive:{},negative:{}}, self.ast, state);
        }
        peek = {positive:clone(self.ch.positive), negative:clone(self.ch.negative)};
        isCaseInsensitive = null != self.fl.i;
        for (n in peek)
        {
            cases = {};
            // either positive or negative
            p = peek[n];
            for (c in p)
            {
                if ('\\d' === c)
                {
                    delete p[c];
                    cases = concat(cases, character_range('0', '9'));
                }

                else if ('\\s' === c)
                {
                    delete p[c];
                    cases = concat(cases, ['\f','\n','\r','\t','\v','\u00A0','\u2028','\u2029']);
                }

                else if ('\\w' === c)
                {
                    delete p[c];
                    cases = concat(cases, ['_'].concat(character_range('0', '9')).concat(character_range('a', 'z')).concat(character_range('A', 'Z')));
                }

                else if ('\\b' === c)
                {
                    delete p[c];
                    cases[ specialChars['b'] ] = 1;
                }

                else if ('\\.' === c)
                {
                    delete p[c];
                    cases[ specialChars['.'] ] = 1;
                }

                /*else if ('\\^' === c)
                {
                    delete p[c];
                    cases[ specialChars['^'] ] = 1;
                }

                else if ('\\$' === c)
                {
                    delete p[c];
                    cases[ specialChars['$'] ] = 1;
                }*/

                else if ( (ESC !== c[CHAR](0)) && isCaseInsensitive )
                {
                    cases[ c.toLowerCase() ] = 1;
                    cases[ c.toUpperCase() ] = 1;
                }

                else if ( ESC === c[CHAR](0) )
                {
                    delete p[c];
                }
            }
            peek[n] = concat(p, cases);
        }
        return peek;
    }
};
// alias
Analyzer[PROTO].set = Analyzer[PROTO].input;
/*
// custom method to access named groups feature, if any
RegExp[PROTO].$group = null;
RegExp[PROTO].group = function( group ){
    group = group || 0;
    return this.$group && this.$group.hasOwnProperty(group) ? this.$group[group] : group;
};
*/

// A simple regular expression composer
function Composer()
{
    var self = this;
    if (!(self instanceof Composer)) return new Composer();
    self.re = null;
    self.reset();
}
Composer.VERSION = __version__;
Composer[PROTO] = {

    constructor: Composer,

    re: null,
    g: 0,
    grp: null,
    level: 0,
    ast: null,

    dispose: function() {
        var self = this;
        self.re = null;
        self.g = null;
        self.grp = null;
        self.level = null;
        self.ast = null;
        return self;
    },

    reset: function() {
        var self = this;
        self.g = 0;
        self.grp = {};
        self.level = 0;
        self.ast = [{node: [], type: T_SEQUENCE, flag: ''}];
        return self;
    },

    compose: function(/* flags */) {
        var self = this,
            fl = slice(arguments).join(''),
            src = self.ast[0].node.join('');
        self.re = {
            source  : src,
            flags   : fl,
            groups  : self.grp,
            pattern : RE(src, fl)
        };
        self.reset();
        return self.re;
    },

    partial: function(reset) {
        var self = this, re = self.ast[0].node.join('');
        if (false !== reset) self.reset();
        return re;
    },

    token: function(token, escaped) {
        var self = this;
        if (null != token)
            self.ast[self.level].node.push(escaped ? esc_re(String(token), ESC) : String(token));
        return self;
    },

    literal: function(literal) {
        return this.token(String(literal), true);
    },

    regexp: function(re) {
        return this.token(String(re), false);
    },

    SOL: function() {
        var self = this;
        self.ast[self.level].node.push('^');
        return self;
    },

    SOF: function() {
        return this.SOL();
    },

    EOL: function() {
        var self = this;
        self.ast[self.level].node.push('$');
        return self;
    },

    EOF: function() {
        return this.EOL();
    },

    LF: function() {
        var self = this;
        self.ast[self.level].node.push(ESC+'n');
        return self;
    },

    CR: function() {
        var self = this;
        self.ast[self.level].node.push(ESC+'r');
        return self;
    },

    TAB: function() {
        var self = this;
        self.ast[self.level].node.push(ESC+'t');
        return self;
    },

    CTRL: function(code) {
        var self = this;
        self.ast[self.level].node.push(ESC+'c'+(code||0));
        return self;
    },

    HEX: function(code) {
        var self = this;
        self.ast[self.level].node.push(ESC+'x'+pad(code||0, 2));
        return self;
    },

    UNICODE: function(code, uni) {
        var self = this;
        self.ast[self.level].node.push(true === uni ? ESC+'u{'+String(code||0)+'}' : ESC+'u'+pad(code||0, 4));
        return self;
    },

    backSpace: function() {
        var self = this;
        self.ast[self.level].node.push('['+ESC+'b]');
        return self;
    },

    any: function(multiline) {
        var self = this;
        self.ast[self.level].node.push(multiline ? '['+ESC+'s'+ESC+'S]' : '.');
        return self;
    },

    space: function(positive) {
        var self = this;
        if (arguments.length < 1) positive = true;
        self.ast[self.level].node.push(!positive ? ESC+'S' : ESC+'s');
        return self;
    },

    digit: function(positive) {
        var self = this;
        if (arguments.length < 1) positive = true;
        self.ast[self.level].node.push(!positive ? ESC+'D' : ESC+'d');
        return self;
    },

    word: function(positive) {
        var self = this;
        if (arguments.length < 1) positive = true;
        self.ast[self.level].node.push(!positive ? ESC+'W' : ESC+'w');
        return self;
    },

    boundary: function(positive) {
        var self = this;
        if (arguments.length < 1) positive = true;
        self.ast[self.level].node.push(!positive ? ESC+'B' : ESC+'b');
        return self;
    },

    characters: function() {
        var self = this;
        if (T_CHARGROUP === self.ast[self.level].type)
            self.ast[self.level].node.push(getArgs(arguments,1).map(function(c){ return esc_re(String(c), ESC, 1); }).join(''));
        return self;
    },

    range: function(start, end) {
        var self = this;
        if (null != start && null != end && T_CHARGROUP === self.ast[self.level].type)
            self.ast[self.level].node.push(esc_re(String(start), ESC, 1)+'-'+esc_re(String(end), ESC, 1));
        return self;
    },

    backReference: function(n) {
        var self = this;
        self.ast[self.level].node.push(ESC+(HAS.call(self.grp, n) ? self.grp[n] : n|0));
        return self;
    },

    repeat: function(min, max, greedy) {
        var self = this;
        if (null == min) return self;
        if (arguments.length < 3) greedy = true;
        var repeat = (null==max || min===max ? ('{'+String(min)+'}') : ('{'+String(min)+','+String(max)+'}')) + (!greedy ? '?' : '');
        self.ast[self.level].node[self.ast[self.level].node.length-1] += repeat;
        return self;
    },

    zeroOrOne: function(greedy) {
        var self = this;
        if (arguments.length < 1) greedy = true;
        self.ast[self.level].node[self.ast[self.level].node.length-1] += (!greedy ? '??' : '?');
        return self;
    },

    zeroOrMore: function(greedy) {
        var self = this;
        if (arguments.length < 1) greedy = true;
        self.ast[self.level].node[self.ast[self.level].node.length-1] += (!greedy ? '*?' : '*');
        return self;
    },

    oneOrMore: function(greedy) {
        var self = this;
        if (arguments.length < 1) greedy = true;
        self.ast[self.level].node[self.ast[self.level].node.length-1] += (!greedy ? '+?' : '+');
        return self;
    },

    alternate: function() {
        var self = this;
        self.level++;
        self.ast.push({node: [], type: T_ALTERNATION, flag: '', sequences: []});
        return self;
    },

    either: function() {
        return this.alternate();
    },

    or_: function() {
        var self = this, ast = self.ast[self.level];
        if ((T_ALTERNATION === ast.type) && ast.node.length)
        {
            ast.sequences.push(ast.node.join(''));
            ast.node = [];
        }
        return self;
    },

    group: function(opts, v) {
        var self = this, type = T_GROUP, fl = '';
        if (is_string(opts))
        {
            fl = opts; opts = {};
            opts[fl] = v; fl = '';
        }
        else
        {
            opts = opts || {};
        }
        if (!!opts['name'] || !!opts['named'])
        {
            self.g++;
            self.grp[self.g] = self.g;
            self.grp[opts.name||opts.named] = self.g;
        }
        else if ((true === opts['lookahead']) || (false === opts['lookahead']))
        {
            fl = false === opts['lookahead'] ? '?!' : '?=';
        }
        else if ((true === opts['lookbehind']) || (false === opts['lookbehind']))
        {
            fl = false === opts['lookbehind'] ? '?<!' : '?<=';
        }
        else if (true === opts['nocapture'])
        {
            fl = '?:';
        }
        else if ((true === opts['characters']) || (false === opts['characters']))
        {
            type = T_CHARGROUP;
            fl = false === opts['characters'] ? '^' : '';
        }
        else
        {
            self.g++;
            self.grp[self.g] = self.g;
        }
        self.level++;
        self.ast.push({node: [], type: type, flag: fl});
        return self;
    },

    subGroup: function(opts) {
        return this.group(opts);
    },

    characterGroup: function(positive) {
        return this.group({'characters':false!==positive});
    },

    namedGroup: function(name) {
        return this.group({'name':name});
    },

    nonCaptureGroup: function() {
        return this.group({'nocapture':true});
    },

    lookAheadGroup: function(positive) {
        return this.group({'lookahead':false!==positive});
    },

    lookBehindGroup: function(positive) {
        return this.group({'lookbehind':false!==positive});
    },

    end: function(n) {
        var self = this, prev, type, flag, part, sequences;
        n = (arguments.length ? n|0 : 1) || 1;
        // support ending multiple blocks at once
        while (n--)
        {
            prev = self.ast.length ? self.ast.pop() : null;
            type = prev ? prev.type : 0;
            flag = prev ? prev.flag : '';
            part = prev ? prev.node : [];
            if (T_ALTERNATION === type)
            {
                sequences = prev ? prev.sequences : [];
                part = !part.length ? sequences : sequences.concat(part.join(''));
            }
            if (0 < self.level)
            {
                --self.level;
                if (T_ALTERNATION === type)
                    self.ast[self.level].node.push(part.join('|'));
                else if (T_GROUP === type)
                    self.ast[self.level].node.push('('+flag+part.join('')+')');
                else if (T_CHARGROUP === type)
                    self.ast[self.level].node.push('['+flag+part.join('')+']');
                else
                    self.ast[self.level].node.push(part.join(''));
            }
        }
        return self;
    }
};
// aliases
var CP = Composer[PROTO];
CP.startOfLine = CP.SOL;
CP.endOfLine = CP.EOL;
CP.startOfInput = CP.SOF;
CP.endOfInput = CP.EOF;
CP.match = CP.token;
CP.sub = CP.regexp;
CP.lineFeed = CP.LF;
CP.carriageReturn = CP.CR;
CP.tabulate = CP.TAB;
CP.wordBoundary = CP.boundary;
CP.chars = CP.characters;
CP.charGroup = CP.characterGroup;
CP.namedSubGroup = CP.namedGroup;
CP.nonCaptureSubGroup = CP.nonCaptureGroup;
CP.lookAheadSubGroup = CP.lookAheadGroup;
CP.lookBehindSubGroup = CP.lookBehindGroup;

var Regex = {
    VERSION     : __version__,
    Node        : Node,
    Analyzer    : Analyzer,
    Composer    : Composer
};
/* export the module */
return Regex;
})();
