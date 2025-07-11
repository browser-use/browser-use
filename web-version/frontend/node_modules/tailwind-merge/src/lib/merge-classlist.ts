import { ConfigUtils } from './config-utils'
import { IMPORTANT_MODIFIER, sortModifiers } from './parse-class-name'

const SPLIT_CLASSES_REGEX = /\s+/

export const mergeClassList = (classList: string, configUtils: ConfigUtils) => {
    const { parseClassName, getClassGroupId, getConflictingClassGroupIds } = configUtils

    /**
     * Set of classGroupIds in following format:
     * `{importantModifier}{variantModifiers}{classGroupId}`
     * @example 'float'
     * @example 'hover:focus:bg-color'
     * @example 'md:!pr'
     */
    const classGroupsInConflict: string[] = []
    const classNames = classList.trim().split(SPLIT_CLASSES_REGEX)

    let result = ''

    for (let index = classNames.length - 1; index >= 0; index -= 1) {
        const originalClassName = classNames[index]!

        const { modifiers, hasImportantModifier, baseClassName, maybePostfixModifierPosition } =
            parseClassName(originalClassName)

        let hasPostfixModifier = Boolean(maybePostfixModifierPosition)
        let classGroupId = getClassGroupId(
            hasPostfixModifier
                ? baseClassName.substring(0, maybePostfixModifierPosition)
                : baseClassName,
        )

        if (!classGroupId) {
            if (!hasPostfixModifier) {
                // Not a Tailwind class
                result = originalClassName + (result.length > 0 ? ' ' + result : result)
                continue
            }

            classGroupId = getClassGroupId(baseClassName)

            if (!classGroupId) {
                // Not a Tailwind class
                result = originalClassName + (result.length > 0 ? ' ' + result : result)
                continue
            }

            hasPostfixModifier = false
        }

        const variantModifier = sortModifiers(modifiers).join(':')

        const modifierId = hasImportantModifier
            ? variantModifier + IMPORTANT_MODIFIER
            : variantModifier

        const classId = modifierId + classGroupId

        if (classGroupsInConflict.includes(classId)) {
            // Tailwind class omitted due to conflict
            continue
        }

        classGroupsInConflict.push(classId)

        const conflictGroups = getConflictingClassGroupIds(classGroupId, hasPostfixModifier)
        for (let i = 0; i < conflictGroups.length; ++i) {
            const group = conflictGroups[i]!
            classGroupsInConflict.push(modifierId + group)
        }

        // Tailwind class not in conflict
        result = originalClassName + (result.length > 0 ? ' ' + result : result)
    }

    return result
}
