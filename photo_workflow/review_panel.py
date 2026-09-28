"""Local before/after browser for a completed batch. Pixels never leave this process."""
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
from PIL import ImageTk

from .imaging import decode_working, preview
from .runtime import json_write, local_runtime, workspace_path


def change_summary(item):
    """Describe saved settings across every stage, without trusting assistant prose."""
    from .edits import DEFAULTS
    lines=[]
    conversion=item.get('conversion')
    if conversion:
        lines.append('HEIC/HEIF preparation · 16-bit TIFF; decoded RGB samples verified exactly; '+conversion['color']+'. Original retained.')
    labels={'Exposure2012':'Exposure (stops)', 'Contrast2012':'Contrast',
            'Highlights2012':'Highlights', 'Shadows2012':'Shadows', 'Whites2012':'Whites',
            'Blacks2012':'Blacks', 'Temperature':'White balance (K)', 'Tint':'Tint',
            'LuminanceSmoothing':'Luminance noise reduction', 'ColorNoiseReduction':'Color noise reduction',
            'LuminanceNoiseReductionDetail':'Luminance detail preservation',
            'LuminanceNoiseReductionContrast':'Luminance contrast preservation',
            'ColorNoiseReductionDetail':'Color detail preservation',
            'ColorNoiseReductionSmoothness':'Color noise smoothness',
            'AutoLateralCA':'Chromatic aberration correction', 'LensProfileEnable':'Lens profile correction',
            'CropAngle':'Straighten (degrees)', 'SaturationAdjustmentPurple':'Purple saturation',
            'LensManualDistortionAmount':'Lens distortion', 'VignetteAmount':'Vignette',
            'VignetteMidpoint':'Vignette midpoint'}
    def value(v):return f'{v:g}' if isinstance(v,(int,float)) else json.dumps(v,ensure_ascii=False)
    def target(t):
        position={'single':'selected','leftmost':'leftmost','rightmost':'rightmost','all':'all'}.get(t.get('position'),'selected')
        description=f'{position} {t.get("category", "face")}'
        return 'background around '+description if t.get('invert') else description
    def scope(recipe):
        if recipe.get('selection'):return target(recipe['selection'])
        return 'painted mask' if recipe.get('grade_mask') else 'whole image'
    stages=list(dict.fromkeys([item['output'],*item.get('stages',[]),item.get('final_output',item['output'])]))
    for stage in stages:
        try:
            job=json.loads((workspace_path(stage)/'job.json').read_text(encoding='utf-8'))
            settings=job.get('settings',{});runtime=job.get('runtime',{})
            if 'before' in settings and 'after' in settings:
                info=settings['before']
                camera=' '.join(str(info.get(k) or '') for k in ('camera_make','camera_model')).strip()
                if camera or info.get('source_encoding'):
                    iso=str(info.get('iso') or 'unknown')
                    if not iso.upper().startswith('ISO'): iso='ISO '+iso
                    encoding=info.get('source_encoding', 'encoding unknown').replace('_', ' ')
                    lines.append(f'Source · {camera or "Camera unknown"}; {iso}; {encoding}')
                before=settings['before'].get('settings',{});after=settings['after'].get('settings',{})
                crop=('CropLeft','CropTop','CropRight','CropBottom')
                if any(before.get(k)!=after.get(k) for k in crop) and all(k in after for k in crop):
                    edges=', '.join(f'{after[k]*100:g}%' for k in crop)
                    lines.append(f'Lightroom · Crop edges (left, top, right, bottom): {edges}')
                for key,new in sorted(after.items()):
                    if key in crop or before.get(key)==new:continue
                    label=labels.get(key,key.replace('ToneCurvePV2012','Tone curve ').replace('Parametric','Tone '))
                    old=before.get(key)
                    lines.append(f'Lightroom · {label}: '+(f'{value(old)} → ' if key in before else '')+value(new))
                local=settings.get('local') or {}
                for op in local.get('operations',[]):
                    region=', '.join(f'{v*100:g}%' for v in op['region'])
                    detail='curve '+value(op['curve']) if op['kind']=='curve' else 'donor offset '+value(op['donor_offset'])
                    lines.append(f'Photoshop · {op["kind"].capitalize()} in region [{region}]; {detail}; feather {op["feather"]*100:g}%')
            recipe=settings.get('recipe',{})
            if recipe:
                if recipe.get('denoise'):
                    where=scope(recipe) if recipe.get('denoise_scope')=='selection' else 'whole image'
                    lines.append(f'Denoise · {where}; blend {recipe["denoise"]*100:g}% ({recipe.get("denoise_model","drunet").upper()}, rendered RGB)')
                for key,default in DEFAULTS.items():
                    if key in ('denoise','noise_sigma') or recipe.get(key,default)==default:continue
                    label=key.replace('_',' ').capitalize()
                    amount=f'{recipe[key]:+g} stops' if key=='exposure' else value(recipe[key])
                    lines.append(f'{label} · {scope(recipe)}; {amount}')
                if recipe.get('inpaint') and runtime.get('inpainting_invoked'):
                    op=recipe['inpaint'];where=target(op['target']) if op.get('target') else 'painted mask'
                    lines.append(f'Local removal · {where}; expand {op.get("expand",8)}px, feather {op.get("feather",4)}px. Replacement content is estimated.')
                if recipe.get('removal'):
                    op=recipe['removal']
                    lines.append(f'Clone removal · painted mask; donor offset ({op["dx"]}, {op["dy"]})px; feather {op["feather"]}px')
                if recipe.get('restore_faces',{}).get('strength') and runtime.get('restoration_invoked'):
                    op=recipe['restore_faces']
                    lines.append(f'Face restoration · {target(op)}; blend {op["strength"]*100:g}%; {job.get("faces",0)} face(s). Detail is estimated and may alter likeness.')
            if 'upscale_strength' in settings:
                strength=settings['upscale_strength'];method=settings.get('upscale_model','realesrgan') if strength else 'interpolation only'
                lines.append(f'Upscale · {settings["scale"]}×; detail blend {strength*100:g}% ({method}); '+
                             ' × '.join(map(str,job['output_size']))+' pixels')
        except (OSError,ValueError,KeyError,TypeError) as error:
            lines.append(f'Change record unavailable for {Path(stage).name}: {error}')
    for warning in item.get('warnings',[]):lines.append('Reported warning: '+str(warning))
    if item.get('error'):lines.append('Reported issue: '+item['error'])
    return '\n'.join('• '+line for line in lines) or 'No changed settings are recorded for this image.'


class ReviewPanel:
    def __init__(self, window, report_path):
        self.window = window
        self.report_path = workspace_path(report_path)
        self.report = json.loads(self.report_path.read_text(encoding='utf-8'))
        self.items = [item for item in self.report['files'] if item['status'] == 'passed']
        if not self.items: raise ValueError('No completed photos to review')
        window.title('Photo Workflow — Before & After')
        window.geometry('1280x820'); window.minsize(820, 560)
        self.index = 0; self.pixels = []; self.images = []; self.center = [.5, .5]
        self.mode = tk.StringVar(value='Fit')
        self.title = ttk.Label(window, font=('Segoe UI', 15, 'bold')); self.title.pack(anchor='w', padx=16, pady=(14,4))
        self.info = ttk.Label(window); self.info.pack(anchor='w', padx=16)
        row = ttk.Frame(window); row.pack(fill='x', padx=16, pady=10)
        ttk.Button(row,text='Previous',command=lambda:self.select(-1)).pack(side='left')
        ttk.Button(row,text='Next',command=lambda:self.select(1)).pack(side='left',padx=6)
        for mode in ('Fit', '100%'):
            ttk.Radiobutton(row,text=mode,variable=self.mode,value=mode,command=self.draw).pack(side='left',padx=6)
        ttk.Label(row,text='Drag either image to pan at 100%.').pack(side='left',padx=12)
        ttk.Button(row,text='Open output folder',command=self.open_folder).pack(side='right')
        ttk.Button(row,text='Open layered edit',command=self.open_layered).pack(side='right',padx=6)
        details=ttk.LabelFrame(window,text='What changed · from saved edit settings')
        details.pack(fill='x',padx=16,pady=(0,8))
        self.changes=tk.Text(details,height=6,wrap='word',font=('Segoe UI',10),relief='flat',padx=8,pady=6)
        scroll=ttk.Scrollbar(details,command=self.changes.yview)
        self.changes.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.changes.pack(fill='both',expand=True)
        area = ttk.Frame(window); area.pack(fill='both',expand=True,padx=16)
        self.canvases=[]
        for label in ('BEFORE · input render', 'AFTER · final edit'):
            frame=ttk.Frame(area);frame.pack(side='left',fill='both',expand=True,padx=3)
            ttk.Label(frame,text=label,font=('Segoe UI',10,'bold')).pack(anchor='w',pady=5)
            canvas=tk.Canvas(frame,bg='#181a1e',highlightthickness=0)
            canvas.pack(fill='both',expand=True)
            canvas.bind('<Configure>',lambda _:self.draw())
            canvas.bind('<ButtonPress-1>',self.start_pan)
            canvas.bind('<B1-Motion>',self.pan)
            self.canvases.append(canvas)
        self.note=ttk.Label(window,wraplength=1200);self.note.pack(fill='x',padx=16,pady=12)
        window.bind('<Left>',lambda _:self.select(-1));window.bind('<Right>',lambda _:self.select(1))
        self.select(0)
        if len(self.pixels)!=2:raise RuntimeError('Initial comparison could not be loaded')
        window.after_idle(lambda:json_write(self.report_path.parent/'review-ui-status.json',
                                           {'status':'ready','photos':len(self.items),'pid':os.getpid()}))

    def select(self, delta):
        self.index=(self.index+delta)%len(self.items);item=self.items[self.index]
        self.changes.configure(state='normal');self.changes.delete('1.0','end')
        self.changes.insert('end',change_summary(item))
        if self.report.get('prompt'):
            self.changes.insert('end','\n\nYour request (compare with the recorded changes above):\n'+self.report['prompt'])
        self.changes.configure(state='disabled');self.changes.yview_moveto(0)
        self.pixels.clear();self.images.clear();self.center=[.5,.5]
        try:
            before=workspace_path(Path(item['output'])/'original.tif')
            after=workspace_path(item['tiff'])
            self.pixels=[decode_working(p.read_bytes())[0] for p in (before,after)]
        except Exception as error:
            messagebox.showerror('Cannot load comparison',str(error),parent=self.window);return
        self.title['text']=f"{self.index+1} / {len(self.items)}  ·  {Path(item['source']).name}"
        sizes=[' × '.join(map(str,(a.shape[1],a.shape[0]))) for a in self.pixels]
        self.info['text']=f'Before {sizes[0]}    →    After {sizes[1]}   |   Local 16-bit originals retained; display is 8-bit sRGB'
        finish=self.report.get('finish',{})
        statuses=' · '.join(f'{key}: {value.get("status", "unknown")}'+
                           (f' ({value["reason"]})' if value.get('reason') else '')
                           for key,value in finish.get('adobe',{}).items())
        self.note['text']='Crops and upscale can change framing or dimensions. 100% shows source pixels without display scaling. '+statuses
        self.draw()

    def draw(self):
        if len(self.pixels)!=2:return
        self.images=[]
        for canvas,pixels in zip(self.canvases,self.pixels):
            w,h=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
            if self.mode.get()=='100%':
                ih,iw=pixels.shape[:2]
                x=int(np.clip(self.center[0]*iw-w/2,0,max(0,iw-w)))
                y=int(np.clip(self.center[1]*ih-h/2,0,max(0,ih-h)))
                im=preview(pixels[y:y+h,x:x+w])
            else:im=preview(pixels,(w,h))
            image=ImageTk.PhotoImage(im,master=self.window);self.images.append(image)
            canvas.delete('all');canvas.create_image(w/2,h/2,image=image)

    def start_pan(self,event):self.drag=(event.x,event.y,*self.center)

    def pan(self,event):
        if self.mode.get()!='100%':return
        x,y,cx,cy=self.drag
        index=self.canvases.index(event.widget);h,w=self.pixels[index].shape[:2]
        self.center=[float(np.clip(cx-(event.x-x)/w,0,1)),float(np.clip(cy-(event.y-y)/h,0,1))]
        self.draw()

    def open_folder(self):os.startfile(workspace_path(self.items[self.index].get('final_output',self.items[self.index]['output'])))

    def open_layered(self):
        path=self.items[self.index].get('psd')
        if path and workspace_path(path).exists():os.startfile(path)
        else:messagebox.showinfo('TIFF only','This batch did not request a layered export.',parent=self.window)


def main():
    import sys
    local_runtime()
    # Keep the 100% view at one image pixel per display pixel on scaled Windows desktops.
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    root=tk.Tk()
    try:ReviewPanel(root,sys.argv[1]);root.mainloop()
    except Exception as error:
        json_write(workspace_path(sys.argv[1]).parent/'review-ui-status.json',{'status':'failed','error':str(error)})
        raise


if __name__=='__main__':main()
