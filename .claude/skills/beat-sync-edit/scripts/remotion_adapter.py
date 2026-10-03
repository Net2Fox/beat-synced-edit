"""Optional, editable local React composition for deterministic motion graphics.

The default Python compositor remains independent of Node. This adapter exports
source and renders only with locally installed Remotion packages. No generation
service, upload, or API key is involved.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess

from graphics_layers import validate_graphics, _number
from project_workspace import read_json, write_json
from render_qa import file_hash

REMOTION_VERSION = "4.0.532"

ENTRY = '''import React,{useRef,useLayoutEffect} from 'react';
import {AbsoluteFill,Composition,registerRoot,useCurrentFrame,delayRender,continueRender,cancelRender} from 'remotion';
import spec from './composition.json';
const FitText=({text,size,width,height})=>{
  const line=useRef(null);
  useLayoutEffect(()=>{
    const handle=delayRender('Fit composition text');
    let active=true;
    const measure=document.createElement('div');
    Object.assign(measure.style,{position:'fixed',left:'-10000px',top:0,visibility:'hidden',width:`${width}px`,height:'auto',fontSize:`${size}px`,lineHeight:'1.2',fontFamily:spec.fontFamily,fontWeight:'700',overflowWrap:'anywhere',whiteSpace:'pre-wrap'});
    measure.textContent=text;document.body.appendChild(measure);
    void measure.offsetHeight;
    document.fonts.ready.then(()=>{
      if(!active)return;
      let pixels=Math.floor(size);
      while(pixels>1&&(measure.scrollHeight>height||measure.scrollWidth>width)){
        pixels--;measure.style.fontSize=`${pixels}px`;
      }
      if(measure.scrollHeight>height||measure.scrollWidth>width){cancelRender(new Error('Text cannot fit composition rectangle'));return;}
      line.current.style.fontSize=`${pixels}px`;
      measure.remove();continueRender(handle);
    }).catch(cancelRender);
    return ()=>{active=false;measure.remove();continueRender(handle);};
  },[text,size,width,height]);
  return <div ref={line} style={{width:'100%',lineHeight:1.2,overflowWrap:'anywhere',whiteSpace:'pre-wrap'}}>{text}</div>;
};
const Motion=()=>{
  const f=useCurrentFrame();
  return <AbsoluteFill style={{background:spec.background,fontFamily:spec.fontFamily,color:spec.style.foreground}}>
    {spec.style.fontUrl ? <style>{`@font-face{font-family:ProjectFont;src:url(${spec.style.fontUrl})}`}</style> : null}
    {spec.graphics.map(g=>{
      if(f<g.start_frame||f>=g.end_frame)return null;
      const n=g.end_frame-g.start_frame,p=(f-g.start_frame)/Math.max(1,n-1);
      const d=Math.min(g.fade_frames??6,Math.floor(n/2));
      const a=d?Math.min(1,(f-g.start_frame+1)/d,(g.end_frame-f)/d):1;
      const rect=g.rect??[.08,.12,.78,.25];
      const anim=g.animation??spec.style.animation??'fade';
      const t=anim==='slide'?`translateY(${(1-a)*24}px)`:anim==='pop'?`scale(${.85+.15*a})`:'none';
      const value=(g.value_from??0)+((g.value_to??100)-(g.value_from??0))*p;
      const prefix=g.text??'';
      const content=g.kind==='counter'?(prefix.includes('{value}')?prefix.replaceAll('{value}',`${Math.round(value)}`):`${prefix}${Math.round(value)}`):prefix;
      return <div key={g.id} style={{position:'absolute',left:`${rect[0]*100}%`,top:`${rect[1]*100}%`,width:`${rect[2]*100}%`,height:`${rect[3]*100}%`,boxSizing:'border-box',display:'flex',alignItems:'center',justifyContent:'center',whiteSpace:'pre-wrap',textAlign:'center',overflow:'hidden',padding:g.kind==='bar'?0:10,background:g.background??spec.style.background,color:g.color??spec.style.foreground,fontSize:g.font_size??spec.style.font_size??58,fontWeight:700,opacity:(g.opacity??1)*(anim==='none'?1:a),transform:t,borderRadius:12}}>
        {g.kind==='bar'?<div style={{position:'absolute',left:0,top:0,bottom:0,width:`${Math.max(0,Math.min(100,value))}%`,background:g.accent??spec.style.accent}}/>:g.kind==='rectangle'?null:<FitText text={content} size={g.font_size??spec.style.font_size??58} width={Math.max(1,rect[2]*spec.width-20)} height={Math.max(1,rect[3]*spec.height-20)}/>}
      </div>;
    })}
  </AbsoluteFill>;
};
const Root=()=> <Composition id="BeatSyncMotion" component={Motion} width={spec.width} height={spec.height} fps={spec.fps} durationInFrames={spec.duration_frames}/>;
registerRoot(Root);
'''

RENDER = '''import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia} from '@remotion/renderer';
const root=path.dirname(fileURLToPath(import.meta.url));
const serveUrl=await bundle({entryPoint:path.join(root,'index.jsx'),publicDir:path.join(root,'public')});
const browserExecutable=process.env.BEAT_SYNC_BROWSER||undefined;
const composition=await selectComposition({serveUrl,id:'BeatSyncMotion',browserExecutable});
await renderMedia({serveUrl,composition,codec:'h264',pixelFormat:'yuv420p',outputLocation:process.argv[2],browserExecutable,concurrency:1});
'''


def export_composition(spec, work, render=None):
    work = Path(work).resolve()
    data = copy.deepcopy(spec)
    data["fps"] = int(_number(data.get("fps", 30), "fps", 1, 120, True))
    for key, default in (("width", 1080), ("height", 1920)):
        data[key] = int(_number(data.get(key, default), key, 2, 8192, True))
        if data[key] % 2:
            raise ValueError("Remotion canvas dimensions must be even")
    data["duration_frames"] = round(_number(data.get("duration", 10), "duration", 1 / data["fps"], 3600) * data["fps"])
    data.setdefault("graphics", [])
    data["style"] = {"background": "#172435", "foreground": "#FFFFFF", "accent": "#FFD633", "font_size": 58, **data.get("style", {})}
    validate_graphics(data)
    from font_diagnostics import inspect_project_fonts
    if any(item["status"] != "pass" for item in inspect_project_fonts(data)):
        raise ValueError("Composition font does not cover all required text characters")
    if data.get("titles") or data.get("subtitles") or data.get("audio") or data.get("audio_mix"):
        raise ValueError("Remotion export accepts graphics layers; compose captions/audio in the main project after rendering")
    if any(layer.get("kind", "card") not in ("card", "rectangle", "counter", "bar") for layer in data["graphics"]):
        raise ValueError("Remotion adapter supports card, rectangle, counter and bar; use the local renderer for image/video layers")
    if any(layer.get("font") for layer in data["graphics"]):
        raise ValueError("Use style.font for the composition font")
    data.setdefault("background", data["style"]["background"])
    data["fontFamily"] = "ProjectFont" if data["style"].get("font") else "Arial, sans-serif"
    copied = {}
    if data["style"].get("font"):
        font = Path(data["style"]["font"])
        name = "font-" + file_hash(font)[:16] + font.suffix.lower()
        copied["public/" + name] = font.read_bytes()
        data["style"]["fontUrl"] = "/" + name
    package = {"private": True, "type": "module", "scripts": {"render": "node render.mjs", "studio": "remotion studio index.jsx"},
               "dependencies": {"remotion": REMOTION_VERSION, "@remotion/bundler": REMOTION_VERSION,
                                "@remotion/renderer": REMOTION_VERSION, "@remotion/cli": REMOTION_VERSION,
                                "react": "19.1.0", "react-dom": "19.1.0"}}
    files = {"index.jsx": ENTRY, "render.mjs": RENDER,
             "package.json": json.dumps(package, indent=2) + "\n",
             "composition.json": json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"}
    previous_path = work / "beat-sync-export.json"
    previous = read_json(previous_path).get("files", {}) if previous_path.is_file() else {}
    for name in [*files, *copied]:
        destination = work / name
        if destination.exists() and (name not in previous or file_hash(destination) != previous[name]):
            raise ValueError(f"Preserve edited/unrelated file: {destination}; choose a new work directory")
    output = Path(render).resolve() if render else None
    if output and (output.suffix.lower() != ".mp4" or output in [work / name for name in files]):
        raise ValueError("Remotion render needs a distinct .mp4 output")
    work.mkdir(parents=True, exist_ok=True)
    (work / "public").mkdir(exist_ok=True)
    for name, text in files.items():
        (work / name).write_text(text, encoding="utf-8")
    for name, payload in copied.items():
        (work / name).write_bytes(payload)
    write_json(previous_path, {"files": {name: file_hash(work / name) for name in [*files, *copied]}})
    result = {"work": str(work), "composition": str(work / "composition.json"), "source": str(work / "index.jsx"),
              "rendered": False, "setup": "Run npm install in the composition directory; then npm run render -- OUTPUT.mp4",
              "remotion_version": REMOTION_VERSION, "docs": "https://www.remotion.dev/docs/renderer/render-media"}
    if output:
        node = shutil.which("node")
        if not node or not (work / "node_modules" / "@remotion" / "renderer").is_dir():
            raise RuntimeError(f"Editable composition exported to {work}. Install Node and run npm install there before rendering")
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run([node, str(work / "render.mjs"), str(output)], cwd=work, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=1800)
        if completed.returncode:
            raise RuntimeError("Remotion render failed: " + completed.stderr[-4000:] + completed.stdout[-2000:])
        from project_render import probe
        info = probe(output, count_frames=True)
        stream = next(s for s in info["streams"] if s["codec_type"] == "video")
        if int(stream["nb_read_frames"]) != data["duration_frames"] or stream["width"] != data["width"] or stream["height"] != data["height"]:
            raise RuntimeError("Remotion output dimensions/frame count differ from composition")
        result.update(rendered=True, video=str(output), frames=int(stream["nb_read_frames"]), sha256=file_hash(output),
                      visual_review="not_reviewed")
    return result
