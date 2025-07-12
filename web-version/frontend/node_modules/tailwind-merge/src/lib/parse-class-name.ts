import { AnyConfig } from './types'

export const IMPORTANT_MODIFIER = '!'

export const createParseClassName = (config: AnyConfig) => {
    const { separator, experimentalParseClassName } = config
    const isSeparatorSingleCharacter = separator.length === 1
    const firstSeparatorCharacter = separator[0]
    const separatorLength = separator.length

    // parseClassName inspired by https://github.com/tailwindlabs/tailwindcss/blob/v3.2.2/src/util/splitAtTopLevelOnly.js
    const parseClassName = (className: string) => {
        const modifiers = []

        let bracketDepth = 0
        let modifierStart = 0
        let postfixModifierPosition: number | undefined

        for (let index = 0; index < className.length; index++) {
            let currentCharacter = className[index]

            if (bracketDepth === 0) {
                if (
                    currentCharacter === firstSeparatorCharacter &&
                    (isSeparatorSingleCharacter ||
                        className.slice(index, index + separatorLength) === separator)
                ) {
                    modifiers.push(className.slice(modifierStart, index))
                    modifierStart = index + separatorLength
                    continue
                }

                if (currentCharacter === '/') {
                    postfixModifierPosition = index
                    continue
                }
            }

            if (currentCharacter === '[') {
                bracketDepth++
            } else if (currentCharacter === ']') {
                bracketDepth--
            }
        }

        const baseClassNameWithImportantModifier =
            modifiers.length === 0 ? className : className.substring(modifierStart)
        const hasImportantModifier =
            baseClassNameWithImportantModifier.startsWith(IMPORTANT_MODIFIER)
        const baseClassName = hasImportantModifier
            ? baseClassNameWithImportantModifier.substring(1)
            : baseClassNameWithImportantModifier

        const maybePostfixModifierPosition =
            postfixModifierPosition && postfixModifierPosition > modifierStart
                ? postfixModifierPosition - modifierStart
                : undefined

        return {
            modifiers,
            hasImportantModifier,
            baseClassName,
            maybePostfixModifierPosition,
        }
    }

    if (experimentalParseClassName) {
        return (className: string) => experimentalParseClassName({ className, parseClassName })
    }

    return parseClassName
}

/**
 * Sorts modifiers according to following schema:
 * - Predefined modifiers are sorted alphabetically
 * - When an arbitrary variant appears, it must be preserved which modifiers are before and after it
 */
export const sortModifiers = (modifiers: string[]) => {
    if (modifiers.length <= 1) {
        return modifiers
    }

    const sortedModifiers: string[] = []
    let unsortedModifiers: string[] = []

    modifiers.forEach((modifier) => {
        const isArbitraryVariant = modifier[0] === '['

        if (isArbitraryVariant) {
            sortedModifiers.push(...unsortedModifiers.sort(), modifier)
            unsortedModifiers = []
        } else {
            unsortedModifiers.push(modifier)
        }
    })

    sortedModifiers.push(...unsortedModifiers.sort())

    return sortedModifiers
}
