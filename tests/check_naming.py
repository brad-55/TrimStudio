import sys
sys.path.insert(0, r"L:\dev\Trim")
from app.exports import time_tag_short, export_tags, output_path_for
print(time_tag_short(0), time_tag_short(2_000_000), time_tag_short(65_000_000), time_tag_short(3_723_500_000), time_tag_short(2_500_000))
print(export_tags({"mode": "lossless"}, 0, 2_000_000))
print(export_tags({"mode": "reencode", "encoder": "libx265", "videoBitrate": 1500, "lut": "x.cube", "stabilize": True, "crop": {"w": 320, "h": 180, "x": 0, "y": 0}}, 10_000_000, 20_000_000))
src = {"path": r"L:\dev\Trim\data\test\src_h264.mp4"}
print(str(output_path_for(src, 0, 2_000_000, "mp4", None, True, {"mode": "lossless"})).split("\\")[-1])
print(str(output_path_for(src, 10_000_000, 20_000_000, "mp4", None, True, {"mode": "reencode", "encoder": "libx265", "videoBitrate": 1500})).split("\\")[-1])
