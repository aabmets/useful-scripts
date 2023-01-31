import subprocess

subprocess.run("coverage run -m pytest", shell=True)
subprocess.run("coverage html", shell=True)
subprocess.run("start \"\" \"htmlcov/index.html\"", shell=True)
