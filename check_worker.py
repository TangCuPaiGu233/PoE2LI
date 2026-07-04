with open('backend/app/tasks/worker.py', 'rb') as f:
    data = f.read(120)
print(repr(data))
