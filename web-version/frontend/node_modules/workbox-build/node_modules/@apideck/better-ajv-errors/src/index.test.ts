import Ajv from 'ajv';
import { JSONSchema6 } from 'json-schema';
import { betterAjvErrors } from './index';

describe('betterAjvErrors', () => {
  let ajv: Ajv;
  let schema: JSONSchema6;
  let data: Record<string, unknown>;

  beforeEach(() => {
    ajv = new Ajv({ allErrors: true });
    schema = {
      type: 'object',
      required: ['str'],
      properties: {
        str: {
          type: 'string',
        },
        enum: {
          type: 'string',
          enum: ['one', 'two'],
        },
        bounds: {
          type: 'number',
          minimum: 2,
          maximum: 4,
        },
        nested: {
          type: 'object',
          required: ['deepReq'],
          properties: {
            deepReq: {
              type: 'boolean',
            },
            deep: {
              type: 'string',
            },
          },
          additionalProperties: false,
        },
      },
      additionalProperties: false,
    };
  });

  describe('additionalProperties', () => {
    it('should handle additionalProperties=false', () => {
      data = {
        str: 'str',
        foo: 'bar',
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'additionalProperties',
          },
          message: "'foo' property is not expected to be here",
          path: '{base}',
        },
      ]);
    });

    it('should handle additionalProperties=true', () => {
      data = {
        str: 'str',
        foo: 'bar',
      };
      schema.additionalProperties = true;
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([]);
    });

    it('should give suggestions when relevant', () => {
      data = {
        str: 'str',
        bonds: 'bar',
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'additionalProperties',
          },
          message: "'bonds' property is not expected to be here",
          path: '{base}',
          suggestion: "Did you mean property 'bounds'?",
        },
      ]);
    });

    it('should handle object schemas without properties', () => {
      data = {
        empty: { foo: 1 },
      };
      schema = {
        type: 'object',
        properties: {
          empty: {
            type: 'object',
            additionalProperties: false,
          },
        },
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'additionalProperties',
          },
          message: "'foo' property is not expected to be here",
          path: '{base}.empty',
        },
      ]);
    });
  });

  describe('required', () => {
    it('should handle required properties', () => {
      data = {
        nested: {},
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'required',
          },
          message: "{base} must have required property 'str'",
          path: '{base}',
        },
        {
          context: {
            errorType: 'required',
          },
          message: "{base}.nested must have required property 'deepReq'",
          path: '{base}.nested',
        },
      ]);
    });

    it('should handle multiple required properties', () => {
      schema = {
        type: 'object',
        required: ['req1', 'req2'],
        properties: {
          req1: {
            type: 'string',
          },
          req2: {
            type: 'string',
          },
        },
      };
      data = {};
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'required',
          },
          message: "{base} must have required property 'req1'",
          path: '{base}',
        },
        {
          context: {
            errorType: 'required',
          },
          message: "{base} must have required property 'req2'",
          path: '{base}',
        },
      ]);
    });
  });

  describe('type', () => {
    it('should handle type errors', () => {
      data = {
        str: 123,
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'type',
          },
          message: "'str' property type must be string",
          path: '{base}.str',
        },
      ]);
    });
  });

  describe('minimum/maximum', () => {
    it('should handle minimum/maximum errors', () => {
      data = {
        str: 'str',
        bounds: 123,
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'maximum',
          },
          message: "property 'bounds' must be <= 4",
          path: '{base}.bounds',
        },
      ]);
    });
  });

  describe('enum', () => {
    it('should handle enum errors', () => {
      data = {
        str: 'str',
        enum: 'zzzz',
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'enum',
            allowedValues: ['one', 'two'],
          },
          message: "'enum' property must be equal to one of the allowed values",
          path: '{base}.enum',
        },
      ]);
    });

    it('should provide suggestions when relevant', () => {
      data = {
        str: 'str',
        enum: 'pne',
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            errorType: 'enum',
            allowedValues: ['one', 'two'],
          },
          message: "'enum' property must be equal to one of the allowed values",
          path: '{base}.enum',
          suggestion: "Did you mean 'one'?",
        },
      ]);
    });

    it('should not crash on null value', () => {
      data = {
        type: null,
      };
      schema = {
        type: 'object',
        properties: {
          type: {
            type: 'string',
            enum: ['primary', 'secondary'],
          },
        },
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            allowedValues: ['primary', 'secondary'],
            errorType: 'enum',
          },
          message: "'type' property must be equal to one of the allowed values",
          path: '{base}.type',
        },
      ]);
    });
  });

  it('should handle array paths', () => {
    data = {
      custom: [{ foo: 'bar' }, { aaa: 'zzz' }],
    };
    schema = {
      type: 'object',
      properties: {
        custom: {
          type: 'array',
          items: {
            type: 'object',
            additionalProperties: false,
            properties: {
              id: {
                type: 'string',
              },
              title: {
                type: 'string',
              },
            },
          },
        },
      },
    };
    ajv.validate(schema, data);
    const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
    expect(errors).toEqual([
      {
        context: {
          errorType: 'additionalProperties',
        },
        message: "'foo' property is not expected to be here",
        path: '{base}.custom.0',
      },
      {
        context: {
          errorType: 'additionalProperties',
        },
        message: "'aaa' property is not expected to be here",
        path: '{base}.custom.1',
      },
    ]);
  });

  it('should handle file $refs', () => {
    data = {
      child: [{ foo: 'bar' }, { aaa: 'zzz' }],
    };
    schema = {
      $id: 'http://example.com/schemas/Main.json',
      type: 'object',
      properties: {
        child: {
          type: 'array',
          items: {
            $ref: './Child.json',
          },
        },
      },
    };
    ajv.addSchema({
      $id: 'http://example.com/schemas/Child.json',
      additionalProperties: false,
      type: 'object',
      properties: {
        id: {
          type: 'string',
        },
      },
    });
    ajv.validate(schema, data);
    const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
    expect(errors).toEqual([
      {
        context: {
          errorType: 'additionalProperties',
        },
        message: "'foo' property is not expected to be here",
        path: '{base}.child.0',
      },
      {
        context: {
          errorType: 'additionalProperties',
        },
        message: "'aaa' property is not expected to be here",
        path: '{base}.child.1',
      },
    ]);
  });

  it('should handle number enums', () => {
    data = {
      isLive: 2,
    };
    schema = {
      type: 'object',
      properties: {
        isLive: {
          type: 'integer',
          enum: [0, 1],
        },
      },
    };
    ajv.validate(schema, data);
    const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
    expect(errors).toEqual([
      {
        context: {
          allowedValues: [0, 1],
          errorType: 'enum',
        },
        message: "'isLive' property must be equal to one of the allowed values",
        path: '{base}.isLive',
      },
    ]);
  });

  describe('const', () => {
    it('should handle const errors', () => {
      data = {
        const: 2,
      };
      schema = {
        type: 'object',
        properties: {
          const: {
            type: 'integer',
            const: 42,
          },
        },
      };
      ajv.validate(schema, data);
      const errors = betterAjvErrors({ data, schema, errors: ajv.errors });
      expect(errors).toEqual([
        {
          context: {
            allowedValue: 42,
            errorType: 'const',
          },
          message: "'const' property must be equal to the allowed value",
          path: '{base}.const',
        },
      ]);
    });
  });
});
