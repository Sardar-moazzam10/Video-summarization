with open("backend/services/semantic_segmenter.py", "r") as f:
    lines = f.readlines()
with open("backend/services/semantic_segmenter.py", "w") as f:
    skip = False
    for line in lines:
        if 'print("Encoding' in line: continue
        f.write(line)
