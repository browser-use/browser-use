const MARKER = "my-special-import";
module.exports = (config, outputOptions, omt) => {
  config.plugins = [
    omt(),
    {
      resolveId(id) {
        if (id !== MARKER) {
          return;
        }
        return id;
      },
      load(id) {
        if (id !== MARKER) {
          return;
        }
        const referenceId = this.emitFile({
          type: "asset",
          name: "my-asset.bin",
          source: "assetcontent"
        });
        return `export default import.meta.ROLLUP_FILE_URL_${referenceId}`;
      }
    }
  ];
};
