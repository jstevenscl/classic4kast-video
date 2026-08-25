"""
Temporary "please wait" HLS loop the on-demand server starts immediately on a
cold request, writing to the SAME output path live_stream.run() will take
over once real data is ready. Must never run concurrently with the real
ffmpeg process against that path -- the on-demand server always stops this
one (stop()) before live_stream.run() starts its own (see live_stream.run's
on_ready callback).

Unlike live_stream's per-frame pipe (clock/ticker need per-second redraws),
this screen is fully static -- a single looped image input is simpler and
cheaper, appropriate for a screen nobody watches for more than a few real
seconds.
"""
import logging
import os
import subprocess
import tempfile
import time

from renderer.screens import loading

log = logging.getLogger(__name__)


def start(hls_dir, city_name=None):
	os.makedirs(hls_dir, exist_ok=True)
	img = loading.render(city_name)
	fd, png_path = tempfile.mkstemp(suffix='.png', prefix='loading_')
	os.close(fd)
	img.save(png_path)

	args = [
		'ffmpeg', '-y', '-loglevel', 'warning',
		# -re: without it ffmpeg has nothing pacing the input (a looped still
		# image has no real "frame rate" of its own to read at) and just
		# encodes flat-out as fast as the CPU allows -- confirmed live, a
		# single one of these pegged ~4 full cores (396% CPU) instead of the
		# near-zero cost a 2fps stillimage loop should actually have. Same
		# fix live_stream.py's own ffmpeg already applies to its audio input.
		'-re', '-loop', '1', '-framerate', '2', '-i', png_path,
		# Silent AAC track, same codec/rate/channel-layout as live_stream.py's
		# real audio output -- without this the loading loop was video-only,
		# so the loading->real handoff on the SAME output path silently
		# changed the stream's track layout (0 audio tracks -> 1 AAC track)
		# mid-session. Confirmed live: Dispatcharr's own MSE player mis-
		# negotiated that transition and started requesting 'audio/mp4;
		# codecs=ac-3' -- unsupported by browser MSE, breaking playback --
		# even though the actual real-content stream (once already playing
		# from a cold start) worked fine with the same Proxy stream profile.
		# Keeping the track layout identical throughout removes the
		# mid-stream renegotiation entirely.
		'-re', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
		'-map', '0:v', '-map', '1:a',
		'-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-b:v', '800k',
		'-pix_fmt', 'yuv420p', '-g', '2',
		'-c:a', 'aac', '-b:a', '128k', '-ac', '2',
		# Kept in sync with live_stream.py's own hls_time/hls_list_size (see
		# that file's comment) -- a viewer can cold-start into THIS loading
		# loop before live_stream.py's real ffmpeg takes over, so a
		# mismatched window/segment size here would mean the handoff itself
		# changes how much cushion the player has.
		'-f', 'hls', '-hls_time', '6', '-hls_list_size', '10',
		# initial_discontinuity: every ffmpeg process here is a brand-new
		# encoder timeline starting at its own PTS 0 -- but each cold start
		# writes to the SAME stream.m3u8 path a still-attached player may
		# have been watching from a much later media sequence number.
		# Without a discontinuity marker on the first segment, hls.js sees
		# the sequence/timestamp jump backward and can stall entirely
		# ("stuck buffering", confirmed live) instead of just resyncing.
		# pat_pmt_at_frames/resend_headers: same combination real
		# Dispatcharr stream profiles use for exactly this reason (see
		# their own "bulletproof for live" profiles) -- resends PAT/PMT so
		# a player can resync from any segment, not just the very first.
		'-hls_flags', 'delete_segments+omit_endlist+independent_segments',
		# start_number: see live_stream.py's identical fix/comment (same
		# file, 2026-08-23) -- a timestamp-based number here too, so a
		# viewer landing on THIS loading loop can never be served a stale
		# CDN-cached segment left over under a reused low number either.
		'-start_number', str(int(time.time())),
		'-mpegts_flags', 'initial_discontinuity+pat_pmt_at_frames+resend_headers',
		os.path.join(hls_dir, 'stream.m3u8'),
	]
	proc = subprocess.Popen(args)
	return proc, png_path


def stop(proc, png_path):
	try:
		proc.terminate()
		proc.wait(timeout=5)
	except Exception:  # noqa: BLE001 -- best-effort, the real ffmpeg is about to overwrite the same path regardless
		proc.kill()
	finally:
		try:
			os.remove(png_path)
		except OSError:
			pass
