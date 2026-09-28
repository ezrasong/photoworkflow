"""User-operated public image search. No selected source/photo/note is accepted."""
import argparse
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from PIL import Image, ImageTk

from .public_references import search, download
from .runtime import ROOT, json_write, workspace_path, local_runtime


class Browser:
    def __init__(self, root, output, suggested=''):
        self.root=root;self.output=output;self.events=queue.Queue();self.items=[];self.selected=[];self.busy=False
        root.title('Choose photo references');root.geometry('920x700')
        ttk.Label(root,text='Find references for your current request',font=('Segoe UI',16)).pack(anchor='w',padx=14,pady=12)
        ttk.Label(root,text='Only the search text below is sent to Wikimedia Commons. Your photos and notes stay local.').pack(anchor='w',padx=14)
        row=ttk.Frame(root);row.pack(fill='x',padx=14,pady=10)
        self.query=tk.StringVar(value=suggested)
        ttk.Entry(row,textvariable=self.query).pack(side='left',fill='x',expand=True)
        self.search_button=ttk.Button(row,text='Search public images',command=self.search);self.search_button.pack(side='left',padx=8)
        ttk.Button(row,text='Choose local references',command=self.local).pack(side='left')
        self.list=tk.Listbox(root,height=8,exportselection=False);self.list.pack(fill='x',padx=14)
        self.list.bind('<<ListboxSelect>>',lambda _:self.preview())
        self.image=ttk.Label(root,anchor='center');self.image.pack(fill='both',expand=True,padx=14,pady=8)
        self.info=ttk.Label(root,text='Search by subject, material, lighting or style. Choose up to three references.',wraplength=850)
        self.info.pack(fill='x',padx=14)
        row=ttk.Frame(root);row.pack(fill='x',padx=14,pady=12)
        ttk.Button(row,text='Add displayed reference',command=self.add).pack(side='left')
        self.count=ttk.Label(row,text='0 selected');self.count.pack(side='left',padx=14)
        ttk.Button(row,text='Use selected references',command=self.done).pack(side='right')
        root.protocol('WM_DELETE_WINDOW',self.done);root.after(100,self.poll)
        self.current=None;self.search_query='';self.generation=0

    def background(self, kind, function):
        if self.busy:return
        self.busy=True;self.search_button['state']='disabled'
        generation=self.generation
        def run():
            try:self.events.put((kind,function(),generation))
            except Exception as e:self.events.put(('error',str(e),generation))
        threading.Thread(target=run,daemon=True).start()

    def search(self):
        if self.busy:return
        self.search_query=self.query.get().strip();self.current=None;self.generation+=1
        self.info['text']='Searching Commons…'
        self.background('results',lambda:search(self.search_query))

    def preview(self):
        if self.busy:return
        selected=self.list.curselection()
        if not selected:return
        item=self.items[selected[0]];self.current=None
        self.info['text']='Downloading selected public preview…'
        self.background('preview',lambda:(download(item,self.search_query),item))

    def local(self):
        names=filedialog.askopenfilenames(parent=self.root,title='Choose up to three local references',
            initialdir=ROOT/'references',filetypes=[('Photographs','*.jpg *.jpeg *.png *.tif *.tiff')])
        for name in names:
            if name not in self.selected and len(self.selected)<3:self.selected.append(name)
        self.count['text']=f'{len(self.selected)} selected'

    def add(self):
        if self.current and str(self.current) not in self.selected:
            if len(self.selected)>=3:return messagebox.showinfo('Reference limit','Select up to three references per comparison.',parent=self.root)
            self.selected.append(str(self.current));self.count['text']=f'{len(self.selected)} selected'

    def poll(self):
        try:
            while True:
                kind,value,generation=self.events.get_nowait();self.busy=False;self.search_button['state']='normal'
                if generation!=self.generation:continue
                if kind=='error':self.info['text']=value
                elif kind=='results':
                    self.items=value;self.list.delete(0,'end')
                    for item in value:self.list.insert('end',item['title']+' — '+(item['license'] or 'check source license'))
                    self.info['text']=f'{len(value)} results. Select one to preview locally; Add keeps it for comparison.'
                elif kind=='preview':
                    path,item=value
                    from .imaging import decode_working,preview
                    pixels,_=decode_working(path.read_bytes());im=preview(pixels);im.thumbnail((850,360))
                    self.tkimage=ImageTk.PhotoImage(im);self.image['image']=self.tkimage;self.current=path
                    self.info['text']=item['title']+' | '+item['license']+' | '+item['artist'][:180]
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def done(self):
        json_write(self.output,self.selected);self.root.destroy()


def main():
    local_runtime();parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--query',default='')
    args=parser.parse_args();output=workspace_path(args.output)
    if not output.is_relative_to(ROOT/'.cache/control'):raise ValueError('Invalid reference-selection output')
    output.parent.mkdir(parents=True,exist_ok=True)
    root=tk.Tk();Browser(root,output,args.query[:200]);root.mainloop()


if __name__=='__main__':main()
