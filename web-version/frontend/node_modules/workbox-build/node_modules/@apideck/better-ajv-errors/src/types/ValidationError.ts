import { DefinedError } from 'ajv';

export interface ValidationError {
  message: string;
  path: string;
  suggestion?: string;
  context: {
    errorType: DefinedError['keyword'];
    [additionalContext: string]: unknown;
  };
}
