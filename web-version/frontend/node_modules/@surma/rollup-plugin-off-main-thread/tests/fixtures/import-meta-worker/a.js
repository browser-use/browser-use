let worker;

if (self.document) {
  worker = new Worker(import.meta.url);
}
if (self.postMessage) {
  setTimeout(() => {
    postMessage("a");
  }, 500);
}

export { worker };
