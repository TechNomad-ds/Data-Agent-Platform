"""加固版代码沙箱：隔离子进程 + 资源限额 + 受限命名空间 + 文件路径校验。

定位：这是纵深防御的【第一层】，用于显著抬高在进程内执行用户代码的攻击成本。
它【不能】替代操作系统级隔离——生产环境仍必须以非 root 用户运行后端，
理想情况下进一步用容器隔离 execute 工具。本模块解决的是：
  1. 真超时（子进程可被强杀，而非线程跑飞）
  2. CPU / 内存 / 文件大小 / 进程数 限额（防 DoS 与 fork 炸弹）
  3. 关闭已知绕过路径（pathlib / io.open / pickle RCE / URL 读 / 任意路径读）
"""
import ast
import multiprocessing
import os

# 允许 import 的模块白名单。
# 刻意移除了 pathlib、io、struct、os、sys 等可直接触达文件系统/解释器的模块。
ALLOWED_MODULES = {
    "pandas", "numpy", "json", "math", "statistics", "collections",
    "itertools", "functools", "re", "datetime", "csv", "decimal",
    "fractions", "operator", "string", "textwrap", "random",
}

# 禁止访问的属性名：解释器内部遍历入口（部分非 dunder）+ 高危库方法。
BLOCKED_ATTRS = {
    # 通过对象遍历回到内建/帧的经典逃逸路径
    "mro", "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame",
    "f_globals", "f_locals", "f_back", "f_builtins", "f_code",
    "tb_frame", "tb_next", "func_globals", "func_code",
    # 直接的系统访问
    "system", "popen", "fork", "spawn", "execv", "execve",
    # pandas / numpy 的反序列化与外部 I/O（RCE / SSRF / 任意读）
    "read_pickle", "to_pickle", "read_html", "read_xml", "read_sql",
    "read_sql_query", "read_sql_table", "read_gbq", "read_clipboard",
    "read_stata", "read_sas", "read_spss", "eval",
    "load", "loads", "save", "fromfile", "tofile", "memmap", "DataSource",
}

# 资源限额默认值
DEFAULT_CPU_SECONDS = 10           # CPU 时间上限
DEFAULT_MEM_BYTES = 1024 * 1024 * 1024   # 地址空间上限 1GB
DEFAULT_FSIZE_BYTES = 50 * 1024 * 1024   # 单文件写入上限 50MB（防写盘 DoS）
DEFAULT_WALL_TIMEOUT = 30          # 墙钟超时（秒），到点强杀子进程


class SandboxViolation(Exception):
    """静态检查阶段发现的违规，附带给模型/用户看的提示。"""


def static_check(code: str, mode: str = "exec") -> None:
    """AST 静态检查。发现违规抛 SandboxViolation。

    这是第一道闸：在代码进入子进程执行前，先拦掉明显的危险写法。
    它不是充分的（运行期还有动态构造），但能挡掉绝大多数直接攻击。
    """
    try:
        tree = ast.parse(code, mode=mode)
    except SyntaxError:
        # eval 模式失败时调用方会改用 exec 模式重试
        tree = ast.parse(code, mode="exec")

    for node in ast.walk(tree):
        # import 白名单
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ALLOWED_MODULES:
                    raise SandboxViolation(f"安全限制：不允许导入 '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top not in ALLOWED_MODULES:
                raise SandboxViolation(f"安全限制：不允许导入 '{node.module}'")

        # 属性访问：拦 dunder + 已知高危属性/方法名
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SandboxViolation(f"安全限制：不允许访问 dunder 属性 '{node.attr}'")
            if node.attr in BLOCKED_ATTRS:
                raise SandboxViolation(f"安全限制：不允许访问属性/方法 '{node.attr}'")

        # 函数调用：拦危险内建名
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fid = node.func.id
            if fid == "open":
                raise SandboxViolation(
                    "安全限制：沙箱禁止 open()。读取数据请用 read_file 工具或已加载的 df 变量。"
                )
            if fid in ("exec", "eval", "compile", "input", "breakpoint",
                       "globals", "locals", "vars", "dir",
                       "getattr", "setattr", "delattr", "__import__",
                       "memoryview", "help", "exit", "quit"):
                raise SandboxViolation(f"安全限制：不允许调用 '{fid}'")

        # 拦下标名形如 attacker["__globals__"] 的字符串绕过
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.startswith("__") and v.endswith("__") and len(v) > 4:
                raise SandboxViolation(f"安全限制：不允许引用 '{v}'")


# 安全内建：只暴露纯计算所需，绝不含 open/exec/eval/__import__ 等
_SAFE_BUILTIN_NAMES = (
    "abs all any ascii bin bool bytearray bytes callable chr complex dict "
    "divmod enumerate filter float format frozenset hash hex int isinstance "
    "issubclass iter len list map max min next object oct ord pow print range "
    "repr reversed round set slice sorted str sum tuple type zip "
    "True False None"
).split()

_SAFE_EXCEPTIONS = (
    "Exception ValueError TypeError KeyError IndexError ZeroDivisionError "
    "ArithmeticError AttributeError StopIteration RuntimeError NotImplementedError "
    "OverflowError FloatingPointError LookupError AssertionError"
).split()


def _build_safe_builtins():
    import builtins as _b
    safe = {}
    for name in _SAFE_BUILTIN_NAMES:
        if hasattr(_b, name):
            safe[name] = getattr(_b, name)
    for name in _SAFE_EXCEPTIONS:
        if hasattr(_b, name):
            safe[name] = getattr(_b, name)

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        top = name.split(".")[0]
        if top not in ALLOWED_MODULES:
            raise ImportError(f"安全限制：不允许导入 '{name}'")
        return __import__(name, globals, locals, fromlist, level)

    safe["__import__"] = _safe_import
    return safe


def _apply_rlimits(cpu_seconds, mem_bytes, fsize_bytes):
    """在子进程内施加 OS 级资源限额（仅 POSIX）。"""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        # 禁止 fork/clone 新进程：防 fork 炸弹与起子进程绕过
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        except (ValueError, OSError):
            pass
        # 不产生 core dump
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        # 拿不到 resource（非 POSIX）时静默跳过，靠墙钟超时兜底
        pass


def _install_fs_guard(pd, np, preload):
    """运行期文件访问守卫：把 pandas/numpy 的 reader 限制在白名单路径内。

    黑名单属性拦不住合法 API（如 pd.read_csv('/任意路径')），因此在运行期
    包装这些 reader：只允许读取 preload 里登记的、数据空间授权的文件路径，
    并拒绝 URL（防 SSRF）。
    """
    import os as _os
    allowed = set()
    for _k, (_kind, p) in (preload or {}).items():
        try:
            allowed.add(_os.path.realpath(p))
        except Exception:
            pass

    def _check(path):
        if not isinstance(path, str):
            raise PermissionError("安全限制：文件参数必须是已授权的数据文件路径")
        low = path.lower()
        if "://" in low or low.startswith(("http", "ftp", "file:", "s3:", "gs:")):
            raise PermissionError("安全限制：沙箱禁止通过 URL 读取数据")
        rp = _os.path.realpath(path)
        if rp not in allowed:
            raise PermissionError(
                "安全限制：只能访问当前数据空间已加载的文件；其它文件请用 read_file 工具。"
            )
        return path

    def _wrap(orig):
        def guarded(filepath_or_buffer, *a, **kw):
            _check(filepath_or_buffer)
            return orig(filepath_or_buffer, *a, **kw)
        return guarded

    for fn in ("read_csv", "read_excel", "read_json", "read_table",
               "read_parquet", "read_feather", "read_orc", "read_fwf"):
        if hasattr(pd, fn):
            setattr(pd, fn, _wrap(getattr(pd, fn)))

    def _np_guard(orig):
        def guarded(file, *a, **kw):
            _check(file)
            return orig(file, *a, **kw)
        return guarded

    for fn in ("loadtxt", "genfromtxt"):
        if hasattr(np, fn):
            setattr(np, fn, _np_guard(getattr(np, fn)))


def _load_json_df(pd, path):
    """在沙箱内加载 JSON 为 DataFrame，与 file_loader._load_json 行为一致。

    很多真实数据是嵌套结构（如 {"table": ..., "records": [...]}），直接
    pd.read_json 会把它读成一行两列的怪表，导致后续按业务列名取数全部 KeyError。
    path 来自 preload（已授权的数据空间文件），属可信预加载，故可直接读取。
    """
    import json as _json
    with open(path, "r", encoding="utf-8") as _fh:
        data = _json.load(_fh)
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, dict):
        # 取第一个 list 型字段作为记录集（兼容 records / data / rows 等命名）
        for key in ("records", "data", "rows", "items"):
            if isinstance(data.get(key), list):
                return pd.DataFrame(data[key])
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return pd.DataFrame(v)
        return pd.DataFrame([data])
    return pd.read_json(path)


def _child_entry(code, preload, cpu_seconds, mem_bytes, fsize_bytes, conn):
    """子进程入口：施加限额 → 构造受限命名空间 → exec → 回传 stdout/错误。

    preload: {变量名: ("csv"|"excel"|"json", 文件绝对路径)} —— 由子进程自己加载，
    确保数据加载也受同一套资源限额约束。
    """
    import io
    from contextlib import redirect_stdout, redirect_stderr

    _apply_rlimits(cpu_seconds, mem_bytes, fsize_bytes)

    out, err = io.StringIO(), io.StringIO()
    try:
        import pandas as pd
        import numpy as np

        _install_fs_guard(pd, np, preload)

        g = {"__builtins__": _build_safe_builtins(), "pd": pd, "np": np}

        # 预加载数据文件为 DataFrame（在子进程内，受限额约束）
        for var_name, (kind, path) in (preload or {}).items():
            try:
                if kind == "csv":
                    g[var_name] = pd.read_csv(path)
                elif kind == "excel":
                    g[var_name] = pd.read_excel(path)
                elif kind == "json":
                    g[var_name] = _load_json_df(pd, path)
            except Exception:
                pass

        with redirect_stdout(out), redirect_stderr(err):
            exec(code, g)

        # 回传 result 变量（若存在且可字符串化）与标准输出
        result_repr = None
        if "result" in g:
            try:
                val = g["result"]
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    result_repr = val.to_string()
                else:
                    result_repr = str(val)
            except Exception:
                result_repr = None
        conn.send({"ok": True, "stdout": out.getvalue(),
                   "stderr": err.getvalue(), "result": result_repr})
    except Exception as e:
        conn.send({"ok": False, "stdout": out.getvalue(),
                   "stderr": err.getvalue(),
                   "error": f"{type(e).__name__}: {e}"})
    finally:
        conn.close()


# 子进程用 fork 启动：继承已加载的 pandas/numpy，避免每次重新 import 的开销
_MP = multiprocessing.get_context("fork")


def run_in_sandbox(code, preload=None, *, mode="exec",
                   cpu_seconds=DEFAULT_CPU_SECONDS,
                   mem_bytes=DEFAULT_MEM_BYTES,
                   fsize_bytes=DEFAULT_FSIZE_BYTES,
                   wall_timeout=DEFAULT_WALL_TIMEOUT):
    """在隔离子进程中执行用户代码。返回 dict：
       {ok, stdout, stderr, result?, error?}  或  {ok:False, error:..., violation:True}

    流程：静态检查 → fork 子进程（限额）→ 墙钟超时强杀。
    """
    try:
        static_check(code, mode=mode)
    except SandboxViolation as v:
        return {"ok": False, "error": str(v), "violation": True}
    except SyntaxError as e:
        return {"ok": False, "error": f"代码语法错误: {e}", "violation": True}

    parent_conn, child_conn = _MP.Pipe(duplex=False)
    proc = _MP.Process(
        target=_child_entry,
        args=(code, preload, cpu_seconds, mem_bytes, fsize_bytes, child_conn),
        daemon=True,
    )
    proc.start()
    child_conn.close()  # 父进程只读

    proc.join(wall_timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        if proc.is_alive():
            proc.kill()
            proc.join()
        return {"ok": False, "error": f"代码执行超时（限制 {wall_timeout} 秒），已强制终止"}

    # 子进程被 OS 因超限杀掉（CPU/内存）时，exitcode 为负信号值
    if proc.exitcode and proc.exitcode != 0 and not parent_conn.poll():
        return {"ok": False, "error": f"代码触发资源限额被终止（退出码 {proc.exitcode}：可能超出 CPU 或内存上限）"}

    if parent_conn.poll():
        try:
            return parent_conn.recv()
        except EOFError:
            pass
    return {"ok": False, "error": "代码执行异常：子进程未返回结果"}
