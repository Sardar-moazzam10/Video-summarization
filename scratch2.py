import ast
with open("backend/api/merge.py") as f:
    code = f.read()
tree = ast.parse(code)
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "target_words":
                print(f"Line {node.lineno}: target_words = ...")
