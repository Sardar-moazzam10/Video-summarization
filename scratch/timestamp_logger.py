import sys
import time
import datetime
import subprocess

logfile = "/home/weiblocks/.gemini/antigravity/brain/5ebb2f15-01eb-460a-8745-7ad1f75878ef/.system_generated/tasks/task-693.log"
out_file = open("scratch/timestamped_backend.log", "w")

p = subprocess.Popen(["tail", "-f", logfile], stdout=subprocess.PIPE, text=True)

try:
    for line in iter(p.stdout.readline, ''):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        out_file.write(f"[{ts}] {line}")
        out_file.flush()
except KeyboardInterrupt:
    pass
