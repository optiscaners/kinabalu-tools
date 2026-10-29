"""
firmware-duplicates.py - Script zur Erstellung eines Reports über duplizierte Files

Usage:

    firmware_duplicates -r <refdir> -b <basedir> [-o <reportfile>] [-v [-v]] [-h]

    -r <refdir>     - reference directory
    -b <basedir>    - directory that is scanned for duplicates
    -o <reportfile> - name of the reportfile
    -v              - increase verbose level of report (future implementation)
    -h              - show help and exit

Known Issue: Reference dir shall not have cmake-build folders.    
"""

# == modules ==
import difflib
import getopt
from pathlib import Path
import sys

# == globals == 

Candidates = {}         # dict with all reference file_names as keys
BaseDir = None
RefDir = None
OutFile = Path("report.md")
FileExtensions=[".c", ".cpp", ".h", ".hpp"]
VerboseReport = 0

# == classes ==

# class that represent a reference file
# it stores the 
# - the original file names
# - a list of copies (self.others)
class FileCandidate:
    def __init__(self, name, filepath, extra=False):
        self.name = name
        self.filepath = filepath
        self.extra = extra
        self.others = []

    def add_other(self, other):
        self.others.append(DerivedFile(other))

    def update_others(self):
        with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
            ref_lines = f.readlines()
        for other in self.others:
            other.compare_to(ref_lines)

    def get_total_changes(self):
        if len(self.others):
            rv = sum([o.total_changes for o in self.others])
        else:
            # -1 means list self.others is empty
            rv = -1
        return rv

    def get_relative_path(self, path):
        try:
            return self.filepath.relative_to(path)
        except ValueError:
            # not below path (e.g. RefDir outside of BaseDir) => keep full path
            return self.filepath

    def __repr__(self):
        return str(self.filepath)

# class that represent a duplicate file
class DerivedFile:
    def __init__(self, filepath):
        self.filepath = filepath
        self.total_changes = 0
        self.ins_changes = 0
        self.del_changes = 0

    def compare_to(self, ref_lines):
        with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        mydiff = list(difflib.unified_diff(ref_lines, lines))
        self.del_changes = sum([1 for l in mydiff[2:] if l.startswith('-')])
        self.ins_changes = sum([1 for l in mydiff[2:] if l.startswith('+')])
        self.total_changes = self.ins_changes + self.del_changes

    def __repr__(self):
        return str(self.filepath.name)
    
    def get_changes_as_str(self):
        rv = "???"
        if self.total_changes:
            rv = f"all: {self.total_changes}, ins: {self.ins_changes}, del: {self.del_changes}"
        else:
            rv = "unchanged"
        return rv

    def get_relative_path(self, path):
        return self.filepath.relative_to(path)

def get_ref_list(refdir, extensions):
    print("collect the reference files ...", end="")
    p = Path(refdir)
    l = []
    for ext in extensions:
        l +=  list(p.glob(f"**/*{ext}"))
    
    for i,v in enumerate(sorted(l)):
        if v.name not in Candidates:
            Candidates[v.name] = FileCandidate(v.name, v)
            #print(f"{i:04d} {v}  {v.name} {type(v)}")
        else:
            print (f"** duplicate name {v} : {Candidates[v.name]}")
            print("Warning: duplicate file name in reference dir, only the first one is used as reference!")
            
    print(f"done ({len(l)} files found) ")

def assign_duplicates(basedir, extensions):
    print("collect the duplicate files ...", end="")
    p = Path(basedir)
    l = []
    for ext in extensions:
        l +=  list(p.glob(f"**/*{ext}"))
    duplicates = 0
    extracandidates = 0
    for i,v in enumerate(sorted(l)):
        if v.name in Candidates:
            if not Candidates[v.name].filepath.is_relative_to(v):
                Candidates[v.name].add_other(v)
                duplicates += 1
            #else:
            #    print(f"thats a reference: {v}")
        else:
            #print (f"isolated file {v} => extra candidate")
            Candidates[v.name] = FileCandidate(v.name, v, extra=True)
            extracandidates += 1
    print(f" done (duplicates: {duplicates}, ExtraCandidates: {extracandidates})")

def Update_derived_files():
    print("update derived files ...", end="")
    for f in Candidates:
        #print(f" => {f}")
        cand = Candidates[f]
        cand.update_others()
    print("done")
        
# === dump functions for results ===
def dump_overview(fp = sys.stdout):
    FilesInRefdir = [ c.name for c in Candidates.values() if c.extra == False]
    FilesNotInRefdir = [ c.name for c in Candidates.values() if c.extra == True]
    UniqueFiles = [ c.name for c in Candidates.values() if len(c.others) < 1]
    DerivedFiles = sum([ len(c.others) for c in Candidates.values() ])
    print(f"""
# Overview

ReferenceDir: `{RefDir}`

BaseDir: `{BaseDir}`

There are:

- {len(Candidates)} Candidates in total
  - {len(FilesInRefdir)} Candidates in the ReferenceDir  
  - {len(FilesNotInRefdir)} Candidates outside of the ReferenceDir
- {DerivedFiles} Derived Files
            """, file=fp)

def dump_derived_files(fp = sys.stdout):
    global BaseDir
    derived_files= [c for c in Candidates.values() if c.get_total_changes() > 0]

    print(f"""
## Derived Files (Files w/ changes)
          
Path is relative to `{BaseDir}`

Number of derived files: {len(derived_files)}

          """, file = fp)

    for i,c in enumerate(derived_files, start=1):
        print(f"{i}. `{c.get_relative_path(BaseDir)}` \n" , file = fp)
        for o in c.others:
            print(f"    * {o.get_changes_as_str()} - `{o.get_relative_path(BaseDir)}` \n" , file = fp)

def dump_unchanged_files(fp = sys.stdout):
    global Candidates, BaseDir
    unchanged_files= [c for c in Candidates.values() if c.get_total_changes() == 0]

    print(f"""
## Unchanged Files
          
Path is relative to `{BaseDir}`

Number of unchanged files: {len(unchanged_files)}

          """, file = fp)
    
    for i, c in enumerate(unchanged_files, start=1):
        print(f"{i}. `{c.get_relative_path(BaseDir)}` \n" , file = fp)
        for o in c.others:
            print(f"    - `{o.get_relative_path(BaseDir)}` \n" , file = fp)

def dump_unique_files(fp = sys.stdout):
    unique_files =[c for c in Candidates.values() if len(c.others) == 0]
    print(f"""
## Unique Files

Path is relative to `{BaseDir}`
          
Number of Unique files: {len(unique_files)}

          """, file = fp)
    for i, c in enumerate(unique_files, start=1):
        print(f"{i}. `{c.get_relative_path(BaseDir)}`", file = fp)

def dump_candidates(outfile):
    with open(outfile, "w", encoding="utf-8") as f:
        dump_overview(f)
        dump_derived_files(f)
        dump_unchanged_files(f) 
        dump_unique_files(f)
    print(f"Created file: {outfile}")

def barf_and_exit(retcode, diag = None):
    if diag:
        print(diag)
    print(__doc__)
    sys.exit(retcode)

# == main ==
def main():
    global Candidates, BaseDir, RefDir, OutFile, FileExtensions, VerboseReport

    try:        
        opts, args = getopt.getopt(sys.argv[1:], "b:r:o:vh" )
    except Exception as e:
        barf_and_exit(-1, f"Error: {e}")

    for o,v in opts:
        if o == "-b":
            BaseDir = Path(v)
        elif o == "-r":
            RefDir = Path(v)
        elif o == "-o":
            OutFile = Path(v)
        elif o == "-v":
            VerboseReport += 1
        elif o == "-h":
            barf_and_exit(0)

    if (BaseDir == None) or (RefDir == None):
        barf_and_exit(-2, "Error: Both -r and -b options are mandatory")

    # 1) find all files in RefDir and populate Candidates
    get_ref_list(RefDir, FileExtensions)

    # 2) scan BaseDir and update candidate entries with duplicates
    #    if a file is found that is not yet in Candidates it is added
    #    with extra=1
    assign_duplicates(BaseDir, FileExtensions)
    
    # 3) calculate all diffs for all files in Candites 
    Update_derived_files()
    
    # 4) write results to file
    dump_candidates(OutFile)

if __name__ == "__main__":
    main()