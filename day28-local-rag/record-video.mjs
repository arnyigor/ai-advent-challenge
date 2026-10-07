// Montage of real browser screenshots captured through cua_repl.
// Does not operate the browser or fabricate model replies.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const frames = path.join(root, 'video-frames');
const scenes = JSON.parse(readFileSync(path.join(frames, 'manifest.json'), 'utf8'));
const ffmpeg = process.env.FFMPEG_PATH || 'ffmpeg';
const out = path.resolve(root, '..', 'ChallengeVideos', 'day28-demo.mp4');
function wrap(text, width) {
  return text.split('\n').map(line => {
    let result = [], current = '';
    for (const word of line.split(' ')) {
      if (current && current.length + word.length + 1 > width) {result.push(current); current = '';}
      current += (current ? ' ' : '') + word;
    }
    result.push(current); return result.join('\n');
  }).join('\n\n');
}
let elapsed = 0; const timeline = [];
for (let i = 0; i < scenes.length; i++) {
  const s = scenes[i];
  if (!Number.isFinite(s.seconds) || s.seconds < 1 || s.seconds > 30) throw Error('Invalid duration');
  writeFileSync(path.join(frames, `title-${i}.txt`), wrap(s.title, 29));
  writeFileSync(path.join(frames, `caption-${i}.txt`), wrap(s.caption, 34));
  const filter = `scale=1280:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:0:(oh-ih)/2:color=0x0c1220,drawbox=x=1280:y=0:w=640:h=1080:color=0x172335:t=fill,drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='AI ADVENT / DAY 28':fontcolor=0xa4d7aa:fontsize=24:x=1320:y=70,drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':textfile=title-${i}.txt:fontcolor=white:fontsize=32:line_spacing=12:x=1320:y=140,drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':textfile=caption-${i}.txt:fontcolor=0xc8d5e7:fontsize=27:line_spacing=12:x=1320:y=350,drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='${i + 1} / ${scenes.length}':fontcolor=0xa4d7aa:fontsize=26:x=1320:y=990`;
  console.log(`Scene ${i + 1}/${scenes.length}: ${s.title}`);
  execFileSync(ffmpeg, ['-y','-loglevel','error','-loop','1','-i',s.file,'-vf',filter,'-t',String(s.seconds),'-r','25','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',`segment-${i}.mp4`], {cwd:frames, stdio:'inherit'});
  timeline.push({at:elapsed, seconds:s.seconds, title:s.title}); elapsed += s.seconds;
}
writeFileSync(path.join(frames, 'segments.txt'), scenes.map((_, i) => `file 'segment-${i}.mp4'`).join('\n'));
mkdirSync(path.dirname(out), {recursive:true});
execFileSync(ffmpeg, ['-y','-loglevel','error','-f','concat','-safe','0','-i','segments.txt','-c','copy','-movflags','+faststart',out], {cwd:frames,stdio:'inherit'});
writeFileSync(path.join(frames,'timeline.json'),JSON.stringify({seconds:elapsed,timeline},null,2));
console.log(`${out} (${elapsed}s)`);
