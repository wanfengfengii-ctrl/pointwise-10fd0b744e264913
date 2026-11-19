# 量化误差下的双段复核

白班照常按 `README.md` 安装任务和登记原读数。夜班可以选择 V2 站件，复核仪器允许误差内整程可能发生的告警次数。门槛 `T`、变化上限 `D`、单位和段序均来自同一个固定任务快照。

## 冻结和交件

`station.freeze.freeze_interval_segment(db, revision_id, intervals)` 返回固定 V2 站件号。`revision_id` 指定本站已登记的一版原读数。`intervals` 是 `(beat, lo, hi)` 三元组的可迭代对象，提交顺序任意，修订中每拍须恰好出现一次。拍位沿用原登记规则，端点沿用原接口的精确有理数输入规则。`lo <= 原读数 <= hi`，允许 `lo == hi`。V2 任务的前后段各限 1～8 拍。未知修订报 `KeyError`，覆盖、拍位、端点或段长非法报 `ValueError`，此次冻结无新增站件。

每拍独立选定一个区间内的实值，同一拍用于前后两次相邻比较时取值一致。每对相邻值满足 `abs(a-b) <= D`，包括跨段接缝。只有 `a < T <= b` 计一次告警，首拍自身不计。合法区间输入即使没有站内可行轨迹也可以冻结，照实保全空关系。

`station.export.export_interval_segment(db, piece_id)` 返回冻结件的稳定 UTF-8 JSON 字节，未知 V2 件号报 `KeyError`。顶层 `version` 为整数 2。站件绑定站点、件号、固定任务、段位、确切读数修订和本次冻结的区间。逐拍原读数及内部拍的单独区间留站。站件必须保全联合核定需要的边界可行关系及其对应次数。证据表示由交付实现决定，须交代所用边界变量及哪些告警已经入账。

`intake.registry.accept_interval_segment(db, payload)` 接纳 V2 字节并返回固定接纳号。中心核对版本、证据结构和来源归属，所用任务快照须与中心登记内容一致。坏件、V1 字节或身份冲突报 `ValueError`，拒绝后不留下新接纳。V1 和 V2 接纳身份须可区分。中心的签发以所选接纳的固定正文为准。

## 签发和领取

`review.issue.issue_interval_review(db, task_id, front_id, back_id, *, before_commit=None)` 接收中心库、任务号及依前后段排列的两个 V2 接纳号，返回 `(report_id, receipt)`。未知任务或接纳号报 `KeyError`，重复、逆序、异任务或 V1 选件报 `ValueError`。签发只依赖中心登记的任务和已接纳的证据。中心须在同一条完整可行轨迹上兑现接缝变化约束与告警口径。每一种可达次数只列一次，接缝告警只入账一次。没有整程可行轨迹时照常签发，次数为 `[]`。

报告和回执同次提交。回执提供 `report_id` 和 `task_id`。`before_commit` 沿用原签发入口的含义，在报告及回执均已写入当次事务、尚未提交时调用。钩子或写入失败须传播原异常，不留新报告或回执，原选件可重试。

`review.history.get_interval_review(db, report_id)` 按 V2 报告号领取保存值，未知号报 `KeyError`。返回对象提供 `report_id`、`task_id`、`front_id`、`back_id`、`front_source`、`back_source`、`reachable_counts` 和 `receipt` 属性。每侧来源为 `(origin, piece_id, revision_id)`，次数为升序整数列表。源站更正、另签或中心库重开后，原号照常返回原次数、选件及回执。

## 公开样例与运行

`examples/interval_shift.json` 每项描述一个独立任务。`front` 和 `back` 中每行依次为 `[拍位, 原读数, 区间下限, 区间上限]`。用 `threshold` 和 `max_change` 建原任务，按行的前两列调用原登记入口，再以第 1、3、4 列调用冻结入口。设定前站 `west` 和后站 `east`，将同一任务快照安装到两站与中心。两站导出关闭后，中心将返回的两个接纳号按段位签发，按报告号领取的 `reachable_counts` 应与样例对应。

`seam_filters_local_count` 唯一可行整程是 0、1、2，告警在站内发生一次。`same_readings_tight` 使用完全一样的实采读数，但前段末拍固定为 0，整程无解。`equal_only` 的接缝只允许等值，达到门槛也不会凭空产生告警。`interior_only` 的前拍可接续范围为 [5/4,7/4]，整程零次。`local_empty` 的前段本身无可行轨迹，仍领取空次数报告。

沿 `.pointwise-runtime.json` 的核验与演示入口接通新链路。核验须执行原回归并检查新业务结果和失败边界，核验失败时返回非零退出码。演示实际运行断源签发，展示次数及采用的修订，再重开中心按原号领取。可用 `two_counts` 演示勘误，旧报告为 `[0,1]`，前站另记修订并固定为 1 后另签 `[0]`，重开仍可领取旧报告及其原选件。
