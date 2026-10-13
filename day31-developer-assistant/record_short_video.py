"""Short narrated demo: real UI crops timed to actual QwenTTS narration."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont

DAY=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DAY.parent/'ChallengeVideos/day31-demo-voiced.mp4')
    args=parser.parse_args()
    ffmpeg=os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg')
    ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe: raise RuntimeError('ffmpeg and ffprobe required')
    narration=json.loads((DAY/'evidence/narration-generation.json').read_text(encoding='utf-8'))
    demo=json.loads((DAY/'evidence/short-browser-demo.json').read_text(encoding='utf-8'))['turns'][0]
    if demo['project']['branch']!='main': raise ValueError('Narration says main; regenerate it for actual branch')
    frames=DAY/'video-frames/short'
    frames.mkdir(parents=True,exist_ok=True)
    args.output.parent.mkdir(exist_ok=True)
    fontpath=os.environ.get('DAY31_VIDEO_FONT',str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'))
    titlefont=ImageFont.truetype(fontpath,47)
    bodyfont=ImageFont.truetype(fontpath,30)
    smallfont=ImageFont.truetype(fontpath,21)
    parts=[]
    manifest=[]
    for i,scene in enumerate(narration['scenes']):
        frame=Image.new('RGB',(1920,1080),'#0c1322')
        draw=ImageDraw.Draw(frame)
        draw.text((70,40),scene['title'],font=titlefont,fill='#edf3ff')
        if scene['image']=='intro':
            draw.text((90,200),'Ассистент отвечает о конкретном проекте',font=titlefont,fill='#78dfc4')
            for j,line in enumerate(['README + docs → поиск по документации', 'MCP → текущая git-ветка', '/help → ответ о структуре проекта']):
                draw.rounded_rectangle((90,340+j*145,1830,445+j*145),radius=18,fill='#142238')
                draw.text((125,370+j*145),line,font=titlefont,fill='#edf3ff')
        else:
            focus={'source':'short-source-focus.png','answer':'short-answer-focus.png','mcp':'short-mcp-focus.png'}
            source=DAY/'evidence'/focus.get(scene['id'],scene['image'])
            picture=Image.open(source).convert('RGB')
            if scene['id']=='source':
                # The native details panel is much wider than its text. Remove
                # empty right-hand space so the real fragment can be read.
                picture=picture.crop((0,0,min(1150,picture.width),picture.height))
            # Fit authentic screenshot/crop, never reconstruct model responses.
            max_width=1680 if scene['id']!='mcp' else 1200
            ratio=min(max_width/picture.width,820/picture.height,1.55)
            picture=picture.resize((round(picture.width*ratio),round(picture.height*ratio)))
            frame.paste(picture,((1920-picture.width)//2,135+(820-picture.height)//2))
        draw.text((70,1008),'Реальные кадры браузера · ожидание ответа сокращено · озвучка QwenTTS Voice Design',font=smallfont,fill='#b3c6df')
        image_path=frames/f'{i:02d}-{scene["id"]}.png'
        frame.save(image_path)
        duration=float(subprocess.check_output([ffprobe,'-v','error','-show_entries','format=duration','-of','csv=p=0',scene['audio']],text=True))+.35
        part=frames/f'{i:02d}.mp4'
        subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-loop','1','-i',str(image_path),'-i',scene['audio'],
            '-t',str(duration),'-vf','fps=25','-af','apad,alimiter=limit=0.95','-c:v','libx264','-preset','fast','-crf','20',
            '-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-b:a','160k',str(part)],check=True)
        parts.append(part)
        manifest.append({'id':scene['id'],'duration_sec':duration,'frame':str(image_path),'audio':scene['audio']})
    concat=frames/'concat.txt'
    concat.write_text(''.join(f"file '{p.as_posix()}'\n" for p in parts),encoding='utf-8')
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),
        '-c','copy','-movflags','+faststart',str(args.output)],check=True)
    (DAY/'evidence/short-video-scenes.json').write_text(json.dumps({'video':str(args.output.resolve()),'model':demo['model'],'scenes':manifest},ensure_ascii=False,indent=2),encoding='utf-8')
    print(args.output.resolve())


if __name__=='__main__':main()
