import { DefinedError } from 'ajv';

export const AJV_ERROR_KEYWORD_WEIGHT_MAP: Partial<Record<DefinedError['keyword'], number>> = {
  enum: 1,
  type: 0,
};

export const QUOTES_REGEX = /"/g;
export const NOT_REGEX = /NOT/g;
export const SLASH_REGEX = /\//g;
