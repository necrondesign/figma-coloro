# -*- coding: utf-8 -*-
"""Запускает scan.py отдельной сессией, чтобы процесс пережил завершение вызова."""
import os, sys
B = os.path.dirname(os.path.abspath(__file__))
keys = open(B + "/w%s.txt" % sys.argv[1]).read().split()
if not keys:
    print("поток %s пуст" % sys.argv[1]); sys.exit(0)
pid = os.fork()
if pid == 0:
    os.setsid()
    log = open(B + "/log%s.txt" % sys.argv[1], "w")
    os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
    os.close(0)
    os.execvp("python3", ["python3", B + "/scan.py"] + keys)
print("поток %s -> pid %d, файлов %d" % (sys.argv[1], pid, len(keys)))
