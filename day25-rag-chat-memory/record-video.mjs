// Edited walkthrough from genuine Browser screenshots; model waits omitted.
// Usage: node record-video.mjs [manifest.json]
import {spawnSync} from 'node:child_process';
import {readFileSync,writeFileSync,existsSync,mkdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const day=path.dirname(fileURLToPath(import.meta.url));
const manifest=path.resolve(process.argv[2]||path.join(day,'video-frames','final','manifest.json'));
const shots=JSON.parse(readFileSync(manifest,'utf8'));
if(!Array.isArray(shots)||!shots.length)throw Error('Capture real UI screenshots before encoding');
for(const s of shots)if(!existsSync(s.file)||!Number.isFinite(s.seconds)||s.seconds<=0)throw Error('Invalid screenshot or duration');
const quote=s=>s.replaceAll('\\','/').replaceAll("'","'\\''");
const list=shots.map(s=>`file '${quote(s.file)}'\nduration ${s.seconds}`).join('\n')+`\nfile '${quote(shots.at(-1).file)}'\n`;
const input=path.join(path.dirname(manifest),'frames.txt');writeFileSync(input,list);
const output=path.resolve(day,'..','ChallengeVideos','day25-demo.mp4');mkdirSync(path.dirname(output),{recursive:true});
const seconds=shots.reduce((sum,s)=>sum+s.seconds,0);
const stamp=t=>{const ms=Math.round(t*1000);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};
let elapsed=0;const captions=[];
for(const s of shots){if(s.caption)captions.push(`${captions.length+1}\n${stamp(elapsed)} --> ${stamp(elapsed+s.seconds)}\n${s.caption}\n`);elapsed+=s.seconds;}
if(captions.length)writeFileSync(path.join(path.dirname(manifest),'captions.srt'),captions.join('\n'),'utf8');
const subtitleFilter=captions.length?",subtitles=captions.srt:force_style='FontName=Segoe UI,FontSize=18,Outline=2,MarginV=12'":'';
const result=spawnSync(process.env.FFMPEG_PATH||'ffmpeg',[
 '-y','-loglevel','error','-f','concat','-safe','0','-i',input,
 '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000',
 '-vf','scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=25'+subtitleFilter,
 '-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-crf','19','-c:a','aac','-t',String(seconds),'-movflags','+faststart',output
],{stdio:'inherit',windowsHide:true,cwd:path.dirname(manifest)});
if(result.error)throw result.error;if(result.status!==0)throw Error('ffmpeg failed');
console.log(JSON.stringify({output,scenes:shots.length,seconds}));
