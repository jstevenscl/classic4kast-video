'use strict';

const config = require('./config');
const cpc = require('./control_plane_client');
const manager = require('./manager');
const server = require('./server');
const { closeWarmBrowser } = require('./browser');

async function main() {
  console.log('[index] Classic4Kast Video+ web-channel renderer starting');
  if (!cpc.isConfigured()) {
    console.warn('[index] CONTROL_PLANE_URL/AGENT_TOKEN not fully configured -- no channels will poll until they are');
  }
  server.start();
  manager.startPrewarmLoop();
  manager.startReaperLoop();
  manager.startStreamKeyPoll();

  process.on('SIGTERM', async () => {
    console.log('[index] shutting down');
    await manager.shutdown();
    await closeWarmBrowser();
    process.exit(0);
  });
}

main().catch((err) => { console.error(`[index] fatal: ${err.message}`); process.exit(1); });

module.exports = { config };
