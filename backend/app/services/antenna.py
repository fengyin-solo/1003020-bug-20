"""天馈系统业务规则：状态流转、字段校验与筛选口径都收在这里。

口径（天馈域内统一定论，列表、明细、待调整名单都按此执行）：
- 驻波比越限线 VSWR_LIMIT：大于 1.5 即越限；越限不得直接记为已调整，先留驻波异常。
- 状态只沿「正常 → 驻波异常 → 下倾偏移 → 已调整」单向前进，不许回退。
- 驻波优先：驻波异常与下倾偏移同时成立时，按驻波异常处理；
  已处在下倾偏移/已调整且驻波越限时，不能再往回补记驻波异常，需先处理越限。
- 调整完成（已调整）即从待调整名单移除；待调整只含驻波异常、下倾偏移。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "antenna"
REQUIRED_FIELDS = ["天馈编号", "天线类型", "工作频段"]
OPTIONAL_FIELDS = ["所属站点", "挂高", "方位角", "驻波比"]
NUMERIC_FIELDS = ["挂高", "方位角", "驻波比"]

STATUS_ORDER = ["正常", "驻波异常", "下倾偏移", "已调整"]
VSWR_LIMIT = 1.5
PENDING_STATUSES = {"驻波异常", "下倾偏移"}
ACTION_RULES = {"记录异常": "驻波异常", "记录偏移": "下倾偏移", "安排调整": "已调整"}


def _to_float(value: Any) -> float | None:
    """把驻波比这类数值字段解析成 float；空值或非数字一律返回 None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_vswr_over_limit(entry: dict[str, Any]) -> bool:
    """驻波比是否越限；解析不出来的脏数据不按越限处理，避免误判状态。"""
    vswr = _to_float(entry.get("驻波比"))
    return vswr is not None and vswr > VSWR_LIMIT


def _refresh(entry: dict[str, Any]) -> dict[str, Any]:
    """由状态统一派生列表/明细共用字段，保证两处口径一致、不会再对不上。"""
    status = entry.get("status", STATUS_ORDER[0])
    entry["天馈状态"] = status
    entry["pending"] = status in PENDING_STATUSES
    entry["abnormal"] = status == "驻波异常"
    return entry


class AntennaService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        pending_only: bool = False,
        sort: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("天馈编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if pending_only:
            rows = [row for row in rows if row.get("status") in PENDING_STATUSES]
        if sort in ("vswr_asc", "vswr_desc"):
            # 解析不出驻波比的脏数据排到末尾，避免排序把它们漏掉。
            rows = sorted(
                rows,
                key=lambda row: (_to_float(row.get("驻波比")) is None, _to_float(row.get("驻波比")) or 0.0),
                reverse=sort == "vswr_desc",
            )
        else:
            rows = sorted(rows, key=lambda row: int(row.get("id", 0)))
        total = len(rows)
        page = max(page, 1)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _refresh(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = self._normalize(field, values.get(field))
        entry["status"] = STATUS_ORDER[0]
        rows.append(entry)
        return _refresh(entry), []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """更新方位角、挂高、驻波比等字段；只动字段，不越权改状态。

        状态流转只能走 run_action；改完驻波比若越限，由动作接口按规则拦下，
        保证「越限不能直接记成已调整」这条口径不会被编辑动作绕过去。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"天馈设备 {entry_id} 不存在或已归档"
        editable = REQUIRED_FIELDS + OPTIONAL_FIELDS
        unknown = [field for field in values if field not in editable]
        if unknown:
            return None, f"字段「{'、'.join(unknown)}」不允许修改"
        for field in editable:
            if field in values:
                entry[field] = self._normalize(field, values[field])
        return _refresh(entry), "天馈设备资料已更新"

    @staticmethod
    def _normalize(field: str, value: Any) -> Any:
        text = str(value).strip()
        if field in NUMERIC_FIELDS:
            number = _to_float(text)
            return number if number is not None else text
        return text

    def stats(self) -> dict[str, int]:
        rows = store.rows(MODULE)
        counts = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            counts[row.get("status", STATUS_ORDER[0])] = counts.get(row.get("status", STATUS_ORDER[0]), 0) + 1
        return {
            "正常": counts["正常"],
            "驻波异常": counts["驻波异常"],
            "下倾偏移": counts["下倾偏移"],
            "已调整": counts["已调整"],
            "待调整": sum(1 for row in rows if row.get("status") in PENDING_STATUSES),
        }

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"天馈设备 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于天馈系统可执行范围"
        target = ACTION_RULES[action]
        current = entry.get("status", STATUS_ORDER[0])
        current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else 0
        target_index = STATUS_ORDER.index(target)

        # 状态机单向前进，禁止回退——驻波异常和下倾偏移不许再来回切。
        if target_index < current_index:
            return None, f"当前为「{current}」，状态只能沿 {' → '.join(STATUS_ORDER)} 前进，不能回退到「{target}」"
        if target_index == current_index:
            return None, f"当前已是「{current}」，无需重复{action}"

        over_limit = is_vswr_over_limit(entry)

        # 规则一：驻波比过线，不许直接记成已调整，得先留下异常。
        if target == "已调整" and over_limit and current != "驻波异常":
            return None, f"驻波比 {entry.get('驻波比')} 已越限（>{VSWR_LIMIT}），须先记录驻波异常并处置，不能直接安排调整"
        if target == "已调整" and current == "驻波异常" and over_limit:
            return None, "驻波异常尚未消除（驻波比仍越限），不能安排调整；请先处置并复核驻波比"

        # 规则二：驻波优先——驻波异常未消除前不能改记下倾偏移；
        # 已偏移/已调整也不允许往回补记驻波异常，避免两个异常状态来回切。
        if target == "下倾偏移" and current == "正常" and over_limit:
            return None, f"驻波比 {entry.get('驻波比')} 已越限，按驻波优先须先记录驻波异常，不能直接记录下倾偏移"
        if target == "下倾偏移" and current == "驻波异常" and over_limit:
            return None, f"驻波比 {entry.get('驻波比')} 仍越限，按驻波优先须先消除驻波异常，不能改记下倾偏移"
        if target == "驻波异常" and current in ("下倾偏移", "已调整"):
            hint = "请先消除驻波越限后再重新流转" if over_limit else "状态不允许回退到驻波异常"
            return None, f"当前为「{current}」，{hint}"

        entry["status"] = target
        _refresh(entry)
        if target == "已调整":
            return entry, "天馈设备已调整完成，已从待调整名单移除"
        return entry, f"天馈设备已{action}"
