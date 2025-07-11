type Config = {
  plugins: { "react-refresh": { rules: Record<string, any> } };
  rules: Record<string, any>;
};

declare const _default: {
  rules: Record<string, any>;
  configs: {
    recommended: Config;
    vite: Config;
  };
};

export = _default;
