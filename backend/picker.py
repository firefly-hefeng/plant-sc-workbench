import sys
from tkinter import Tk, filedialog
if __name__=="__main__":
    root=Tk();root.withdraw();root.attributes("-topmost",True)
    try:
        path=filedialog.askdirectory(parent=root) if sys.argv[1]=="directory" else filedialog.askopenfilename(parent=root)
        sys.stdout.buffer.write(path.encode("utf-8"))
    finally:root.destroy()

