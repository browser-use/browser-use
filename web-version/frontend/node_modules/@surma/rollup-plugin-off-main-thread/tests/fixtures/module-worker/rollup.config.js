module.exports = (config, outputOptions, omt) => {
  outputOptions.format = "esm";
  config.plugins = [omt()];
};
