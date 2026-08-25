'use strict';

// Cheap static "LOADING" placeholder frame, generated with a single ffmpeg
// call (lavfi color source + drawtext) -- same role as the Python renderer's
// loading_stream.py baseline for on_demand channels, simplified (no logo
// overlay/animation states -- see Scorecastarr's writeStartingClip for the
// fancier version this deliberately skips for a first pass).

const { execFileSync } = require('child_process');

function writeLoadingFrame(destPath, label, width, height) {
  const safeLabel = String(label || '').replace(/[^A-Za-z0-9 .,'-]/g, '').slice(0, 60).toUpperCase();
  execFileSync('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-f', 'lavfi', '-i', `color=c=0x0b1d33:size=${width}x${height}:rate=1`,
    '-vf', `drawtext=text='${safeLabel}':fontcolor=white:fontsize=36:x=(w-text_w)/2:y=(h-text_h)/2-20,` +
           `drawtext=text='LOADING...':fontcolor=0x00d9ff:fontsize=24:x=(w-text_w)/2:y=(h-text_h)/2+30,` +
           'format=yuv420p',
    '-frames:v', '1', '-q:v', '3', destPath,
  ], { stdio: 'pipe' });
}

module.exports = { writeLoadingFrame };
