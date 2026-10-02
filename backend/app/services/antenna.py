"""天馈系统业务规则：状态流转、字段校验与筛选口径都收在这里。

越限定论（全模块只认这一套）：
- 驻波比大于 VSWR_LIMIT 即越限，越限就是驻波异常，不许直接记成已调整；
- 驻波异常与下倾偏移同时出现时，驻波异常优先展示；
- 状态沿 正常 → 驻波异常 → 下倾偏移 → 已调整 走，不许回退，已调整是终点；
- 待调整名单只留未处理的异常设备，调整完立刻移出。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "antenna"
REQUIRED_FIELDS = ["天馈编号", "天线类型", "工作频段"]
EDITABLE_FIELDS = ["天线类型", "工作频段", "所属站点", "挂高", "方位角", "驻波比"]
NUMERIC_FIELDS = ("挂高", "方位角", "驻波比")
SORTABLE_FIELDS = ("天馈编号", "挂高", "方位角", "驻波比")

# 越限线：驻波比超过 1.5 即判定越限
VSWR_LIMIT = 1.5

STATUS_ORDER = ["正常", "驻波异常", "下倾偏移", "已调整"]
ACTION_RULES = {"记录异常": "驻波异常", "记录偏移": "下倾偏移", "安排调整": "已调整"}
ANOMALY_STATUSES = ("驻波异常", "下倾偏移")


def _to_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _vswr_over(entry: dict[str, Any]) -> bool:
    """驻波比是否越限：只认数值，过线就是越限。"""
    value = _to_number(entry.get("驻波比"))
    return value is not None and value > VSWR_LIMIT


def _derive_status(entry: dict[str, Any]) -> str:
    """按统一口径推导状态，列表、详情、看板看到的都是同一个结论。

    - 已调整是终点，一旦到达不再变化；
    - 驻波比越限或已记录驻波异常时，驻波异常优先于下倾偏移；
    - 记录过的异常标记不因数值回落被抹掉，只能靠安排调整收尾。
    """
    if entry.get("adjusted"):
        return "已调整"
    if _vswr_over(entry) or entry.get("vswr_anomaly"):
        return "驻波异常"
    if entry.get("tilt_offset"):
        return "下倾偏移"
    return "正常"


def _sync(entry: dict[str, Any]) -> dict[str, Any]:
    """把推导结果写回记录：状态、待调整口径与异常标记同源，互不对账。"""
    status = _derive_status(entry)
    entry["status"] = status
    entry["天馈状态"] = status
    entry["pending"] = status in ANOMALY_STATUSES
    entry["abnormal"] = status in ANOMALY_STATUSES
    return entry


def _sort_key(row: dict[str, Any], field: str) -> tuple[int, Any]:
    value = row.get(field)
    if field in NUMERIC_FIELDS:
        number = _to_number(value)
        # 没填或不是数值的记录排到最后，不参与大小比较
        return (0, number) if number is not None else (1, 0.0)
    return (0, str(value or ""))


def _clean_numbers(values: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """把数值字段统一转成数字并校验量程，不合法时给出可读原因。"""
    cleaned: dict[str, Any] = {}
    for field in NUMERIC_FIELDS:
        if field not in values or values[field] in (None, ""):
            continue
        number = _to_number(values[field])
        if number is None:
            return {}, f"{field}需填写数值"
        if field == "方位角" and not 0 <= number <= 360:
            return {}, "方位角需在 0 到 360 度之间"
        if field == "驻波比" and number < 1:
            return {}, "驻波比不会小于 1，请核对测量值"
        if field == "挂高" and number <= 0:
            return {}, "挂高需大于 0"
        cleaned[field] = int(number) if number == int(number) else number
    return cleaned, ""


class AntennaService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        pending: bool | None = None,
        sort: str | None = None,
        order: str = "asc",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [_sync(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("天馈编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if pending is not None:
            rows = [row for row in rows if bool(row.get("pending")) == pending]
        if sort:
            rows = sorted(rows, key=lambda row: _sort_key(row, sort), reverse=order == "desc")
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _sync(entry) if entry is not None else None

    def stats(self) -> dict[str, Any]:
        rows = [_sync(row) for row in store.rows(MODULE)]
        by_status = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            by_status[row["status"]] += 1
        return {
            "total": len(rows),
            "by_status": by_status,
            "pending": sum(1 for row in rows if row.get("pending")),
            "vswr_limit": VSWR_LIMIT,
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        cleaned, error = _clean_numbers(values)
        if error:
            return None, error
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + EDITABLE_FIELDS:
            if field in cleaned:
                entry[field] = cleaned[field]
            elif field in values and str(values.get(field) or "").strip():
                entry[field] = str(values[field]).strip()
        entry["vswr_anomaly"] = False
        entry["tilt_offset"] = False
        entry["adjusted"] = False
        rows.append(_sync(entry))
        return entry, "天馈设备已登记"

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"天馈设备 {entry_id} 不存在或已归档"
        if not values:
            return None, "没有提交可更新的字段"
        unknown = [field for field in values if field not in EDITABLE_FIELDS]
        if unknown:
            return None, f"字段不允许直接修改：{'、'.join(unknown)}"
        cleaned, error = _clean_numbers(values)
        if error:
            return None, error
        for field in EDITABLE_FIELDS:
            if field in cleaned:
                entry[field] = cleaned[field]
            elif field in values and field not in NUMERIC_FIELDS:
                text = str(values[field]).strip()
                if text:
                    entry[field] = text
        # 状态按统一口径重新推导：越限即异常，已记录的异常标记不回退
        return _sync(entry), "天馈设备已更新"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"天馈设备 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于天馈系统可执行范围"
        _sync(entry)
        if entry["status"] == "已调整":
            return None, "天馈设备已调整完成，状态沿流程不可回退"
        if action == "记录异常":
            entry["vswr_anomaly"] = True
            _sync(entry)
            return entry, "已记录驻波异常，设备留在待调整名单"
        if action == "记录偏移":
            entry["tilt_offset"] = True
            _sync(entry)
            if entry["status"] == "驻波异常":
                return entry, "已记录下倾偏移，按规则驻波异常优先展示"
            return entry, "已记录下倾偏移，设备留在待调整名单"
        # 安排调整：驻波比越限必须先留下异常记录，不许直接记成已调整
        if _vswr_over(entry) and not entry.get("vswr_anomaly"):
            return None, f"驻波比 {entry.get('驻波比')} 已超过 {VSWR_LIMIT} 越限线，需先记录异常再安排调整"
        entry["adjusted"] = True
        entry["vswr_anomaly"] = False
        entry["tilt_offset"] = False
        _sync(entry)
        return entry, "天馈设备已安排调整，移出待调整名单"
