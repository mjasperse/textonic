import subprocess
import tempfile
import os
import shutil
import sys

class TexTonic:
    def __init__(self,res=300):
        self.dir = tempfile.mkdtemp(prefix='textonic_')
        self.gs = 'gswin32c' if os.name == 'nt' else 'gs'
        self.latex = 'pdflatex'
        self.res = res
        self.outline = True

    def __del__(self):
        self.cleanup()
        
    def _baseGS(self):
        return [self.gs,'-dBATCH','-dNOPAUSE','-dSAFER','-dTextAlphaBits=4','-dGraphicsAlphaBits=4','-r%d'%self.res]
        
    def _exec(self,args,cb=None):
        # http://stackoverflow.com/questions/7006238/how-do-i-hide-the-console-when-i-use-os-system-or-subprocess-call
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.pipe = subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=self.dir,shell=False,startupinfo=startupinfo)
        if cb is not None:
            for line in iter(self.pipe.stdout.readline,''):
                cb(line.rstrip())
        code = self.pipe.wait()
        print >> sys.stderr, '>>',args,'ret',code
        return code
        
    def computeBounds(self, src):
        if self._exec(self._baseGS()+['-sDEVICE=bbox',src]):
            self.finished.emit('Ghostscript BBOX failed')
            return False
        bboxinfo = self.pipe.stderr.read()
        self.pipe = None # close the pipe
        # find the highres info
        for l in bboxinfo.split('\n'):
            if l.startswith('%%HiResBoundingBox:'):
                return map(float, l.split(' ')[1:5])
        raise RuntimeError('Failed to compute bounding box')
        
    def runLatex(self, data, cb=None):
        src = 'textonic.tex'
        dest = 'textonic.pdf'
        # if the file exists, check if it's the same
        psrc = os.path.join(self.dir,src)
        pdest = os.path.join(self.dir,dest)
        try:
            if open(psrc,"rb").read() == data:
                return True
        except: pass
        # create the tex file
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
            gsextra = ['-g%dx%d'%(w,h),'-c','<</Install {-%d -%d translate}>> setpagedevice'%(int(bbox[0]),int(bbox[1]))]
        else:
            dest = 'output.eps'
            dev = 'epswrite'
            # crop by replacing the BBOX in the EPS
            gscmd = gscmd[:4] + ['-dEPSCrop']
            if self.outline: gscmd.append('-dNOCACHE')
        if self._exec(gscmd+['-o',dest,'-sDEVICE='+dev]+gsextra+['-f',src],cb):
            raise RuntimeError('Ghostscript EPS conversion failed')
        if fmt in ('PDF',0):
            # process via EPS to ensure that fonts get outlined
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
            data = None
            if fmt == 'PNG':
                from PIL import Image
                im = Image.open(os.path.join(self.dir,src))
                src += '.bmp'
                # TODO: blend with background color
                im.save(os.path.join(self.dir,src),format='bmp')
                iformat = clip.CF_DIB
                with open(os.path.join(self.dir,src),'rb') as f:
                    f.seek(14)  # bypass the BITMAPFILEHEADER
                    data = f.read()
            elif fmt == 'PDF':
                iformat = clip.RegisterClipboardFormat('Portable Document Format')
            elif fmt == 'EPS':
                iformat = clip.RegisterClipboardFormat('Encapsulated PostScript')
            else:
                raise RuntimeError('Unknown format')
            if data is None:
                data = open(os.path.join(self.dir,src),'rb').read()
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
                print '!! Failed to remove dir,',E
            self.dir = None
