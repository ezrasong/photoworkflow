"""Local-only mask painting and the editing/agent controls."""
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from .edits import DEFAULTS, validate_recipe
from .imaging import decode_working, stable_read, preview, save_mask
from .runtime import ROOT, json_write, sha256

class MaskPainter:
    def __init__(self, parent, source, clone, saved, initial_mask=None):
        pixels,_=decode_working(stable_read(source,settle=0))
        from .selection import pixel_hash, assert_binding
        self.binding = dict(source_pixel_sha256=pixel_hash(pixels), source_file_sha256=sha256(source),
                            dimensions=[pixels.shape[1],pixels.shape[0]], coordinate_transform=[1,0,0,0,1,0],
                            method='local painted/corrected mask')
        self.size=(pixels.shape[1],pixels.shape[0]); self.clone=clone; self.saved=saved
        self.mask=Image.new('I',self.size); self.source=None; self.anchor=None; self.previous=None
        if initial_mask:
            from pathlib import Path
            from .edits import mask_pixels
            path=Path(initial_mask); sidecar=path.with_suffix('.json')
            if sidecar.exists(): assert_binding(json.loads(sidecar.read_text(encoding='utf-8')),pixels)
            self.mask=Image.fromarray(mask_pixels(stable_read(path,0),pixels.shape).astype(np.int32))
        self.window=tk.Toplevel(parent); self.window.title('Paint clone removal' if clone else 'Paint grade mask')
        ttk.Label(self.window,text=('Right-click clear donor pixels, then paint the distraction. Red is the removal area.' if clone else
                  'Paint the area to grade. Red receives color/tone edits. Black is protected.')).pack(padx=12,pady=8)
        self.base=preview(pixels); self.base.thumbnail((1000,600))
        self.scale=self.size[0]/self.base.width
        self.canvas=tk.Canvas(self.window,width=self.base.width,height=self.base.height,highlightthickness=0)
        self.canvas.pack(padx=12); self.item=self.canvas.create_image(0,0,anchor='nw')
        self.radius=tk.IntVar(value=20)
        self.erase=tk.BooleanVar(value=False)
        row=ttk.Frame(self.window); row.pack(fill='x',padx=12,pady=8)
        ttk.Label(row,text='Brush radius (image pixels)').pack(side='left')
        ttk.Spinbox(row,from_=1,to=500,textvariable=self.radius,width=6).pack(side='left',padx=8)
        ttk.Button(row,text='Clear',command=self.clear).pack(side='left')
        ttk.Checkbutton(row,text='Erase',variable=self.erase).pack(side='left')
        ttk.Button(row,text='Save mask',command=self.save).pack(side='right')
        self.info=ttk.Label(self.window,text='');self.info.pack(pady=4)
        self.canvas.bind('<ButtonPress-1>',self.begin); self.canvas.bind('<B1-Motion>',self.paint)
        self.canvas.bind('<ButtonRelease-1>',lambda _:setattr(self,'previous',None))
        self.canvas.bind('<ButtonPress-3>',self.donor)
        self.refresh()

    def point(self,event):
        return (max(0,min(self.size[0]-1,round(event.x*self.scale))),
                max(0,min(self.size[1]-1,round(event.y*self.scale))))

    def donor(self,event):
        if self.clone:
            self.source=self.point(event); self.anchor=None
            self.mask=Image.new('I',self.size); self.refresh()
            self.info['text']=f'Donor selected at {self.source}; paint destination next.'

    def begin(self,event):
        if self.clone and self.source is None:
            messagebox.showinfo('Select donor','Right-click a clear source area first.',parent=self.window);return
        if self.anchor is None:self.anchor=self.point(event)
        self.previous=None;self.paint(event)

    def paint(self,event):
        if self.clone and self.source is None:return
        try: radius=max(1,min(500,self.radius.get()))
        except tk.TclError:return
        x,y=self.point(event);draw=ImageDraw.Draw(self.mask)
        value=0 if self.erase.get() else 65535
        if self.previous:draw.line([self.previous,(x,y)],fill=value,width=radius*2)
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=value)
        self.previous=(x,y); self.refresh()

    def refresh(self):
        small=Image.fromarray(np.rint(np.asarray(self.mask)/257).astype(np.uint8)).resize(self.base.size)
        overlay=Image.new('RGB',self.base.size,(255,40,40))
        view=Image.composite(overlay,self.base,small.point(lambda x:round(x*.45)))
        self.photo=ImageTk.PhotoImage(view);self.canvas.itemconfigure(self.item,image=self.photo)

    def clear(self):
        self.mask=Image.new('I',self.size);self.anchor=None;self.previous=None;self.refresh()

    def save(self):
        if not self.mask.getbbox():return messagebox.showinfo('Empty mask','Paint an area first.',parent=self.window)
        folder=ROOT/'.cache/masks';folder.mkdir(exist_ok=True,parents=True)
        path=folder/(uuid.uuid4().hex+'.tif')
        save_mask(path,np.asarray(self.mask).astype(np.uint16))
        json_write(path.with_suffix('.json'),dict(self.binding,mask_sha256=sha256(path)))
        removal=None
        if self.clone:
            removal={'mask':str(path),'dx':self.source[0]-self.anchor[0],
                     'dy':self.source[1]-self.anchor[1],'feather':8}
        self.saved(str(path),removal);self.window.destroy()

class Editor:
    def __init__(self,app):
        self.app=app;self.removal=None
        w=self.window=tk.Toplevel(app.window);w.title('Local photo editor');w.geometry('760x740')
        root=ttk.Frame(w,padding=16);root.pack(fill='both',expand=True)
        ttk.Label(root,text='Grade, denoise and masked clone',font=('Segoe UI',16)).pack(anchor='w')
        row=ttk.Frame(root);row.pack(fill='x',pady=8)
        ttk.Entry(row,textvariable=app.path).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Choose photo',command=self.choose).pack(side='left',padx=6)
        ttk.Label(root,text='Original dimensions · 16-bit sRGB · separate raster layers and saved recipe').pack(anchor='w')
        self.mask=tk.StringVar();self.mask_label=tk.StringVar(value='Grade mask: whole image')
        row=ttk.Frame(root);row.pack(fill='x',pady=8)
        ttk.Button(row,text='Paint grade mask',command=lambda:self.paint(False)).pack(side='left')
        ttk.Button(row,text='Import mask',command=self.import_mask).pack(side='left',padx=6)
        ttk.Button(row,text='Whole image',command=lambda:(self.mask.set(''),self.mask_label.set('Grade mask: whole image'))).pack(side='left')
        ttk.Label(root,textvariable=self.mask_label).pack(anchor='w')
        book=ttk.Notebook(root);book.pack(fill='both',expand=True,pady=10)
        manual=ttk.Frame(book,padding=12);agent=ttk.Frame(book,padding=12)
        book.add(manual,text='Manual edits');book.add(agent,text='Local assistant (text only)')
        self.values={k:tk.StringVar(value=str(v)) for k,v in DEFAULTS.items()}
        labels={'exposure':'Exposure (stops, -3 to 3)','warmth':'Warmth (-1 to 1)','tint':'Tint (-1 to 1)',
                'contrast':'Contrast (0.5 to 1.5)','shadows':'Shadow curve (-0.3 to 0.3)','highlights':'Highlight curve (-0.3 to 0.3)',
                'saturation':'Saturation (0 to 2)','purple_saturation':'Purple saturation (0 to 2)',
                'denoise':'Denoise blend (0 to 1)','noise_sigma':'DRUNet noise level (1 to 50)'}
        for i,(key,label) in enumerate(labels.items()):
            ttk.Label(manual,text=label).grid(row=i,column=0,sticky='w',pady=3)
            ttk.Entry(manual,textvariable=self.values[key],width=12).grid(row=i,column=1,padx=15)
        self.denoise_model=tk.StringVar(value='drunet')
        ttk.Label(manual,text='Denoiser').grid(row=10,column=0,sticky='w')
        ttk.Combobox(manual,textvariable=self.denoise_model,values=('drunet','scunet'),state='readonly',width=12).grid(row=10,column=1,padx=15)
        row=ttk.Frame(manual);row.grid(row=11,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Button(row,text='Paint clone removal',command=lambda:self.paint(True)).pack(side='left')
        ttk.Button(row,text='Clear removal',command=self.clear_removal).pack(side='left',padx=6)
        self.removal_label=ttk.Label(manual,text='No removal. Clone copies a donor; hidden content is not recovered.')
        self.removal_label.grid(row=12,column=0,columnspan=2,sticky='w')
        ttk.Button(manual,text='Load selected job recipe',command=self.load).grid(row=13,column=0,sticky='w',pady=8)
        ttk.Button(manual,text='Apply manual edits',command=self.apply).grid(row=13,column=1)
        ttk.Label(agent,text='Describe color/tone or denoise changes. For subject-only edits, paint a grade mask first.',wraplength=620).pack(anchor='w')
        self.request=tk.Text(agent,height=6,wrap='word');self.request.pack(fill='x',pady=10)
        self.request.insert('1.0','Reduce noise moderately and lift exposure half a stop across the whole image while keeping purple stage lighting.')
        ttk.Label(agent,text='Qwen3-4B runs locally. It cannot see the photo. One validated editing tool; no shell, web or remote fallback. Clone removal is manual.',wraplength=620).pack(anchor='w')
        self.psd=tk.BooleanVar(value=True)
        ttk.Checkbutton(agent,text='Export a layered PSD after processing',variable=self.psd).pack(anchor='w',pady=12)
        ttk.Button(agent,text='Run local assistant',command=self.ask).pack(anchor='w')
        ttk.Label(root,text='Review every result locally. SCUNet targets mixed noise; DRUNet uses a Gaussian noise level. Both process rendered RGB. Use the main panel to stop, compare or export.',wraplength=700).pack(anchor='w')

    def choose(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Photos','*.jpg *.jpeg *.png *.tif *.tiff')])
        if path:
            self.app.path.set(path);self.mask.set('');self.mask_label.set('Grade mask: whole image');self.clear_removal()

    def paint(self,clone):
        try:MaskPainter(self.window,self.app.path.get(),clone,self.saved_removal if clone else self.saved_mask,
                        initial_mask=self.mask.get() if not clone else None)
        except Exception as e:messagebox.showerror('Cannot paint',str(e),parent=self.window)

    def saved_mask(self,path,_=None):self.mask.set(path);self.mask_label.set('Grade mask selected (white edits, black protects)')
    def saved_removal(self,path,removal):
        self.removal=removal;self.removal_label['text']=f"Clone selected: donor offset {removal['dx']}, {removal['dy']}; feather 8 pixels inward."
    def clear_removal(self):self.removal=None;self.removal_label['text']='No removal. Clone replacement is synthetic.'
    def import_mask(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('Grayscale mask','*.png *.tif *.tiff')])
        if path:self.saved_mask(path)
    def load(self):
        folder=self.app.selected()
        try:
            r=json.loads((folder/'recipe.json').read_text())
            for k in DEFAULTS:self.values[k].set(str(r[k]))
            self.denoise_model.set(r.get('denoise_model','drunet'))
            self.mask.set(r.get('grade_mask',''));self.mask_label.set('Grade mask loaded' if self.mask.get() else 'Grade mask: whole image')
            self.removal=r.get('removal');self.removal_label['text']='Removal loaded' if self.removal else 'No removal'
        except Exception as e:messagebox.showerror('Cannot load recipe',str(e),parent=self.window)
    def apply(self):
        try:
            recipe={k:float(v.get()) for k,v in self.values.items()}
            recipe['denoise_model']=self.denoise_model.get()
            if self.mask.get():recipe['grade_mask']=self.mask.get()
            if self.removal:recipe['removal']=self.removal
            recipe=validate_recipe(recipe)
            path=ROOT/'.cache/control'/(uuid.uuid4().hex+'.json');path.parent.mkdir(exist_ok=True,parents=True);json_write(path,recipe)
            self.app.launch(['edit',self.app.path.get(),'--recipe',str(path)],True)
        except Exception as e:messagebox.showerror('Cannot edit',str(e),parent=self.window)
    def ask(self):
        args=['agent',self.app.path.get(),'--request',self.request.get('1.0','end').strip()]
        if self.mask.get():args+=['--grade-mask',self.mask.get()]
        if self.psd.get():args+=['--export-psd']
        self.app.launch(args,True)
