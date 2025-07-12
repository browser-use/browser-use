import { createTailwindMerge } from './create-tailwind-merge'
import { getDefaultConfig } from './default-config'
import { mergeConfigs } from './merge-configs'
import { AnyConfig, ConfigExtension, DefaultClassGroupIds, DefaultThemeGroupIds } from './types'

type CreateConfigSubsequent = (config: AnyConfig) => AnyConfig

export const extendTailwindMerge = <
    AdditionalClassGroupIds extends string = never,
    AdditionalThemeGroupIds extends string = never,
>(
    configExtension:
        | ConfigExtension<
              DefaultClassGroupIds | AdditionalClassGroupIds,
              DefaultThemeGroupIds | AdditionalThemeGroupIds
          >
        | CreateConfigSubsequent,
    ...createConfig: CreateConfigSubsequent[]
) =>
    typeof configExtension === 'function'
        ? createTailwindMerge(getDefaultConfig, configExtension, ...createConfig)
        : createTailwindMerge(
              () => mergeConfigs(getDefaultConfig(), configExtension),
              ...createConfig,
          )
