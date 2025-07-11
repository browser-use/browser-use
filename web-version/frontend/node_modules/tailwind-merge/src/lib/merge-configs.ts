import { AnyConfig, ConfigExtension } from './types'

/**
 * @param baseConfig Config where other config will be merged into. This object will be mutated.
 * @param configExtension Partial config to merge into the `baseConfig`.
 */
export const mergeConfigs = <ClassGroupIds extends string, ThemeGroupIds extends string = never>(
    baseConfig: AnyConfig,
    {
        cacheSize,
        prefix,
        separator,
        experimentalParseClassName,
        extend = {},
        override = {},
    }: ConfigExtension<ClassGroupIds, ThemeGroupIds>,
) => {
    overrideProperty(baseConfig, 'cacheSize', cacheSize)
    overrideProperty(baseConfig, 'prefix', prefix)
    overrideProperty(baseConfig, 'separator', separator)
    overrideProperty(baseConfig, 'experimentalParseClassName', experimentalParseClassName)

    for (const configKey in override) {
        overrideConfigProperties(
            baseConfig[configKey as keyof typeof override],
            override[configKey as keyof typeof override],
        )
    }

    for (const key in extend) {
        mergeConfigProperties(
            baseConfig[key as keyof typeof extend],
            extend[key as keyof typeof extend],
        )
    }

    return baseConfig
}

const overrideProperty = <T extends object, K extends keyof T>(
    baseObject: T,
    overrideKey: K,
    overrideValue: T[K] | undefined,
) => {
    if (overrideValue !== undefined) {
        baseObject[overrideKey] = overrideValue
    }
}

const overrideConfigProperties = (
    baseObject: Partial<Record<string, readonly unknown[]>>,
    overrideObject: Partial<Record<string, readonly unknown[]>> | undefined,
) => {
    if (overrideObject) {
        for (const key in overrideObject) {
            overrideProperty(baseObject, key, overrideObject[key])
        }
    }
}

const mergeConfigProperties = (
    baseObject: Partial<Record<string, readonly unknown[]>>,
    mergeObject: Partial<Record<string, readonly unknown[]>> | undefined,
) => {
    if (mergeObject) {
        for (const key in mergeObject) {
            const mergeValue = mergeObject[key]

            if (mergeValue !== undefined) {
                baseObject[key] = (baseObject[key] || []).concat(mergeValue)
            }
        }
    }
}
