[![npm (scoped)](https://img.shields.io/npm/v/@apideck/better-ajv-errors?color=brightgreen)](https://npmjs.com/@apideck/better-ajv-errors) [![npm](https://img.shields.io/npm/dm/@apideck/better-ajv-errors)](https://npmjs.com/@apideck/better-ajv-errors) [![GitHub Workflow Status](https://img.shields.io/github/workflow/status/apideck-libraries/better-ajv-errors/CI)](https://github.com/apideck-libraries/better-ajv-errors/actions/workflows/main.yml?query=branch%3Amain++)

# @apideck/better-ajv-errors 👮‍♀️

> Human-friendly JSON Schema validation for APIs


- Readable and helpful [ajv](https://github.com/ajv-validator/ajv) errors
- API-friendly format
- Suggestions for spelling mistakes
- Minimal footprint: 1.56 kB (gzip + minified)

![better-ajv-errors output Example](https://user-images.githubusercontent.com/8850410/118274790-e0529e80-b4c5-11eb-8188-9097c8064c61.png)

## Install

```bash
$ yarn add @apideck/better-ajv-errors
```

or

```bash
$ npm i @apideck/better-ajv-errors
```

Also make sure that you've installed [ajv](https://www.npmjs.com/package/ajv) at version 8 or higher.

## Usage

After validating some data with ajv, pass the errors to `betterAjvErrors`

```ts
import Ajv from 'ajv';
import { betterAjvErrors } from '@apideck/better-ajv-errors';

// Without allErrors: true, ajv will only return the first error
const ajv = new Ajv({ allErrors: true });

const valid = ajv.validate(schema, data);

if (!valid) {
  const betterErrors = betterAjvErrors({ schema, data, errors: ajv.errors });
}
```

## API

### betterAjvErrors

Function that formats ajv validation errors in a human-friendly format.

#### Parameters

- `options: BetterAjvErrorsOptions`
  - `errors: ErrorObject[] | null | undefined` Your ajv errors, you will find these in the `errors` property of your ajv instance (`ErrorObject` is a type from the ajv package).
  - `data: Object` The data you passed to ajv to be validated.
  - `schema: JSONSchema` The schema you passed to ajv to validate against.
  - `basePath?: string` An optional base path to prefix paths returned by `betterAjvErrors`. For example, in APIs, it could be useful to use `'{requestBody}'` or `'{queryParemeters}'` as a basePath. This will make it clear to users where exactly the error occurred.

#### Return Value

- `ValidationError[]` Array of formatted errors (properties of `ValidationError` below)
  - `message: string` Formatted error message
  - `suggestion?: string` Optional suggestion based on provided data and schema
  - `path: string` Object path where the error occurred (example: `.foo.bar.0.quz`)
  - `context: { errorType: DefinedError['keyword']; [additionalContext: string]: unknown }` `errorType` is `error.keyword` proxied from `ajv`. `errorType` can be used as a key for i18n if needed. There might be additional properties on context, based on the type of error.

## Related

- [atlassian/better-ajv-errors](https://github.com/atlassian/better-ajv-errors) was the inspiration for this library. Atlassian's library is more focused on CLI errors, this library is focused on developer-friendly API error messages.
