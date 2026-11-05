import sys
sys.path.insert(0, r"L:\dev\Trim")
from app.ffmpeg_tools import copy_compatibility as c
print("h264/mxf:", c({"type": "video", "codec": "h264"}, "mxf"))
print("aac/mxf:", c({"type": "audio", "codec": "aac"}, "mxf"))
print("pcm/mxf:", c({"type": "audio", "codec": "pcm_s16le"}, "mxf"))
print("mpeg2/mxf:", c({"type": "video", "codec": "mpeg2video"}, "mxf"))
import app.main
print("import ok")
