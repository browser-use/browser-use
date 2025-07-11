# SMOB 🧪

[![npm version](https://badge.fury.io/js/smob.svg)](https://badge.fury.io/js/smob)
[![main](https://github.com/tada5hi/smob/actions/workflows/main.yml/badge.svg)](https://github.com/tada5hi/smob/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/tada5hi/smob/branch/master/graph/badge.svg?token=0VL41WO0CG)](https://codecov.io/gh/tada5hi/smob)
[![Known Vulnerabilities](https://snyk.io/test/github/Tada5hi/smob/badge.svg?targetFile=package.json)](https://snyk.io/test/github/Tada5hi/smob?targetFile=package.json)
[![semantic-release: angular](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)

A zero dependency library to **s**afe **m**erge **ob**jects and arrays with customizable behavior.

**Table of Contents**

- [Installation](#installation)
- [Usage](#usage)
  - [Merger](#merger)
  - [Utils](#utils)
- [License](#license)

## Installation

```bash
npm install smob --save
```

## Usage

```typescript
import { merge } from "smob";

const output = merge(...sources);
```

The following merge options are set by default:
- **array**: `true` Merge object array properties.
- **arrayDistinct**: `false` Remove duplicates, when merging array elements.
- **arrayPriority**: `left` (options.priority) The source aka leftmost array has by **default** the highest priority.
- **clone**: `false` Deep clone input sources.
- **inPlace**: `false` Merge sources in place.
- **priority**: `left` The source aka leftmost object has by **default** the highest priority.

The merge behaviour can be changed by creating a custom [merger](#merger).

**Arguments**
- sources `(any[] | Record<string, any>)[]`: The source arrays/objects.

```typescript
import { merge } from 'smob';

merge({ a: 1 }, { b: 2 }, { c: 3 });
// { a: 1, b: 2, c: 3 }

merge(['foo'], ['bar']);
// ['foo', 'bar']

```

### Merger

A custom merger can simply be created by using the `createMerger` method.

**Array**
```typescript
import { createMerger } from 'smob';

const merge = createMerger({ array: false });

merge({ a: [1,2,3] }, { a: [4,5,6] });
// { a: [1,2,3] }
```

**ArrayDistinct**
```typescript
import { createMerger } from 'smob';

const merge = createMerger({ arrayDistinct: true });

merge({ a: [1,2,3] }, { a: [3,4,5] });
// { a: [1,2,3,4,5] }
```

**Priority**
```typescript
import { createMerger } from 'smob';

const merge = createMerger({ priority: 'right' });

merge({ a: 1 }, { a: 2 }, { a: 3 })
// { a: 3 }
```

**Strategy**
```typescript
import { createMerger } from 'smob';

const merge = createMerger({
    strategy: (target, key, value) => {
        if (
            typeof target[key] === 'number' &&
            typeof value === 'number'
        ) {
            target[key] += value;
            return target;
        }
    }
});

merge({ a: 1 }, { a: 2 }, { a: 3 });
// { a: 6 }
```

A returned value indicates that the strategy has been applied.

## Utils

### distinctArray

```typescript
import { distinctArray } from 'smob';

distnctArray(['foo', 'bar', 'foo']);
// ['foo', 'bar']
```

The function also removes non-primitive
elements that are identical by value or reference.

**Objects**
```typescript
import { distinctArray } from 'smob';

distinctArray([{ foo: 'bar' }, { foo: 'bar' }]);
// [{ foo: 'bar' }]
```

**Arrays**
```typescript
import { distinctArray } from 'smob';

distinctArray([['foo', 'bar'], ['foo', 'bar']]);
// [['foo', 'bar']]
```

### isEqual

Checks if two (non-primitive) elements
are identical by value or reference.

````typescript
import { isEqual } from 'smob';

isEqual({foo: 'bar'}, {foo: 'bar'});
// true

isEqual(['foo', 'bar'], ['foo', 'bar']);
// true
````

## License

Made with 💚

Published under [MIT License](./LICENSE).
