self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});

// Handle incoming push notifications
self.addEventListener('push', (event) => {
  let data = { title: 'CNAZ Safety', body: 'New message', url: '/chat' };

  try {
    if (event.data) {
      data = event.data.json();
    }
  } catch (e) {
    console.log('Push data error', e);
  }

  const options = {
    body: data.body || 'New chat message',
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    data: {
      url: data.url || '/chat'
    },
    vibrate: [100, 50, 100]
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'CNAZ Safety', options)
  );
});

// When user taps the notification
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const url = event.notification.data.url || '/chat';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
