from __future__ import print_function
import subprocess
import tempfile
import os
import shutil
import sys
import StringIO

class TexTonic:
    def __init__(self,res=300):
        self.dir = tempfile.mkdtemp(prefix='textonic_')
        self.gs = 'gswin32c' if os.name == 'nt' else 'gs'
        self.epsdev = None
        self.latex = 'pdflatex'
        self.res = res
        self.outline = True

    def __del__(self):
        self.cleanup()
        
    def _baseGS(self,res=None):
        if res is None: res = self.res
        return [self.gs,'-dBATCH','-dNOPAUSE','-dSAFER','-dTextAlphaBits=4','-dGraphicsAlphaBits=4','-r%d'%res]
        
    def _exec(self,args,cb=None):
        # http://stackoverflow.com/questions/7006238/how-do-i-hide-the-console-when-i-use-os-system-or-subprocess-call
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.pipe = subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=self.dir,shell=False,startupinfo=startupinfo)
        if cb is not None:
            for line in iter(self.pipe.stdout.readline,''):
                cb(line.rstrip())
        code = self.pipe.wait()
        print('>>',args,file=sys.stderr)
        return code
        
    def computeBounds(self, src, res=1200):
        if self._exec(self._baseGS()+['-sDEVICE=bbox',src]):
            self.finished.emit('Ghostscript BBOX failed')
            return False
        bboxinfo = self.pipe.stderr.read()
        self.pipe = None # close the pipe
        # find the highres info
        for l in bboxinfo.split('\n'):
            if l.startswith('%%HiResBoundingBox:'):
                return [float(x) for x in l.split(' ')[1:5]]
        raise RuntimeError('Failed to compute bounding box')
        
    def runLatex(self, data, cb=None):
        src = 'textonic.tex'
        dest = 'textonic.pdf'
        # create the tex file
        psrc = os.path.join(self.dir,src)
        pdest = os.path.join(self.dir,dest)
        open(psrc,'wb').write(data)
        if os.path.isfile(pdest): os.remove(pdest)
        if self._exec([self.latex,'-interaction=nonstopmode',src],cb):
            raise RuntimeError('LaTeX failed')
        return dest
        
    def convert(self, src, fmt, cb=None):
        gscmd = self._baseGS()
        gsextra = []
        if fmt in ('PNG',2):
            dest = 'output.png'
            dev = 'pngalpha'
            # src must be an eps or pdf
            bbox = self.computeBounds(src)
            # bbox is spec in pts
            w = round((bbox[2]-int(bbox[0]))*self.res/72.0 + 0.5)
            h = round((bbox[3]-int(bbox[1]))*self.res/72.0 + 0.5)
            # these need to go AFTER the device specification
            gsextra = ['-g%dx%d'%(w,h),'-c','<</Install {-%.2f -%.2f translate}>> setpagedevice'%(bbox[0],bbox[1])]
        else:
            dest = 'output.eps'
            # recent versions of GS have removed the outdated epswrite driver, so check which driver we need to use
            if self.epsdev is None:
                buffer = StringIO.StringIO()
                self._exec(gscmd + ['-h'], buffer.write)
                if 'eps2write' in buffer.getvalue():
                    self.epsdev = 'eps2write'
                elif 'epswrite' in buffer.getvalue():
                    self.epsdev = 'epswrite'
                else:
                    raise RuntimeError('Ghostscript does not support EPS device')
            dev = self.epsdev
            # crop by replacing the BBOX in the EPS
            gscmd = gscmd[:4] + ['-dEPSCrop']
            if self.outline: gscmd.append('-dNOCACHE' if self.epsdev == 'epswrite' else '-dNoOutputFonts')
        # run the conversion process
        if self._exec(gscmd+['-o',dest,'-sDEVICE='+dev]+gsextra+['-f',src],cb):
            raise RuntimeError('Ghostscript EPS conversion failed')
        if fmt in ('PDF',0):
            # turn the EPS into a PDF to ensure that fonts get outlined
            # if we didn't want to do this, we wouldn't have used convert
            src = dest
            dest = 'output.pdf'
            if self._exec(gscmd+['-o',dest,'-sDEVICE=pdfwrite','-f',src],cb):
                raise RuntimeError('Ghostscript PDF conversion failed')
        return dest
        
    def clipboard(self,src,fmt):
        import win32clipboard as clip
        clip.OpenClipboard()
        clip.EmptyClipboard()
        try:
            data = open(os.path.join(self.dir,src),'rb').read()
            if fmt == 'BMP':
                # to copy BMP data to the clipboard we need to generate the appropriate BITMAP header
                # let's cheat instead by using PIL to open the PNG, write a temporary BMP and 
                from PIL import Image
                png = Image.open(os.path.join(self.dir,src))
                src += '.bmp'
                # BMP does not really RGBA, so blend with white
                # https://stackoverflow.com/questions/9166400/convert-rgba-png-to-rgb-with-pil
                bmp = Image.new("RGB", png.size, (255, 255, 255))                
                bmp.paste(png, mask=png.split()[3])
                buffer = StringIO.StringIO() # use a StringIO object instead of a temp file
                bmp.save(buffer,format='bmp')
                iformat = clip.CF_DIB
                data = buffer.getvalue()[14:] # bypass the BITMAPFILEHEADER
            elif fmt == 'PNG':
                iformat = clip.RegisterClipboardFormat('PNG')
            elif fmt == 'PDF':
                iformat = clip.RegisterClipboardFormat('Portable Document Format')
            elif fmt == 'EPS':
                iformat = clip.RegisterClipboardFormat('Encapsulated PostScript')
            clip.SetClipboardData(iformat,data)
        except Exception as E:
            clip.CloseClipboard()
            raise   # ensure clipboard closed, then reraise
        clip.CloseClipboard()
        return True
        
    def cleanup(self):
        if getattr(self,'pipe',False):
            self.pipe.terminate()
            self.pipe = None
        if getattr(self,'dir',''):
            try:
                shutil.rmtree(self.dir)
            except Exception as E:
                print('!! Failed to remove dir,',E,file=sys.stderr)
            self.dir = None
