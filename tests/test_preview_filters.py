"""Unit tests for the preview audio filter graph (no ffmpeg needed).

These pin the sign/units rules from docs/PLAN_PREVIEW_PROXY.md: a positive shift must be
an adelay in milliseconds, a negative one an atrim start in seconds, and every mode must
end in the fixed-length stage so the audio cannot be longer or shorter than the video.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.preview import IMPL, _audio_filter  # noqa: E402

fails = 0


def check(label, cond, detail=""):
    global fails
    print(("OK   " if cond else "FAIL ") + label + ("" if cond else "  " + str(detail)))
    if not cond:
        fails += 1


D = 12.0
# Intentional cache-version gate: bump IMPL whenever the baked graph semantics change.
check("preview cache: addedStart semantics invalidate old cached media", IMPL == "preview-v16", IMPL)
graph = _audio_filter(0.5, 0.0, D, 48000, True, False)
check("single: positive shift uses adelay in ms", "adelay=500:all=1" in graph, graph)
check("single: no atrim start for a delay", "atrim=start=" not in graph, graph)
check("single: fixed length stage is present", "apad=whole_dur=12.000000" in graph and "atrim=end=12.000000" in graph, graph)
check("single: labelled output", "[aout]" in graph, graph)

graph = _audio_filter(-0.5, 0.0, D, 48000, True, False)
check("single: negative shift uses atrim start in seconds", "atrim=start=0.500000" in graph, graph)
check("single: negative shift does not use adelay", "adelay=" not in graph, graph)
check("single: PTS is re-zeroed at the end (after the trim)", graph.rstrip().endswith("asetpts=PTS-STARTPTS[aout]"), graph)

graph = _audio_filter(0.0, 0.0, D, 48000, True, False)
check("single: zero shift touches neither adelay nor trim", "adelay=" not in graph and "atrim=start=" not in graph, graph)

graph = _audio_filter(0.5, 0.25, D, 48000, True, True)
check("mix: both inputs are labelled and fed to amix",
      "[ao][ad]amix=inputs=2:normalize=0:duration=first[am]" in graph, graph)
check("mix: the mixed stream also gets the fixed length stage", "[am]apad=whole_dur=12.000000" in graph, graph)
check("mix: added track gets its own delay", "adelay=250:all=1" in graph, graph)

graph = _audio_filter(0.0, 0.0, D, 48000, False, True)
check("added only: uses input 1", "[1:a:0]" in graph and "[2:a:0]" not in graph, graph)
check("added only: still ends at the fixed length", "apad=whole_dur=12.000000" in graph, graph)

check("no audio at all returns nothing", _audio_filter(0.0, 0.0, D, 48000, False, False) is None)

# addedStartMs is a skip INSIDE the added file, not a timeline delay.
graph = _audio_filter(0.5, 0.2, D, 48000, True, True, 1.0)
check("added start: trims the added input by addedStartMs", "atrim=start=1.000000" in graph, graph)
check("added start: the delay is only the shift (not start+shift)", "adelay=200:all=1" in graph, graph)
check("added start: no start+shift sum is delayed", "adelay=1200:all=1" not in graph, graph)
check("added start: both chains are normalised to the interval",
      graph.count("apad=whole_dur=12.000000") == 3, graph)

graph = _audio_filter(0.0, -0.2, D, 48000, True, True, 0.5)
check("negative added shift: extra head cut = start + |shift|", "atrim=start=0.700000" in graph, graph)
check("negative added shift: never an adelay", "adelay=" not in graph, graph)

graph = _audio_filter(0.0, 0.2, D, 48000, False, True, 0.5)
check("added-only start: input 1 is trimmed", "[1:a:0]atrim=start=0.500000" in graph, graph)

print("RESULT: " + ("FAIL(%d)" % fails if fails else "OK"))
sys.exit(1 if fails else 0)
