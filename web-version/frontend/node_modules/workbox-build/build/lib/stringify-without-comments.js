"use strict";
/*
  Copyright 2021 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.stringifyWithoutComments = void 0;
const stringify_object_1 = __importDefault(require("stringify-object"));
const strip_comments_1 = __importDefault(require("strip-comments"));
function stringifyWithoutComments(obj) {
    return (0, stringify_object_1.default)(obj, {
        // See https://github.com/yeoman/stringify-object#transformobject-property-originalresult
        transform: (_obj, _prop, str) => {
            if (typeof _prop !== 'symbol' && typeof _obj[_prop] === 'function') {
                // Can't typify correctly stripComments
                return (0, strip_comments_1.default)(str); // eslint-disable-line
            }
            return str;
        },
    });
}
exports.stringifyWithoutComments = stringifyWithoutComments;
