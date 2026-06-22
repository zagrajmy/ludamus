/// <reference types="vite/client" />

if (import.meta.hot) {
  import.meta.hot.on("django-template-reload", () => {
    globalThis.location.reload();
  });
}
