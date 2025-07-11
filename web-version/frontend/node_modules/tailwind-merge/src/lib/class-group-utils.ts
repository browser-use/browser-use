import {
    AnyClassGroupIds,
    AnyConfig,
    AnyThemeGroupIds,
    ClassGroup,
    ClassValidator,
    Config,
    ThemeGetter,
    ThemeObject,
} from './types'

export interface ClassPartObject {
    nextPart: Map<string, ClassPartObject>
    validators: ClassValidatorObject[]
    classGroupId?: AnyClassGroupIds
}

interface ClassValidatorObject {
    classGroupId: AnyClassGroupIds
    validator: ClassValidator
}

const CLASS_PART_SEPARATOR = '-'

export const createClassGroupUtils = (config: AnyConfig) => {
    const classMap = createClassMap(config)
    const { conflictingClassGroups, conflictingClassGroupModifiers } = config

    const getClassGroupId = (className: string) => {
        const classParts = className.split(CLASS_PART_SEPARATOR)

        // Classes like `-inset-1` produce an empty string as first classPart. We assume that classes for negative values are used correctly and remove it from classParts.
        if (classParts[0] === '' && classParts.length !== 1) {
            classParts.shift()
        }

        return getGroupRecursive(classParts, classMap) || getGroupIdForArbitraryProperty(className)
    }

    const getConflictingClassGroupIds = (
        classGroupId: AnyClassGroupIds,
        hasPostfixModifier: boolean,
    ) => {
        const conflicts = conflictingClassGroups[classGroupId] || []

        if (hasPostfixModifier && conflictingClassGroupModifiers[classGroupId]) {
            return [...conflicts, ...conflictingClassGroupModifiers[classGroupId]!]
        }

        return conflicts
    }

    return {
        getClassGroupId,
        getConflictingClassGroupIds,
    }
}

const getGroupRecursive = (
    classParts: string[],
    classPartObject: ClassPartObject,
): AnyClassGroupIds | undefined => {
    if (classParts.length === 0) {
        return classPartObject.classGroupId
    }

    const currentClassPart = classParts[0]!
    const nextClassPartObject = classPartObject.nextPart.get(currentClassPart)
    const classGroupFromNextClassPart = nextClassPartObject
        ? getGroupRecursive(classParts.slice(1), nextClassPartObject)
        : undefined

    if (classGroupFromNextClassPart) {
        return classGroupFromNextClassPart
    }

    if (classPartObject.validators.length === 0) {
        return undefined
    }

    const classRest = classParts.join(CLASS_PART_SEPARATOR)

    return classPartObject.validators.find(({ validator }) => validator(classRest))?.classGroupId
}

const arbitraryPropertyRegex = /^\[(.+)\]$/

const getGroupIdForArbitraryProperty = (className: string) => {
    if (arbitraryPropertyRegex.test(className)) {
        const arbitraryPropertyClassName = arbitraryPropertyRegex.exec(className)![1]
        const property = arbitraryPropertyClassName?.substring(
            0,
            arbitraryPropertyClassName.indexOf(':'),
        )

        if (property) {
            // I use two dots here because one dot is used as prefix for class groups in plugins
            return 'arbitrary..' + property
        }
    }
}

/**
 * Exported for testing only
 */
export const createClassMap = (config: Config<AnyClassGroupIds, AnyThemeGroupIds>) => {
    const { theme, prefix } = config
    const classMap: ClassPartObject = {
        nextPart: new Map<string, ClassPartObject>(),
        validators: [],
    }

    const prefixedClassGroupEntries = getPrefixedClassGroupEntries(
        Object.entries(config.classGroups),
        prefix,
    )

    prefixedClassGroupEntries.forEach(([classGroupId, classGroup]) => {
        processClassesRecursively(classGroup, classMap, classGroupId, theme)
    })

    return classMap
}

const processClassesRecursively = (
    classGroup: ClassGroup<AnyThemeGroupIds>,
    classPartObject: ClassPartObject,
    classGroupId: AnyClassGroupIds,
    theme: ThemeObject<AnyThemeGroupIds>,
) => {
    classGroup.forEach((classDefinition) => {
        if (typeof classDefinition === 'string') {
            const classPartObjectToEdit =
                classDefinition === '' ? classPartObject : getPart(classPartObject, classDefinition)
            classPartObjectToEdit.classGroupId = classGroupId
            return
        }

        if (typeof classDefinition === 'function') {
            if (isThemeGetter(classDefinition)) {
                processClassesRecursively(
                    classDefinition(theme),
                    classPartObject,
                    classGroupId,
                    theme,
                )
                return
            }

            classPartObject.validators.push({
                validator: classDefinition,
                classGroupId,
            })

            return
        }

        Object.entries(classDefinition).forEach(([key, classGroup]) => {
            processClassesRecursively(
                classGroup,
                getPart(classPartObject, key),
                classGroupId,
                theme,
            )
        })
    })
}

const getPart = (classPartObject: ClassPartObject, path: string) => {
    let currentClassPartObject = classPartObject

    path.split(CLASS_PART_SEPARATOR).forEach((pathPart) => {
        if (!currentClassPartObject.nextPart.has(pathPart)) {
            currentClassPartObject.nextPart.set(pathPart, {
                nextPart: new Map(),
                validators: [],
            })
        }

        currentClassPartObject = currentClassPartObject.nextPart.get(pathPart)!
    })

    return currentClassPartObject
}

const isThemeGetter = (func: ClassValidator | ThemeGetter): func is ThemeGetter =>
    (func as ThemeGetter).isThemeGetter

const getPrefixedClassGroupEntries = (
    classGroupEntries: Array<[classGroupId: string, classGroup: ClassGroup<AnyThemeGroupIds>]>,
    prefix: string | undefined,
): Array<[classGroupId: string, classGroup: ClassGroup<AnyThemeGroupIds>]> => {
    if (!prefix) {
        return classGroupEntries
    }

    return classGroupEntries.map(([classGroupId, classGroup]) => {
        const prefixedClassGroup = classGroup.map((classDefinition) => {
            if (typeof classDefinition === 'string') {
                return prefix + classDefinition
            }

            if (typeof classDefinition === 'object') {
                return Object.fromEntries(
                    Object.entries(classDefinition).map(([key, value]) => [prefix + key, value]),
                )
            }

            return classDefinition
        })

        return [classGroupId, prefixedClassGroup]
    })
}
