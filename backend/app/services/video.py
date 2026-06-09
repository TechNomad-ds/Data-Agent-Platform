"""视频关键帧提取服务

针对"幻灯片放映"型视频（briefing.mp4 这类）：画面高度冗余，同一张幻灯片
连续上百帧都一样，真正的信息只有翻页后的那几张静态画面。所以不逐帧处理，
而是把视频拆回成"几张代表性幻灯片图片"，再交给现有 OCR 管线解析成文字。

策略：
1. 用 imageio-ffmpeg 自带的 ffmpeg 二进制按固定间隔密集抽帧（候选帧）。
2. Pillow 感知哈希（dHash）对候选帧去重，相邻近似帧只保留第一张
   → 一张幻灯片无论用硬切还是淡入淡出过渡，都收敛成一帧。

之所以用"密集抽帧 + 哈希去重"而非 ffmpeg 的 scene 检测：幻灯片过渡方式
多样（硬切 / 淡入淡出 / 渐变），淡入淡出的逐帧差分很小，scene 检测会整段
漏掉；哈希去重对过渡方式不敏感，是更稳的主力。

依赖（imageio-ffmpeg / Pillow）缺失或解码异常时返回空列表，调用方据此降级。
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("video")

# 密集抽帧间隔（秒）：越小越不会漏掉短暂出现的幻灯片，但候选帧更多。
_SAMPLE_INTERVAL = 2.0
# 关键帧数上限，避免超长视频把下游远程 OCR 打爆（每帧一次提交+轮询）。
_MAX_KEYFRAMES = 30
# dHash 汉明距离阈值，<= 此值视为同一张幻灯片。
_PHASH_DISTANCE = 6
# ffmpeg 解码整体超时（秒）。
_FFMPEG_TIMEOUT = 180


def _ffmpeg_exe() -> Optional[str]:
    """获取 imageio-ffmpeg 自带的 ffmpeg 二进制路径，缺失返回 None。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        logger.warning(f"imageio-ffmpeg 不可用: {e}")
        return None


def probe_metadata(video_path: Path) -> dict:
    """用 ffmpeg 读取视频基础元数据（时长/分辨率）。失败返回空 dict。

    imageio-ffmpeg 只带 ffmpeg（不带 ffprobe），所以从 ffmpeg 的 stderr 解析。
    """
    exe = _ffmpeg_exe()
    if not exe:
        return {}
    try:
        # ffmpeg -i 不指定输出会报错并把流信息打到 stderr，正常现象。
        proc = subprocess.run(
            [exe, "-i", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        stderr = proc.stderr
        meta: dict = {}
        import re
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", stderr)
        if m:
            h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            meta["duration_seconds"] = round(h * 3600 + mnt * 60 + s, 1)
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", stderr)
        if m:
            meta["width"] = int(m.group(1))
            meta["height"] = int(m.group(2))
        return meta
    except Exception as e:
        logger.warning(f"视频元数据探测失败 {video_path.name}: {e}")
        return {}


def _dhash(image, hash_size: int = 8) -> int:
    """感知哈希（difference hash）：缩放成 9x8 灰度，比较相邻像素生成 64 位整数。"""
    img = image.convert("L").resize((hash_size + 1, hash_size), )
    bits = 0
    idx = 0
    pixels = list(img.getdata())
    w = hash_size + 1
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * w + col]
            right = pixels[row * w + col + 1]
            bits |= (1 << idx) if left > right else 0
            idx += 1
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def extract_keyframes(video_path: Path, work_dir: Optional[Path] = None) -> List[Path]:
    """提取去重后的关键帧（每张幻灯片一帧），返回 PNG 路径列表。

    密集间隔抽帧 → dHash 去重 → 截到上限。
    失败 / 依赖缺失 / 无帧 → 返回空列表。临时帧写入 work_dir（默认系统临时目录），
    调用方负责清理。
    """
    exe = _ffmpeg_exe()
    if not exe:
        return []
    if not video_path.exists():
        return []

    out_dir = work_dir or Path(tempfile.mkdtemp(prefix="vframes_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%04d.png")

    # 按固定间隔抽帧（fps=1/interval）；vsync vfr 避免补帧。
    cmd = [
        exe, "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps=1/{_SAMPLE_INTERVAL}",
        "-vsync", "vfr",
        pattern,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    except Exception as e:
        logger.warning(f"ffmpeg 抽帧失败 {video_path.name}: {e}")
        return []

    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        logger.info(f"视频无可抽取帧 {video_path.name}")
        return []

    return _dedup_frames(frames)


def _dedup_frames(frames: List[Path]) -> List[Path]:
    """用 dHash 去重相邻相似帧（动画过渡/渐变产生的伪切换），并截到上限。"""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow 不可用，跳过关键帧去重")
        return frames[:_MAX_KEYFRAMES]

    kept: List[Path] = []
    hashes: List[int] = []
    for fp in frames:
        try:
            with Image.open(fp) as im:
                h = _dhash(im)
        except Exception:
            continue
        if any(_hamming(h, prev) <= _PHASH_DISTANCE for prev in hashes):
            # 与已保留帧近似 → 丢弃这张过渡/重复帧
            try:
                fp.unlink()
            except OSError:
                pass
            continue
        hashes.append(h)
        kept.append(fp)
        if len(kept) >= _MAX_KEYFRAMES:
            break
    return kept
