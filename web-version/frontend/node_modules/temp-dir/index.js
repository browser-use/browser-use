'use strict';
const fs = require('fs');
const os = require('os');

const tempDirectorySymbol = Symbol.for('__RESOLVED_TEMP_DIRECTORY__');

if (!global[tempDirectorySymbol]) {
	Object.defineProperty(global, tempDirectorySymbol, {
		value: fs.realpathSync(os.tmpdir())
	});
}

module.exports = global[tempDirectorySymbol];
