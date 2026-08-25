"""
Bakes a sequence of rendered PIL Images into a short xfade-crossfaded video
clip -- same ffmpeg filter chain as the Chromium-based renderer
(weatherstar/src/renderer.js), just fed pre-rendered PNGs from Pillow
instead of Puppeteer screenshots. streamer.js (unchanged) loops whatever
baked.mp4 this produces, exactly as it already does today.
"""
import asyncio
import os

# Real WS4KP default (confirmed live in shared.min.js: `this.timing =
# {totalScreens:1, baseDelay:9000, delay:1}`) -- matches live_stream.py.
SCREEN_HOLD_SECONDS = 9
XFADE_SECONDS = 1


async def _run_ffmpeg(args):
	proc = await asyncio.create_subprocess_exec(
		'ffmpeg', *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
	)
	_, stderr = await proc.communicate()
	if proc.returncode != 0:
		raise RuntimeError(f'ffmpeg exited {proc.returncode}: {stderr.decode()[-2000:]}')


async def bake_clip(images, tmp_dir, output_path):
	"""images: list of PIL Images (already rendered). Writes each to a temp
	PNG, xfades them together, atomically renames the result to
	output_path -- same atomic-handoff pattern as renderer.js (streamer.js's
	mtime-poll must never see a half-written file)."""
	os.makedirs(tmp_dir, exist_ok=True)
	shot_paths = []
	for i, img in enumerate(images):
		p = os.path.join(tmp_dir, f'screen_{i}.png')
		img.save(p)
		shot_paths.append(p)

	ff_args = []
	for p in shot_paths:
		ff_args += ['-loop', '1', '-t', str(SCREEN_HOLD_SECONDS), '-i', p]

	if len(shot_paths) > 1:
		filter_parts = []
		last_label = '0:v'
		for i in range(1, len(shot_paths)):
			offset = i * SCREEN_HOLD_SECONDS - i * XFADE_SECONDS
			out_label = 'vout' if i == len(shot_paths) - 1 else f'v{i}'
			filter_parts.append(f'[{last_label}][{i}:v]xfade=transition=fade:duration={XFADE_SECONDS}:offset={offset}[{out_label}]')
			last_label = out_label
		total_duration = len(shot_paths) * SCREEN_HOLD_SECONDS - (len(shot_paths) - 1) * XFADE_SECONDS
		new_clip_path = f'{output_path}.new'
		args = [
			'-y', *ff_args,
			'-filter_complex', ';'.join(filter_parts),
			'-map', '[vout]', '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '2500k',
			'-pix_fmt', 'yuv420p', '-r', '30', '-t', str(total_duration), '-f', 'mp4', new_clip_path,
		]
	else:
		new_clip_path = f'{output_path}.new'
		args = [
			'-y', '-loop', '1', '-t', '10', '-i', shot_paths[0],
			'-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '2500k',
			'-pix_fmt', 'yuv420p', '-r', '30', '-f', 'mp4', new_clip_path,
		]

	await _run_ffmpeg(args)

	size = os.path.getsize(new_clip_path)
	if size < 10_000:
		raise RuntimeError(f'baked clip suspiciously small ({size} bytes)')

	os.rename(new_clip_path, output_path)

	for p in shot_paths:
		try:
			os.remove(p)
		except OSError:
			pass

	return size
