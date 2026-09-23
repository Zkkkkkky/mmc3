from pathlib import Path

import numpy as np
from PIL import Image

root = Path(r"D:\GIT\mmc3\output\verification")
video_dir = root / "v56-user-video-20260924-001241" / "native-counter-960"
video_paths = sorted(video_dir.glob("frame-*.png"))
video = np.stack([np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)[8:232] for path in video_paths])

for emu_frame in range(300, 361):
    path = root / f"user-full-trace-v56-{emu_frame:03d}.png"
    reference = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    mse = np.mean((video - reference) ** 2, axis=(1, 2, 3))
    best = int(np.argmin(mse))
    if emu_frame in (324, 326, 328, 330, 332, 334, 336, 338, 340, 342, 344):
        print(f"emu={emu_frame} video={video_paths[best].name} mse={mse[best]:.2f}")
