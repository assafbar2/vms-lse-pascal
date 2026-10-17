// Cross-origin isolation for a static host.
//
// SharedArrayBuffer (which lets a running Pascal program wait for the
// keyboard) needs the page to be cross-origin isolated, which needs the
// COOP and COEP response headers. GitHub Pages cannot send custom headers,
// so this service worker adds them to every same-origin response. The page
// registers it and reloads once (see main.js).

// A reload revalidates cached files, and the answer can be 304 Not Modified.
// A response with one of these statuses must have no body: Safari rejects it
// otherwise, and the file fails to load.
const NO_BODY = new Set([204, 205, 304]);

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.cache === "only-if-cached" && request.mode !== "same-origin") return;
  if (new URL(request.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(request).then((response) => {
      if (response.status === 0) return response;
      const headers = new Headers(response.headers);
      headers.set("Cross-Origin-Opener-Policy", "same-origin");
      headers.set("Cross-Origin-Embedder-Policy", "require-corp");
      headers.set("Cross-Origin-Resource-Policy", "same-origin");
      return new Response(NO_BODY.has(response.status) ? null : response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    }),
  );
});
