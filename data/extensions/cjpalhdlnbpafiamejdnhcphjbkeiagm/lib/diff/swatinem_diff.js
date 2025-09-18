/*******************************************************************************

  Key portions of code below was borrowed from:
    https://github.com/Swatinem/diff

  License is LGPL3 (thanks!) as per:
    https://github.com/Swatinem/diff/blob/b58391504759/README.md

  I chose to pick this implementation over
  https://github.com/google/diff-match-patch as suggested by CodeMirror
  because:

  - Code is clean and simple to read -- useful when unfamiliar with the diff
    algorithm, this makes changing the code easier if/when needed.

  - Smaller -- diff_match_patch comes with an extended API most of which is
    of no use to the current project.
    - diff_match_patch uncompressed: 74.7 KB
    - Swatinem's diff uncompressed: 3.66 KB

  - I can easily adapt Swatinem's diff to deal with arrays of strings, which
    is best suited for the current project -- it natively work with arrays.

  I removed portions of code which are of no use for the current project.

  I modified the diff script generator (Diff.prototype.editscript) since I
  need to generate a script which is compatible with the output of the
  diff_match_patch, as expected by CodeMirror.

  2018-12-20 gorhill:
  ===================
  There was an issue causing the wrong diff data to be issued, for instance
  when diff-ing these two URLs on a character granularity basis (failure
  point is marked):
                                                                                                                          |
  /articles/5c1a7aae1854f30006cb26f7/lede/1545239527833-shutterstock_726   01757 2-copy.jpeg?crop=0.8889xw%3A0.9988xh%3B0.1089xw%2C0xh&resize=650%3A*&output-quality=55
  /articles/5c1a*   1854f30006cb2*  /lede/15452*       -shutterstock_*     017*  2-copy.jpeg?crop=0.*   xw%3A*      h%3B0.0*  xw%2C0xh&resize=650%3A*&output-quality=55
  /articles/5c1aaea91854f30006cb2f1e/lede/1545253629235-shutterstock_106399017   2-copy.jpeg?crop=0.7749xw%3A1     xh%3B0.0391xw%2C0xh&resize=650%3A*&output-quality=55
                                                                                                                          |

  Investigating, I found what appears to be the original source on which the
  code below is based:
  - "An O(ND) Difference Algorithm for C#" by Matthias Hertel
  - http://www.mathertel.de/Diff/ViewSrc.aspx
  - https://github.com/mathertel

  There was a difference; code had been commented out in the original source:
  http://www.mathertel.de/Diff/DiffTest.aspx?oldfile=Diff.cs.v1&newfile=Diff.cs.v2

  The developer noted:
  > There have been overlapping boxes; that where analyzed partial differently.
  > One return-point is enough.

  After applying the changes to the code below, the problematic diff-ing went
  away:
                                                                                                                          |
  /articles/5c1a7aae1854f30006cb26f7/lede/1545239527833-shutterstock_726   01757 2-copy.jpeg?crop=0.8889xw%3A0.9988xh%3B0.1089xw%2C0xh&resize=650%3A*&output-quality=55
  /articles/5c1a*   1854f30006cb2*  /lede/15452*       -shutterstock_*     017*  2-copy.jpeg?crop=0.*  9xw%3A*     xh%3B0.*   xw%2C0xh&resize=650%3A*&output-quality=55
  /articles/5c1aaea91854f30006cb2f1e/lede/1545253629235-shutterstock_106399017   2-copy.jpeg?crop=0.7749xw%3A1     xh%3B0.0391xw%2C0xh&resize=650%3A*&output-quality=55
                                                                                                                          |

  So I will assume this was the issue.

  2021-07-17 gorhill:
  ===================
  Added pure diff() method which natively deals with arrays and other minor
  changes related to ES6.
  
**/

'use strict';

(function(context) {

    // CodeMirror expect these globals:
    context.DIFF_INSERT = 1;
    context.DIFF_DELETE = -1;
    context.DIFF_EQUAL = 0;
    context.diff_match_patch = function(){};

    context.diff_match_patch.prototype.diff_main = function(a, b) {
        if ( a === b ) { return [ [ 0, a ] ]; }
        const aa = a.match(/\n|[^\n]+\n?/g) || [];
        const bb = b.match(/\n|[^\n]+\n?/g) || [];
        const d = new Diff(aa, bb);
        return d.editscript();
    };

    context.diff_match_patch.prototype.diff = function(a, b) {
        const d = new Diff(a, b);
        return d.editscript();
    };

    const eqlDefault = (a, b) => a === b;

    function Diff(a, b, eql = eqlDefault) {
        this.a = a;
        this.b = b;
        this.eql = eql;

        this.moda = Array.apply(null, new Array(a.length)).map(true.valueOf, false);
        this.modb = Array.apply(null, new Array(b.length)).map(true.valueOf, false);

        // just to save some allocations:
        this.down = {};
        this.up = {};

        this.lcs(0, a.length, 0, b.length);
    }

    Diff.prototype.editscript = function Diff_editscript() {
        const moda = this.moda, modb = this.modb;
        var astart = 0, aend = moda.length;
        var bstart = 0, bend = modb.length;
        const result = [];
        while (astart < aend || bstart < bend) {
            if (astart < aend && bstart < bend) {
                if (!moda[astart] && !modb[bstart]) {
                    result.push([ 0, this.a[astart] ]);
                    astart++; bstart++;
                    continue;
                } else if (moda[astart] && modb[bstart]) {
                    result.push([ -1, this.a[astart] ]);
                    result.push([ 1, this.b[bstart] ]);
                    astart++; bstart++;
                    continue;
                }
            }
            if (astart < aend && (bstart >= bend || moda[astart])) {
                result.push([ -1, this.a[astart] ]);
                astart++;
            }
            if (bstart < bend && (astart >= aend || modb[bstart])) {
                result.push([ 1, this.b[bstart] ]);
                bstart++;
            }
        }
        return result;
    };

    Diff.prototype.lcs = function Diff_lcs(astart, aend, bstart, bend) {
        const a = this.a, b = this.b, eql = this.eql;
        // separate common head
        while (astart < aend && bstart < bend && eql(a[astart], b[bstart])) {
            astart++; bstart++;
        }
        // separate common tail
        while (astart < aend && bstart < bend && eql(a[aend - 1], b[bend - 1])) {
            aend--; bend--;
        }

        if (astart === aend) {
            // only insertions
            while (bstart < bend) {
                this.modb[bstart] = true;
                bstart++;
            }
        } else if (bend === bstart) {
            // only deletions
            while (astart < aend) {
                this.moda[astart] = true;
                astart++;
            }
        } else {
            const snake = this.snake(astart, aend, bstart, bend);

            this.lcs(astart, snake.x, bstart, snake.y);
            this.lcs(snake.x, aend, snake.y, bend);
        }
    };

    Diff.prototype.snake = function Diff_snake(astart, aend, bstart, bend) {
        const a = this.a, b = this.b, eql = this.eql;

        const N = aend - astart;
        const M = bend - bstart;

        const kdown = astart - bstart;
        const kup   = aend   - bend;

        const delta = N - M;
        const deltaOdd = delta & 1;

        const down = this.down;
        down[kdown + 1] = astart;
        const up = this.up;
        up[kup - 1] = aend;

        const Dmax = (N + M + 1) / 2;
        for (let D = 0; D <= Dmax; D++) {
            // forward path
            for (let k = kdown - D; k <= kdown + D; k += 2) {
                let x;
                if (k === kdown - D) {
                    x = down[k + 1]; // down
                } else {
                    x = down[k - 1] + 1; // right
                    if ((k < kdown + D) && (down[k + 1] >= x)) {
                        x = down[k + 1]; // down
                    }
                }
                let y = x - k;

                while (x < aend && y < bend && eql(a[x], b[y])) {
                    x++; y++; // diagonal
                }
                down[k] = x;

                if (deltaOdd && (kup - D < k) && (k < kup + D) &&
                    up[k] <= down[k]) {
                    return {
                        x: down[k],
                        y: down[k] - k,
                    //    u: up[k],
                    //    v: up[k] - k,
                    };
                }
            }

            // reverse path
            for (let k = kup - D; k <= kup + D; k += 2) {
                let x;
                if (k === kup + D) {
                    x = up[k - 1]; // up
                } else {
                    x = up[k + 1] - 1; // left
                    if ((k > kup - D) && (up[k - 1] < x)) {
                        x = up[k - 1]; // up
                    }
                }
                let y = x - k;

                while (x > astart && y > bstart && eql(a[x - 1], b[y - 1])) {
                    x--; y--; // diagonal
                }
                up[k] = x;

                if (!deltaOdd && (kdown - D <= k) && (k <= kdown + D) &&
                    up[k] <= down[k]) {
                    return {
                        x: down[k],
                        y: down[k] - k,
                    //    u: up[k],
                    //    v: up[k] - k,
                    };
                }
            }
        }
    };

    return Diff;
})(self);








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;
