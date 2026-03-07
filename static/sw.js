self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("student-app-v1").then((cache) => {
      return cache.addAll([
        "/",
        "/student/login",
        "/admin-id-login"
      ]);
    })
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});
