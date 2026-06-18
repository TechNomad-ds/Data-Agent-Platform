"""数据预处理服务 - 文件上传后自动分析生成数据画像"""
import asyncio
import uuid
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_session_factory
from app.models.file import File
from app.models.data_profile import DataProfile
from app.services.chunking import greedy_chunk
from app.services import embedding as embed_svc

_LIMITERS: dict[str, asyncio.Semaphore] = {}


def _limiter_limit(kind: str) -> int:
    return {
        "preprocessing": settings.max_preprocessing_tasks,
        "embedding": settings.max_embedding_tasks,
        "ocr": settings.max_ocr_tasks,
        "graph": settings.max_graph_tasks,
    }.get(kind, 1)


def _get_limiter(kind: str) -> asyncio.Semaphore:
    limiter = _LIMITERS.get(kind)
    if limiter is None:
        limiter = asyncio.Semaphore(max(1, _limiter_limit(kind)))
        _LIMITERS[kind] = limiter
    return limiter


async def run_limited(kind: str, awaitable):
    """限制进程内重任务并发，避免上传/嵌入/OCR 抢占 API 进程资源。"""
    async with _get_limiter(kind):
        return await awaitable


async def preprocess_file_limited(file_id: uuid.UUID, data_space_id: uuid.UUID) -> Dict[str, Any]:
    return await run_limited("preprocessing", preprocess_file(file_id, data_space_id))


async def preprocess_file(file_id: uuid.UUID, data_space_id: uuid.UUID) -> Dict[str, Any]:
    """预处理单个文件，生成数据画像。向量索引在后台异步完成，不阻塞状态。"""
    async with get_session_factory()() as db:
        result = await db.execute(select(File).where(File.id == file_id))
        file = result.scalar_one_or_none()
        if not file:
            return {"error": "文件不存在"}

        file_path = Path(settings.storage_root) / file.storage_path
        if not file_path.exists():
            return {"error": "文件不在磁盘上"}

        ext = file.file_type.lower()

        try:
            if ext in ("csv", "tsv", "xlsx", "xls", "json", "jsonl", "parquet", "feather", "dta", "sav", "sas7bdat"):
                profile_data = _profile_tabular(file_path, ext)
                profile_type = "tabular"
                asyncio.create_task(
                    run_limited(
                        "embedding",
                        _embed_tabular_background(profile_data, str(file_id), str(data_space_id), file.filename),
                    )
                )
            elif ext in ("sqlite", "db", "sqlite3"):
                profile_data = _profile_sqlite(file_path)
                profile_type = "database"
            elif ext in ("txt", "md", "py", "sql", "html", "xml", "yaml", "yml", "log", "r", "ipynb"):
                profile_data = _profile_text_fast(file_path)
                profile_type = "text"
                asyncio.create_task(
                    run_limited(
                        "embedding",
                        _embed_text_background(file_path, str(file_id), str(data_space_id), file.filename),
                    )
                )
            elif ext in ("pdf", "docx", "pptx", "ppt"):
                profile_data = _profile_document_fast(file_path, ext)
                profile_type = "document"
                if ext != "ppt":
                    asyncio.create_task(
                        run_limited(
                            "ocr",
                            _document_ocr_pipeline(file_path, ext, str(file_id), str(data_space_id), file.filename),
                        )
                    )
            elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp"):
                profile_data = _profile_image(file_path)
                profile_type = "image"
                asyncio.create_task(
                    run_limited(
                        "ocr",
                        _image_ocr_pipeline(file_path, str(file_id), str(data_space_id), file.filename),
                    )
                )
            elif ext in ("mp4", "mov", "avi", "mkv", "webm"):
                profile_data = _profile_video(file_path)
                profile_type = "video"
                asyncio.create_task(
                    run_limited(
                        "ocr",
                        _video_ocr_pipeline(file_path, str(file_id), str(data_space_id), file.filename),
                    )
                )
            else:
                profile_data = {"info": f"文件类型: {ext}", "file_size": file.file_size}
                profile_type = "other"

            existing = await db.execute(
                select(DataProfile).where(
                    DataProfile.file_id == file_id,
                    DataProfile.data_space_id == data_space_id,
                )
            )
            profile = existing.scalar_one_or_none()
            if profile:
                profile.profile_data = profile_data
                profile.profile_type = profile_type
                profile.status = "ready"
                profile.error_message = None
            else:
                profile = DataProfile(
                    file_id=file_id,
                    data_space_id=data_space_id,
                    profile_type=profile_type,
                    profile_data=profile_data,
                    status="ready",
                )
                db.add(profile)

            await db.commit()
            return profile_data

        except Exception as e:
            existing = await db.execute(
                select(DataProfile).where(
                    DataProfile.file_id == file_id,
                    DataProfile.data_space_id == data_space_id,
                )
            )
            profile = existing.scalar_one_or_none()
            if profile:
                profile.status = "error"
                profile.error_message = str(e)
            else:
                db.add(DataProfile(
                    file_id=file_id,
                    data_space_id=data_space_id,
                    profile_type="tabular",
                    profile_data={},
                    status="error",
                    error_message=str(e),
                ))
            await db.commit()
            return {"error": str(e)}


async def recover_unprocessed_files() -> int:
    """启动时自愈：补跑所有缺失画像的文件。

    后台预处理是 asyncio 任务，进程重启（uvicorn --reload / 崩溃 / 部署）会直接
    丢掉正在跑的任务，导致文件永远停在"无画像"状态、前端进度卡死。这里在每次启动时
    扫描出所有「已关联到数据空间、但没有 ready 画像」的文件，逐个补跑。
    error 状态的也重试（可能是上次 bug 导致，修复后应能成功）。

    返回补跑的文件数。
    """
    import logging
    logger = logging.getLogger("preprocessing")
    from app.models.data_space import DataSpaceFile

    # 多 worker 场景下（gunicorn preload + N workers）每个 worker 都会在启动时调用本函数。
    # 用 Redis SET NX 抢一把全局锁，确保只有一个 worker 真正执行补跑，避免重复 preprocess
    # 同一批文件造成的 CPU/embedding 浪费与竞态。拿不到锁的 worker 直接跳过。
    # 锁带过期时间兜底，防止持锁 worker 崩溃后永久占用。
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        got_lock = await redis.set("lock:recover_unprocessed_files", "1", nx=True, ex=1800)
        if not got_lock:
            logger.info("启动自愈：已有其它 worker 在执行，本 worker 跳过")
            return 0
    except Exception as e:
        # Redis 不可用时不阻塞启动；退化为可能多 worker 重复跑（功能仍正确，幂等）
        logger.warning(f"启动自愈：获取分布式锁失败，继续执行（可能重复）: {e}")

    async with get_session_factory()() as db:
        # 所有 (file_id, data_space_id) 关联
        link_rows = await db.execute(
            select(DataSpaceFile.file_id, DataSpaceFile.data_space_id)
        )
        links = link_rows.all()

        # 已 ready 的 (file_id, data_space_id) 集合
        ready_rows = await db.execute(
            select(DataProfile.file_id, DataProfile.data_space_id).where(
                DataProfile.status == "ready"
            )
        )
        ready_set = {(r[0], r[1]) for r in ready_rows.all()}

    pending = [(fid, sid) for fid, sid in links if (fid, sid) not in ready_set]
    if not pending:
        return 0

    logger.info(f"启动自愈：检测到 {len(pending)} 个文件缺少画像，开始补跑")
    done = 0
    for fid, sid in pending:
        try:
            await preprocess_file(fid, sid)
            done += 1
        except Exception as e:
            logger.warning(f"自愈补跑文件 {fid} 失败: {e}")
    logger.info(f"启动自愈完成：补跑 {done}/{len(pending)} 个文件")
    return done


def _profile_tabular(file_path: Path, ext: str) -> Dict[str, Any]:
    """生成表格数据画像 - 支持多种格式"""
    if ext in ("xlsx", "xls"):
        from app.services.file_loader import load_excel_sheets
        sheets = load_excel_sheets(file_path, nrows=10000)
        sheet_profiles = []
        for sheet_name, df in sheets.items():
            if df.empty:
                continue
            sheet_profile = _profile_dataframe(df)
            sheet_profile["sheet_name"] = sheet_name
            sheet_profiles.append(sheet_profile)
        if not sheet_profiles:
            return {"error": f"无法加载 {ext} 格式文件"}

        profile = dict(sheet_profiles[0])
        profile.update({
            "workbook": True,
            "sheet_count": len(sheets),
            "loaded_sheet_count": len(sheet_profiles),
            "sheets": sheet_profiles,
        })
        return profile

    df = _load_tabular(file_path, ext)
    if df is None or df.empty:
        return {"error": f"无法加载 {ext} 格式文件"}
    return _profile_dataframe(df)


def _profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """生成单张 DataFrame 的画像。"""
    profile: Dict[str, Any] = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": [],
        "memory_usage_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
    }

    numeric_cols = []
    for col in df.columns:
        # 检测列是否含有不可哈希的嵌套值（dict/list），如 JSON 里的对象列
        has_unhashable = df[col].dropna().apply(lambda v: isinstance(v, (dict, list))).any()

        if has_unhashable:
            # 嵌套对象列：转成 JSON 字符串后再统计，避免 unhashable type 崩溃
            str_series = df[col].dropna().apply(
                lambda v: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)
            )
            col_info: Dict[str, Any] = {
                "name": col,
                "dtype": "object(nested)",
                "non_null_count": int(df[col].notna().sum()),
                "null_count": int(df[col].isna().sum()),
                "null_pct": round(float(df[col].isna().mean()) * 100, 1),
                "unique_count": int(str_series.nunique()),
            }
            col_info["sample_values"] = [s[:200] for s in str_series.head(5).tolist()]
            profile["columns"].append(col_info)
            continue

        col_info = {
            "name": col,
            "dtype": str(df[col].dtype),
            "non_null_count": int(df[col].notna().sum()),
            "null_count": int(df[col].isna().sum()),
            "null_pct": round(float(df[col].isna().mean()) * 100, 1),
            "unique_count": int(df[col].nunique()),
        }

        # 注意：布尔列在 pandas 里 is_numeric_dtype 也返回 True，但对布尔做
        # describe/分位数/IQR 异常值会触发 numpy "boolean subtract" 报错，且统计意义
        # 不大。这里显式排除布尔列，按类别列（top_values）处理。
        if pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_bool_dtype(df[col]):
            desc = df[col].describe()
            col_info["stats"] = {
                "mean": _safe_float(desc.get("mean")),
                "std": _safe_float(desc.get("std")),
                "min": _safe_float(desc.get("min")),
                "25%": _safe_float(desc.get("25%")),
                "50%": _safe_float(desc.get("50%")),
                "75%": _safe_float(desc.get("75%")),
                "max": _safe_float(desc.get("max")),
            }
            numeric_cols.append(col)
        else:
            top_values = df[col].value_counts().head(10)
            col_info["top_values"] = {str(k): int(v) for k, v in top_values.items()}

        col_info["sample_values"] = [str(v) for v in df[col].dropna().head(5).tolist()]
        profile["columns"].append(col_info)

    # Data quality metrics（duplicated 也需可哈希，含嵌套列时降级跳过）
    try:
        quality = {
            "duplicate_rows": int(df.duplicated().sum()),
            "duplicate_pct": round(float(df.duplicated().mean()) * 100, 1),
            "complete_rows": int((~df.isna().any(axis=1)).sum()),
            "complete_pct": round(float((~df.isna().any(axis=1)).mean()) * 100, 1),
        }
    except TypeError:
        quality = {
            "duplicate_rows": 0,
            "duplicate_pct": 0.0,
            "complete_rows": int((~df.isna().any(axis=1)).sum()),
            "complete_pct": round(float((~df.isna().any(axis=1)).mean()) * 100, 1),
        }

    # Outlier detection for numeric columns (IQR method)
    outlier_cols = []
    for col in numeric_cols[:10]:
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            outlier_count = int(((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum())
            if outlier_count > 0:
                outlier_cols.append({"column": col, "outlier_count": outlier_count, "outlier_pct": round(outlier_count / len(df) * 100, 1)})

    quality["outlier_columns"] = outlier_cols

    # Type suggestions
    type_suggestions = []
    for col in df.columns:
        if df[col].dtype == "object":
            non_null = df[col].dropna()
            if len(non_null) > 0:
                try:
                    pd.to_numeric(non_null.head(100))
                    type_suggestions.append({"column": col, "suggestion": "可转为数值类型"})
                    continue
                except (ValueError, TypeError):
                    pass
                try:
                    pd.to_datetime(non_null.head(100))
                    type_suggestions.append({"column": col, "suggestion": "可转为日期类型"})
                except (ValueError, TypeError):
                    pass

    quality["type_suggestions"] = type_suggestions
    profile["quality"] = quality

    if len(numeric_cols) >= 2 and len(numeric_cols) <= 20:
        corr = df[numeric_cols].corr()
        profile["correlations"] = {
            "columns": numeric_cols,
            "matrix": corr.fillna(0).values.tolist(),
        }

    return profile


def _profile_text_fast(file_path: Path) -> Dict[str, Any]:
    """快速生成文本文件画像（不做 embedding）"""
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.split("\n")
    return {
        "char_count": len(content),
        "line_count": len(lines),
        "word_count": len(content.split()),
        "preview": content[:500],
    }


async def _embed_tabular_background(
    profile_data: Dict[str, Any], file_id: str, data_space_id: str, filename: str
) -> None:
    """将表格文件的列信息和摘要嵌入为可搜索的文本块"""
    import logging
    logger = logging.getLogger("preprocessing")
    try:
        chunks = []
        profiles = profile_data.get("sheets") or [profile_data]
        summary_parts = []
        if profile_data.get("workbook"):
            summary_parts.append(f"Excel 文件 {filename}，共 {profile_data.get('sheet_count', len(profiles))} 个工作表。")

        for sheet_profile in profiles:
            columns = sheet_profile.get("columns", [])
            row_count = sheet_profile.get("row_count", 0)
            sheet_name = sheet_profile.get("sheet_name")
            col_names = [c["name"] for c in columns]
            prefix = f"工作表 {sheet_name}: " if sheet_name else ""
            summary = f"{prefix}共 {row_count} 行，{len(columns)} 列。列包括: {', '.join(col_names)}。"

            for c in columns:
                desc = f"列 {c['name']} (类型: {c['dtype']})"
                if c.get("stats"):
                    s = c["stats"]
                    desc += f"，均值 {s.get('mean', '?')}，范围 {s.get('min', '?')} ~ {s.get('max', '?')}"
                if c.get("top_values"):
                    top = list(c["top_values"].keys())[:5]
                    desc += f"，常见值: {', '.join(top)}"
                if c.get("sample_values"):
                    desc += f"，示例: {', '.join(c['sample_values'][:3])}"
                summary += " " + desc + "。"
            summary_parts.append(summary)

        summary = "\n".join(summary_parts)

        chunks.append({"text": summary, "start_char": 0, "end_char": len(summary)})
        await embed_svc.embed_chunks_async(data_space_id, chunks, file_id, filename)

        try:
            from app.services.retrieval import invalidate_cache
            invalidate_cache(data_space_id)
        except Exception:
            pass
        logger.info(f"表格嵌入完成: {filename}")
    except Exception as e:
        logger.error(f"表格嵌入失败 ({filename}): {e}", exc_info=True)


async def _embed_text_background(
    file_path: Path, file_id: str, data_space_id: str, filename: str
) -> None:
    """后台异步执行文本 embedding"""
    import logging
    logger = logging.getLogger("preprocessing")
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        chunks = greedy_chunk(content, max_size=1000, overlap=200)
        await embed_svc.embed_chunks_async(data_space_id, chunks, file_id, filename)
        try:
            from app.services.retrieval import invalidate_cache
            invalidate_cache(data_space_id)
        except Exception:
            pass
        logger.info(f"文本嵌入完成: {filename}, {len(chunks)} 个块")
    except Exception as e:
        logger.error(f"文本嵌入失败 ({filename}): {e}", exc_info=True)


def _profile_document_fast(file_path: Path, ext: str) -> Dict[str, Any]:
    """快速生成文档画像（不做 embedding）"""
    if ext == "ppt":
        return {
            "char_count": 0,
            "page_count": 0,
            "preview": "",
            "warning": "旧版 .ppt 暂不支持抽取文本，请转换为 .pptx 后上传以获得检索和问答效果",
        }

    from app.services.document_text import document_page_count, extract_document_text
    text = extract_document_text(file_path, ext)
    page_count = document_page_count(file_path, ext, text)

    return {
        "char_count": len(text),
        "page_count": page_count,
        "preview": text[:500],
    }


async def _document_ocr_pipeline(
    file_path: Path, ext: str, file_id: str, data_space_id: str, filename: str
) -> None:
    """文档处理流水线（单文件内顺序执行，避免嵌入竞态）：
    1. 本地 fitz/docx 抽文本并嵌入（立即可搜，保证基础可用）
    2. 若配置了 OCR，调用远程 API；成功则用 OCR Markdown 覆盖嵌入与画像
    OCR 不可用 / 失败 / 超时 → 保留本地抽取结果。
    """
    import logging
    logger = logging.getLogger("preprocessing")

    # ---- 1. 本地抽取 + 嵌入 ----
    local_text = ""
    try:
        from app.services.document_text import extract_document_text
        local_text = extract_document_text(file_path, ext)

        chunks = greedy_chunk(local_text, max_size=1000, overlap=200)
        await embed_svc.embed_chunks_async(data_space_id, chunks, file_id, filename)
        _invalidate_retrieval(data_space_id)
        logger.info(f"文档本地嵌入完成: {filename}, {len(chunks)} 个块")
    except Exception as e:
        logger.error(f"文档本地嵌入失败 ({filename}): {e}", exc_info=True)

    # ---- 2. OCR 覆盖（仅 PDF；docx 已是结构化文本，无需 OCR）----
    if ext != "pdf":
        return
    try:
        from app.services.ocr import is_ocr_configured, ocr_extract_markdown
        if not await is_ocr_configured():
            return
        md = await ocr_extract_markdown(file_path)
        if not md:
            return

        # 用 OCR 结果覆盖嵌入
        embed_svc.delete_file_embeddings(data_space_id, file_id)
        ocr_chunks = greedy_chunk(md, max_size=1000, overlap=200)
        await embed_svc.embed_chunks_async(data_space_id, ocr_chunks, file_id, filename)
        _invalidate_retrieval(data_space_id)

        # 更新画像：覆盖 preview / char_count，记录 OCR 全文供 read_file 使用
        await _update_profile_ocr(file_id, data_space_id, md)
        logger.info(f"文档 OCR 覆盖完成: {filename}, {len(ocr_chunks)} 个块")
    except Exception as e:
        logger.error(f"文档 OCR 处理失败 ({filename}): {e}", exc_info=True)


async def _image_ocr_pipeline(
    file_path: Path, file_id: str, data_space_id: str, filename: str
) -> None:
    """图片 OCR 流水线：本地无文本，直接尝试远程 OCR。
    成功则嵌入 OCR 文本并写入画像；失败/未配置则什么都不做（保留尺寸画像）。
    """
    import logging
    logger = logging.getLogger("preprocessing")
    try:
        from app.services.ocr import is_ocr_configured, ocr_extract_markdown
        if not await is_ocr_configured():
            return
        md = await ocr_extract_markdown(file_path)
        if not md:
            return

        chunks = greedy_chunk(md, max_size=1000, overlap=200)
        await embed_svc.embed_chunks_async(data_space_id, chunks, file_id, filename)
        _invalidate_retrieval(data_space_id)
        await _update_profile_ocr(file_id, data_space_id, md)
        logger.info(f"图片 OCR 完成: {filename}, {len(chunks)} 个块")
    except Exception as e:
        logger.error(f"图片 OCR 处理失败 ({filename}): {e}", exc_info=True)


def _profile_video(file_path: Path) -> Dict[str, Any]:
    """快速生成视频画像（不解码全片）：基础元数据 + 大小。OCR 全文后台补充。"""
    meta = {}
    try:
        from app.services.video import probe_metadata
        meta = probe_metadata(file_path)
    except Exception:
        pass
    return {
        "file_size_mb": round(file_path.stat().st_size / 1024 / 1024, 2),
        "duration_seconds": meta.get("duration_seconds"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "note": "幻灯片型视频，关键帧 OCR 文本在后台异步生成",
    }


async def _video_ocr_pipeline(
    file_path: Path, file_id: str, data_space_id: str, filename: str
) -> None:
    """视频处理流水线（幻灯片型）：
    1. 抽取去重后的关键帧（每张幻灯片一帧）
    2. 逐帧调用远程 OCR，拼成 "## 第 N 页" 的 Markdown
    3. chunk + embed + 写回画像，复用与图片/PDF 完全相同的下游
    依赖缺失 / 无帧 / OCR 未配置或全部失败 → 保留基础画像，不嵌入。
    """
    import logging
    import shutil
    logger = logging.getLogger("preprocessing")

    frames = []
    work_dir = None
    try:
        from app.services.video import extract_keyframes
        frames = extract_keyframes(file_path)
        if not frames:
            logger.info(f"视频无可用关键帧，跳过 OCR: {filename}")
            return
        work_dir = frames[0].parent

        from app.services.ocr import is_ocr_configured, ocr_extract_markdown
        if not await is_ocr_configured():
            logger.info(f"OCR 未配置，跳过视频 OCR: {filename}")
            return

        parts = []
        for i, frame in enumerate(frames, start=1):
            md = await ocr_extract_markdown(frame)
            if md and md.strip():
                parts.append(f"## 第 {i} 页\n\n{md.strip()}")

        full_md = "\n\n".join(parts).strip()
        if not full_md:
            logger.info(f"视频关键帧 OCR 结果为空: {filename}")
            return

        chunks = greedy_chunk(full_md, max_size=1000, overlap=200)
        await embed_svc.embed_chunks_async(data_space_id, chunks, file_id, filename)
        _invalidate_retrieval(data_space_id)
        await _update_profile_ocr(file_id, data_space_id, full_md)
        logger.info(f"视频 OCR 完成: {filename}, {len(frames)} 帧, {len(chunks)} 个块")
    except Exception as e:
        logger.error(f"视频 OCR 处理失败 ({filename}): {e}", exc_info=True)
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)


def _invalidate_retrieval(data_space_id: str) -> None:
    try:
        from app.services.retrieval import invalidate_cache
        invalidate_cache(data_space_id)
    except Exception:
        pass


async def _update_profile_ocr(file_id: str, data_space_id: str, md: str) -> None:
    """把 OCR Markdown 写回 DataProfile：更新 preview/char_count，存全文供 read_file。"""
    import uuid as _uuid
    try:
        async with get_session_factory()() as db:
            result = await db.execute(
                select(DataProfile).where(
                    DataProfile.file_id == _uuid.UUID(file_id),
                    DataProfile.data_space_id == _uuid.UUID(data_space_id),
                )
            )
            profile = result.scalar_one_or_none()
            if not profile:
                return
            data = dict(profile.profile_data or {})
            data["preview"] = md[:500]
            data["char_count"] = len(md)
            data["ocr_applied"] = True
            data["ocr_text"] = md[:20000]  # 截断存储，供 read_file 回退
            profile.profile_data = data
            profile.status = "ready"
            await db.commit()
    except Exception:
        import logging
        logging.getLogger("preprocessing").warning("写回 OCR 画像失败", exc_info=True)




def _load_json_df(file_path: Path) -> pd.DataFrame:
    content = file_path.read_text(encoding="utf-8")
    data = json.loads(content)
    if isinstance(data, list):
        return pd.DataFrame(data)
    elif isinstance(data, dict) and "records" in data:
        return pd.DataFrame(data["records"])
    elif isinstance(data, dict):
        return pd.DataFrame([data])
    return pd.DataFrame()


def _detect_encoding(file_path: Path) -> str:
    """检测文件编码"""
    try:
        import chardet
        raw = file_path.read_bytes()[:10000]
        result = chardet.detect(raw)
        return result.get("encoding", "utf-8") or "utf-8"
    except ImportError:
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1", "shift_jis"):
            try:
                file_path.read_text(encoding=enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "utf-8"


def _load_tabular(file_path: Path, ext: str) -> Optional[pd.DataFrame]:
    """加载各种格式的表格数据"""
    try:
        if ext == "csv":
            encoding = _detect_encoding(file_path)
            return pd.read_csv(file_path, encoding=encoding, nrows=10000, on_bad_lines="skip")
        elif ext == "tsv":
            encoding = _detect_encoding(file_path)
            return pd.read_csv(file_path, sep="\t", encoding=encoding, nrows=10000, on_bad_lines="skip")
        elif ext in ("xlsx", "xls"):
            return pd.read_excel(file_path, nrows=10000)
        elif ext == "json":
            return _load_json_df(file_path)
        elif ext == "jsonl":
            return pd.read_json(file_path, lines=True, nrows=10000)
        elif ext == "parquet":
            return pd.read_parquet(file_path).head(10000)
        elif ext == "feather":
            return pd.read_feather(file_path).head(10000)
        elif ext == "dta":
            return pd.read_stata(file_path)
        elif ext == "sav":
            return pd.read_spss(file_path)
        elif ext == "sas7bdat":
            return pd.read_sas(file_path)
    except ImportError as e:
        import logging
        logging.getLogger("preprocessing").warning(f"缺少依赖库，无法加载 {ext}: {e}")
        return None
    except Exception:
        return None
    return None


def _profile_sqlite(file_path: Path) -> Dict[str, Any]:
    """分析 SQLite 数据库文件"""
    import sqlite3
    conn = sqlite3.connect(str(file_path))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = []
        total_rows = 0
        for (table_name,) in cursor.fetchall():
            quoted = '"' + table_name.replace('"', '""') + '"'
            info_cursor = conn.execute(f"PRAGMA table_info({quoted})")
            columns = [{"name": row[1], "type": row[2], "nullable": not row[3]} for row in info_cursor.fetchall()]
            count_cursor = conn.execute(f"SELECT COUNT(*) FROM {quoted}")
            row_count = count_cursor.fetchone()[0]
            total_rows += row_count

            sample_cursor = conn.execute(f"SELECT * FROM {quoted} LIMIT 5")
            sample_rows = [list(row) for row in sample_cursor.fetchall()]

            tables.append({
                "name": table_name,
                "columns": columns,
                "row_count": row_count,
                "sample_rows": sample_rows,
            })

        return {
            "database_type": "sqlite",
            "table_count": len(tables),
            "total_rows": total_rows,
            "tables": tables,
            "file_size_mb": round(file_path.stat().st_size / 1024 / 1024, 2),
        }
    finally:
        conn.close()


def _profile_image(file_path: Path) -> Dict[str, Any]:
    """分析图片文件"""
    try:
        from PIL import Image
        img = Image.open(file_path)
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "file_size_kb": round(file_path.stat().st_size / 1024, 1),
        }
    except ImportError:
        return {
            "file_size_kb": round(file_path.stat().st_size / 1024, 1),
            "note": "需要安装 Pillow 库以获取图片详细信息",
        }
    except Exception as e:
        return {"error": str(e)}


def _safe_float(val) -> Optional[float]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return round(float(val), 4)


async def get_space_profile(data_space_id: uuid.UUID) -> Dict[str, Any]:
    """获取数据空间的聚合画像"""
    async with get_session_factory()() as db:
        result = await db.execute(
            select(DataProfile).where(
                DataProfile.data_space_id == data_space_id,
                DataProfile.status == "ready",
            )
        )
        profiles = result.scalars().all()

    if not profiles:
        return {"status": "empty", "files": []}

    files_summary = []
    total_rows = 0
    total_columns = 0

    for p in profiles:
        summary = {
            "file_id": str(p.file_id),
            "profile_type": p.profile_type,
        }
        if p.profile_type == "tabular":
            summary["row_count"] = p.profile_data.get("row_count", 0)
            summary["column_count"] = p.profile_data.get("column_count", 0)
            summary["columns"] = [c["name"] for c in p.profile_data.get("columns", [])]
            total_rows += summary["row_count"]
            total_columns += summary["column_count"]
        elif p.profile_type in ("text", "document", "video"):
            summary["char_count"] = p.profile_data.get("char_count", 0)
            summary["chunk_count"] = p.profile_data.get("chunk_count", 0)

        files_summary.append(summary)

    return {
        "status": "ready",
        "file_count": len(profiles),
        "total_rows": total_rows,
        "total_columns": total_columns,
        "files": files_summary,
    }
