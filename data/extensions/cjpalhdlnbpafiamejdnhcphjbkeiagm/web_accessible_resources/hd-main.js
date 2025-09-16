/*******************************************************************************

    uBlock Origin - a browser extension to block requests.
    Copyright (C) 2019-present Raymond Hill

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

(function() {
    'use strict';
    const l = {};
    const noopfn = function() {
    };
    const props = [
        "$j","Ad","Bd","Cd","Dd","Ed","Fd","Gd","Hd","Id","Jd","Nj","Oc","Pc","Pe",
        "Qc","Qe","Rc","Re","Ri","Sc","Tc","Uc","Vc","Wc","Wg","Xc","Xg","Yc","Yd",
        "ad","ae","bd","bf","cd","dd","ed","ef","ek","fd","fg","fh","fk","gd","hd",
        "ig","ij","jd","kd","ke","ld","md","mi","nd","od","oh","pd","pf","qd","rd",
        "sd","td","ud","vd","wd","wg","xd","xh","yd","zd",
        "$d","$e","$k","Ae","Af","Aj","Be","Ce","De","Ee","Ek","Eo","Ep","Fe","Fo",
        "Ge","Gh","Hk","Ie","Ip","Je","Ke","Kk","Kq","Le","Lh","Lk","Me","Mm","Ne",
        "Oe","Pe","Qe","Re","Rp","Se","Te","Ue","Ve","Vp","We","Xd","Xe","Yd","Ye",
        "Zd","Ze","Zf","Zk","ae","af","al","be","bf","bg","ce","cp","df","di","ee",
        "ef","fe","ff","gf","gm","he","hf","ie","je","jf","ke","kf","kl","le","lf",
        "lk","mf","mg","mn","nf","oe","of","pe","pf","pg","qe","qf","re","rf","se",
        "sf","te","tf","ti","ue","uf","ve","vf","we","wf","wg","wi","xe","ye","yf",
        "yk","yl","ze","zf","zk"
    ];
    for ( let i = 0; i < props.length; i++ ) {
        l[props[i]] = noopfn;
    }
    window.L = window.J = l;
})();
