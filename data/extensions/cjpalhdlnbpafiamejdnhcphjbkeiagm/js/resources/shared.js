/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
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

// Code imported from main code base and exposed as injectable scriptlets
import { ArglistParser as __ArglistParser__ } from '../arglist-parser.js';
import { JSONPath as __JSONPath__ } from '../jsonpath.js';
import { registerScriptlet } from './base.js';

/******************************************************************************/

export const ArglistParser = __ArglistParser__;

registerScriptlet(ArglistParser, {
    name: 'arglist-parser.fn',
});

export const JSONPath = __JSONPath__;

registerScriptlet(JSONPath, {
    name: 'jsonpath.fn',
});
