// Export is needed because TypeScript complains about an error otherwise:
// Error: …/tailwind-merge/src/config-utils.ts(8,17): semantic error TS4058: Return type of exported function has or is using name 'LruCache' from external module "…/tailwind-merge/src/lru-cache" but cannot be named.
export interface LruCache<Key, Value> {
    get(key: Key): Value | undefined
    set(key: Key, value: Value): void
}

// LRU cache inspired from hashlru (https://github.com/dominictarr/hashlru/blob/v1.0.4/index.js) but object replaced with Map to improve performance
export const createLruCache = <Key, Value>(maxCacheSize: number): LruCache<Key, Value> => {
    if (maxCacheSize < 1) {
        return {
            get: () => undefined,
            set: () => {},
        }
    }

    let cacheSize = 0
    let cache = new Map<Key, Value>()
    let previousCache = new Map<Key, Value>()

    const update = (key: Key, value: Value) => {
        cache.set(key, value)
        cacheSize++

        if (cacheSize > maxCacheSize) {
            cacheSize = 0
            previousCache = cache
            cache = new Map()
        }
    }

    return {
        get(key) {
            let value = cache.get(key)

            if (value !== undefined) {
                return value
            }
            if ((value = previousCache.get(key)) !== undefined) {
                update(key, value)
                return value
            }
        },
        set(key, value) {
            if (cache.has(key)) {
                cache.set(key, value)
            } else {
                update(key, value)
            }
        },
    }
}
