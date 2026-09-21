// Register the service worker so the site (and config builder) works offline.
if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
  navigator.serviceWorker.register('sw.js').catch(function () { /* offline support is optional */ });
}
