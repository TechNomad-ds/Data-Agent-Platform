# Plan: 防止 agent 通读类任务「没读完就总结」

## 问题

用户让 agent「概述/讲解/总结整篇」文件时，agent 会偷懒：
- 用很小的页大小略读几十行就下结论；
- 读到 `read_file` 返回的「⚠️ 未读完，还有 N 行」提示直接无视；
- 甚至压根不读用户本次附带的文件（如本次的 `p3655-zhang.pdf` 没读，只读了 README/config 就总结）。

过去 18 天已用「提示词说教」修过两轮（footer 加 ⚠️、系统提示词加硬约束），但 LLM 可以无视纯文本提示——这次就无视了。根因：**agent 判定「完成」是纯自愿的，收尾时（某轮不调工具直接作答）没有任何代码层闸门检查「该读的读完没」。**

## 决策（已与用户确认）

- **强度：挡一次强提醒。** 不死磕、不无限拦。首次想收尾且检测到「通读类任务 + 有文件读到一半未读完」时，强制注入一次续读提示并拦回循环；之后即便仍未读完也放行，靠 max_iterations 兜底防死循环。
- **范围：只管通读类任务。** 仅当用户意图是「概述/讲解/总结整篇/逐篇」时触发。「找某个具体信息」的快通道（search + 跳读）不受影响，避免误伤快问快答、也不失控烧额度。

## 机制（复用现有注入闸模式）

现有 `loop.py:707 if not tool_uses:` 收尾链上已有两道同构闸：`plan_nudge`（`iteration -= 1` 不耗配额、`plan_nudges < MAX_PLAN_NUDGES` 限次）和 `self_check`（`self_check_done` 只走一次）。新增第三道「未读完」闸，完全对齐该模式。

### 改动点（均在 `backend/app/agent/loop.py`，纯后端）

1. **记账：跟踪「有未读残余的文件」集合。**
   - 在工具结果后处理循环 `loop.py:936` 内，对 `tu["name"] == "read_file"` 的结果字符串判断：
     - 含 `"未读完"` → 把该文件名加入 `files_partially_read`（set）；
     - 含 `"全文已读完"` → 从 `files_partially_read` 移除（读完了就销账）。
   - 文件名从 `tool_args`（read_file 的 `filename` 入参）取，稳妥且无需解析结果文本。
   - 在 run() 顶部初始化 `files_partially_read: set[str] = set()` 和 `readthrough_nudged = False`。

2. **意图判定：是否通读类任务。**
   - 轻量判断当前用户消息是否属于「概述/讲解/总结整篇/逐篇/通读」意图。
   - 用一个小关键词集合（概述、概括、总结、讲解、讲讲、逐篇、通读、整体情况、整篇、全文、overview、summar…）对**本轮用户原始问题**做匹配，命中即视为通读类。
   - 记忆里提过「关键词伪路由脆弱」——这里可接受，因为：① 只用于「要不要多拦一次」这种低风险增益，判错顶多少拦/多拦一次不影响正确性；② 不改变工具下发、不碰上下文灌注。仍属提示注入层，不是硬路由。

3. **闸门：收尾时拦一次。**
   - 在 `loop.py:707 if not tool_uses:` 块内，**插在 plan_nudge 之前**（未读完优先于计划提醒）：
     ```
     if (is_readthrough_task and files_partially_read and not readthrough_nudged):
         # 落 full_text 到 messages/canonical（同 plan_nudge 写法）
         nudge = "（系统提示）以下文件你还没读完就准备作答了：{名单}。" \
                 "通读/概述/讲解整篇必须先把它们读完——用 read_file(filename, start_line=上次末尾) " \
                 "翻页续读到出现「全文已读完」，再综合全部内容作答。不要以「核心已覆盖/后面是附录」为由跳过。"
         messages.append(user nudge); turn_canonical.append(...)
         readthrough_nudged = True
         iteration -= 1  # 注入轮不耗配额
         continue
     ```
   - 只走一次（`readthrough_nudged` 置真）。之后仍未读完则放行收尾，不死磕。

### 为什么不动其它层

- **不改 max_lines / footer / 现有提示词**：那两轮已经加过，保留即可；本次补的是它们扛不住时的代码层兜底。
- **不碰 2000 字符前端展示截断**：那是纯展示、agent 看到全文，与偷懒无关（已向用户澄清）。
- **不做「所有涉文件任务都强制读完」**：用户明确只要通读类，避免误伤「只找一个数字」的快通道。

## 验证

- 后端语法自检 `py_compile` + `compileall app`。
- 手工构造：通读类问题 + 一个大文件，确认首次收尾被拦一次、注入续读提示、`iteration` 未被消耗；第二次即便仍未读完也放行。
- 确认非通读类（如「X 的值是多少」）不受影响：`is_readthrough_task=False` 时闸门不触发。
- pytest 本项目会 hang（既有 asyncio 死锁），用直接执行/import 验证，不跑全量 pytest。
- 重启 `datamind-backend.service`，health 200。

## 风险

- 关键词判定漏判（通读类没被识别）→ 退化为现状（不拦），不会更糟。
- 误判（非通读被识别为通读且恰有未读文件）→ 至多多拦一次、多读一页，成本有界（只一次）。
- 无死循环风险：`readthrough_nudged` 单次 + `iteration -= 1` 仅省这一次配额，max_iterations 仍兜底。
