import { DefinedError, ErrorObject } from 'ajv';
import type { JSONSchema6 } from 'json-schema';
import { ValidationError } from './types/ValidationError';
import { filterSingleErrorPerProperty } from './lib/filter';
import { getSuggestion } from './lib/suggestions';
import { cleanAjvMessage, getLastSegment, pointerToDotNotation, safeJsonPointer } from './lib/utils';

export interface BetterAjvErrorsOptions {
  errors: ErrorObject[] | null | undefined;
  data: any;
  schema: JSONSchema6;
  basePath?: string;
}

export const betterAjvErrors = ({
  errors,
  data,
  schema,
  basePath = '{base}',
}: BetterAjvErrorsOptions): ValidationError[] => {
  if (!Array.isArray(errors) || errors.length === 0) {
    return [];
  }

  const definedErrors = filterSingleErrorPerProperty(errors as DefinedError[]);

  return definedErrors.map((error) => {
    const path = pointerToDotNotation(basePath + error.instancePath);
    const prop = getLastSegment(error.instancePath);
    const defaultContext = {
      errorType: error.keyword,
    };
    const defaultMessage = `${prop ? `property '${prop}'` : path} ${cleanAjvMessage(error.message as string)}`;

    let validationError: ValidationError;

    switch (error.keyword) {
      case 'additionalProperties': {
        const additionalProp = error.params.additionalProperty;
        const suggestionPointer = error.schemaPath.replace('#', '').replace('/additionalProperties', '');
        const { properties } = safeJsonPointer({
          object: schema,
          pnter: suggestionPointer,
          fallback: { properties: {} },
        });
        validationError = {
          message: `'${additionalProp}' property is not expected to be here`,
          suggestion: getSuggestion({
            value: additionalProp,
            suggestions: Object.keys(properties ?? {}),
            format: (suggestion) => `Did you mean property '${suggestion}'?`,
          }),
          path,
          context: defaultContext,
        };
        break;
      }
      case 'enum': {
        const suggestions = error.params.allowedValues.map((value) => value.toString());
        const prop = getLastSegment(error.instancePath);
        const value = safeJsonPointer({ object: data, pnter: error.instancePath, fallback: '' });
        validationError = {
          message: `'${prop}' property must be equal to one of the allowed values`,
          suggestion: getSuggestion({
            value,
            suggestions,
          }),
          path,
          context: {
            ...defaultContext,
            allowedValues: error.params.allowedValues,
          },
        };
        break;
      }
      case 'type': {
        const prop = getLastSegment(error.instancePath);
        const type = error.params.type;
        validationError = {
          message: `'${prop}' property type must be ${type}`,
          path,
          context: defaultContext,
        };
        break;
      }
      case 'required': {
        validationError = {
          message: `${path} must have required property '${error.params.missingProperty}'`,
          path,
          context: defaultContext,
        };
        break;
      }
      case 'const': {
        return {
          message: `'${prop}' property must be equal to the allowed value`,
          path,
          context: {
            ...defaultContext,
            allowedValue: error.params.allowedValue,
          },
        };
      }

      default:
        return { message: defaultMessage, path, context: defaultContext };
    }

    // Remove empty properties
    const errorEntries = Object.entries(validationError);
    for (const [key, value] of errorEntries as [keyof ValidationError, unknown][]) {
      if (value === null || value === undefined || value === '') {
        delete validationError[key];
      }
    }

    return validationError;
  });
};

export { ValidationError };
