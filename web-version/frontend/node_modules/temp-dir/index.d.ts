/**
Get the real path of the system temp directory.

@example
```
import * as os from 'os';
import tempDirectory = require('temp-dir');

console.log(tempDirectory);
//=> '/private/var/folders/3x/jf5977fn79jbglr7rk0tq4d00000gn/T'

console.log(os.tmpdir());
//=> '/var/folders/3x/jf5977fn79jbglr7rk0tq4d00000gn/T' // <= Symlink
```
*/
declare const tempDirectory: string;

export = tempDirectory;
