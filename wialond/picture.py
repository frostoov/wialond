from subprocess import run, PIPE
from time import time


def take_picture(path, trasport):
    command = [
        'ffmpeg', '-rtsp_transport', trasport, '-i', path,
        '-vframes', '1', '-r', '1', '-f', 'singlejpeg', 'pipe:1'
    ]
    result = run(command, stdout=PIPE, stderr=PIPE)
    result.check_returncode()
    return time(), result.stdout
