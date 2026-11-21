// scripts/ui_development_monitor_smoke.mjs

import { createServer } from 'http';
import { readFileSync } from 'fs';

const server = createServer((req, res) => {
  if (req.url === '/api/monitor') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'running', jobs: 10, events: 50, workers: 3 }));
  } else if (req.url === '/api/events') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify([{ id: 1, type: 'error', message: 'Test error' }]));
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
  }
});

server.listen(3000, () => {
  console.log('Server running at http://localhost:3000/');
});
