import { DefinedError } from 'ajv';
import { AJV_ERROR_KEYWORD_WEIGHT_MAP } from '../constants';

export const filterSingleErrorPerProperty = (errors: DefinedError[]): DefinedError[] => {
  const errorsPerProperty = errors.reduce<Record<string, DefinedError>>((acc, error) => {
    const prop =
      error.instancePath + ((error.params as any)?.additionalProperty ?? (error.params as any)?.missingProperty ?? '');
    const existingError = acc[prop];
    if (!existingError) {
      acc[prop] = error;
      return acc;
    }
    const weight = AJV_ERROR_KEYWORD_WEIGHT_MAP[error.keyword] ?? 0;
    const existingWeight = AJV_ERROR_KEYWORD_WEIGHT_MAP[existingError.keyword] ?? 0;

    if (weight > existingWeight) {
      acc[prop] = error;
    }
    return acc;
  }, {});

  return Object.values(errorsPerProperty);
};
