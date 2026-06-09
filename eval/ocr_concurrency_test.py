import asyncio, time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup_env  # noqa: F401  设置 backend 路径 + chdir
from app.services.video import extract_keyframes
from app.services.ocr import ocr_extract_markdown, is_ocr_configured


async def main():
    print('ocr configured:', await is_ocr_configured(), flush=True)
    vp = Path('/root/datamind/demo_samples_phase2/input/task_6/context/video/briefing.mp4')
    frames = extract_keyframes(vp)
    print('frames:', len(frames), flush=True)
    t0 = time.time()
    r = await ocr_extract_markdown(frames[0])
    print(f'SINGLE: {time.time()-t0:.0f}s ok={bool(r)}', flush=True)
    t0 = time.time()
    rs = await asyncio.gather(*[ocr_extract_markdown(f) for f in frames[1:4]], return_exceptions=True)
    ok = sum(1 for x in rs if isinstance(x, str) and x)
    print(f'CONCURRENT 3: {time.time()-t0:.0f}s ok={ok}/3', flush=True)
    import shutil
    shutil.rmtree(frames[0].parent, ignore_errors=True)


asyncio.run(main())
print('DONE', flush=True)
