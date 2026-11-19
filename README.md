# 榆湾材料试验室双段质控归档

白班两台架各交一段实采读数。站员按同一份采样清册核定段内变化并冻结证据。夜班关闭源站后，凭接纳号补算接缝告警及整程次数。次班勘误后仍可凭原报告号核对当时的读数修订及结论。

## 运行

使用 Python 3.11 和标准库。物化工程提供 `check_project.py` 作为完整回归入口。

```sh
python3 -B check_project.py
python3 -B demo.py
```

演示从 `examples/day_shift.json` 读取固定班次样例，在独立临时目录建立两份站库和一份中心库，结束时清理。原读数 0、0、1、1 在门槛和变化上限均为 1 时签出一次告警。后段改为 0、0 后另签零次，重开中心仍可按两个原号领取。随后按 `examples/interval_shift.json` 的 two_counts 样例演示 V2 区间复核：两站关闭后签发 `[0,1]`，前站另记修订并把区间固定为 1 后另签 `[0]`，重开中心按原号领取旧报告及其原选件。演示输出的场景记录来自断言核对后的实际报告及领取结果。

## 业务接口

用 `database.connect(path)` 打开连接，调用者负责关闭。各写入口拥有自己的事务，调用时连接应处于事务外。先对各库执行 `plan.catalog.initialize_catalog(db)`。站库再执行 `ledger.storage.initialize_ledger(db, origin)` 和 `station.storage.initialize_station(db)`。中心库执行 `intake.registry.initialize_intake(db)` 和 `review.storage.initialize_review(db)`。初始化可以重复执行，已有站点绑定及业务数据保留。

1. 班长用 `plan.tasks.open_task(db, name, unit, threshold, max_change, segments)` 登记任务。`segments` 依序提供两个 `plan.layout.SegmentLayout(slot, origin, rig, beats)`，段位为 1、2，拍位为整数。每段非空且连续，前末与后首相邻。规程需具名，变化上限非负。非法定义抛出 `ValueError`。
2. `plan.catalog.get_task(db, task_id)` 领取不可变快照，`install_task_snapshot(db, snapshot)` 在各站和中心安装同一快照。相同快照重放返回原号，同号异内容抛出 `ValueError`。未知任务号抛出 `KeyError`。
3. `ledger.ingest.record_segment(db, task_id, slot, samples, parent_id=None)` 登记整段。`samples` 是 `(拍位, 读数)` 对的可迭代对象，提交次序任意，每个计划拍位须恰好出现一次。读数、门槛和变化上限接受整数、`Fraction` 和精确有理数字符串，如 `-1/3`、`0.5`。空值、浮点值、零分母、错误拍位或站点归属抛出 `ValueError`。`ledger.query.get_revision(db, revision_id)` 按号取得清册顺序的原读数。勘误指定同任务同段同台架的父修订并新增一版，错误归属抛出 `ValueError`，未知任务或父号抛出 `KeyError`。
4. `station.freeze.freeze_segment(db, revision_id)` 检查该版每对相邻读数的绝对差。等于变化上限可以冻结，超限抛出 `ValueError`，原修订保留。告警从严格低于门槛到达到或超过门槛时计一次，首拍自身零次。`station.export.export_segment(db, piece_id)` 按号导出稳定的 V1 字节，未知修订或站件号抛出 `KeyError`。
5. `intake.registry.accept_segment(db, payload)` 校验 V1 与登记任务，保存首份字节并返回接纳号。`get_accepted_piece(db, acceptance_id)` 领取身份、解码值、首份原文及回执。同站同件号的等内容重投沿用原接纳号，允许 JSON 空白及字段次序不同。坏件、任务或站点不匹配、同号异内容抛出 `ValueError`。
6. `review.issue.issue_review(db, task_id, front_id, back_id, *, before_commit=None)` 用有序选件的实际前末和后首核算接缝，返回 `(report_id, receipt)`。接缝合法才签发，两段次数与接缝次数合计为整程次数。未知号抛出 `KeyError`，重复、逆序、异任务选件或接缝超限抛出 `ValueError`。可选的无参 `before_commit` 在报告与回执已暂存时运行，抛出的异常连同存储错误一起传播，此次签发回滚。
7. `review.history.get_review(db, report_id)` 返回固定任务、有序选件、两段计数、接缝实值与差值、接缝计数、整程计数及原回执。未知报告号抛出 `KeyError`。源站勘误、重开中心或重复初始化后照常领取旧报告。

V1 UTF-8 JSON 使用固定字段顺序 `version, origin, piece_id, task_id, slot, revision_id, first, last, crossings`。`version` 为整数 1，编号为正整数，段位为整数 1 或 2，`first` 与 `last` 为约分后的 `分子/分母` 字符串。站内件号按站点命名，中心接纳号与签发号各自只在其中心库内使用。中心核对站件的任务归属和摘要形状，站内逐拍检查由登记站承担。

## 区间复核（V2）

夜班按 `INTERVALS.md` 复核量化误差内整程可能触发的告警次数，初始化流程不变。

1. `station.freeze.freeze_interval_segment(db, revision_id, intervals)` 按本站一版原读数冻结区间证据。`intervals` 为 `(拍位, 下限, 上限)` 三元组，提交顺序任意，修订中每拍恰好一次；端点沿用精确有理数输入规则，`下限 <= 原读数 <= 上限`，允许端点相等。每段限 1～8 拍。未知修订抛出 `KeyError`，覆盖、拍位、端点或段长非法抛出 `ValueError`，此次冻结无新增站件。合法区间即使站内无可行轨迹也可冻结，空关系照实保全。
2. `station.export.export_interval_segment(db, piece_id)` 导出稳定的 V2 字节，未知件号抛出 `KeyError`。
3. `intake.registry.accept_interval_segment(db, payload)` 校验版本、证据结构与来源归属后接纳，返回固定接纳号；`get_accepted_interval_piece(db, acceptance_id)` 领取。V1 与 V2 接纳号出自同一序列、互不混用；V1 字节、坏件、未知任务或身份冲突抛出 `ValueError`，拒绝后不留下新接纳。
4. `review.issue.issue_interval_review(db, task_id, front_id, back_id, *, before_commit=None)` 只凭同任务按前后段选定的两个 V2 接纳号核定共同轨迹，按升序签发全部可达次数，无整程可行轨迹时签发 `[]`。未知任务或接纳号抛出 `KeyError`，重复、逆序、异任务或 V1 选件抛出 `ValueError`。报告与回执同次提交，`before_commit` 语义与 V1 一致，失败无新增且可重试。
5. `review.history.get_interval_review(db, report_id)` 按原号领取，提供 `report_id`、`task_id`、`front_id`、`back_id`、`front_source`、`back_source`、`reachable_counts` 和 `receipt` 属性；每侧来源为 `(origin, piece_id, revision_id)`，次数为升序整数列表。未知报告号抛出 `KeyError`。源站更正、另签或中心库重开后，原号照常返回原次数、选件及回执。

V2 UTF-8 JSON 使用固定字段顺序 `version, origin, piece_id, task_id, slot, revision_id, boundary_beat, boundary_interval, counted_pairs, relation`。`version` 为整数 2。边界变量为接缝侧拍位的取值：前段末拍或后段首拍，`boundary_interval` 为其冻结闭区间。`counted_pairs` 列出已入账的段内相邻对，接缝告警不在站件内入账。`relation` 每项为 `[下限, 上限, 下限开, 上限开, 次数]`，表示边界变量落在该（半）开区间内时对应段内次数可达；逐拍原读数与内部拍的单独区间留站。中心按两边关系枚举接缝可行组合与接缝告警取值，合计出整程可达次数。
