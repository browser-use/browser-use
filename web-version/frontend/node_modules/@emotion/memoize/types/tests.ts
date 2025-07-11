import memoize from '@emotion/memoize'

// $ExpectType string[]
memoize((arg: string) => [arg])('foo')

// $ExpectError
memoize((arg: number) => [arg])
