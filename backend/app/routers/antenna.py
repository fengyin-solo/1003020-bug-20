"""天馈系统接口：维护天馈设备，覆盖记录异常、记录偏移、安排调整等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.antenna import SORTABLE_FIELDS, AntennaService

router = APIRouter(prefix="/api/antenna", tags=["天馈系统"])

service = AntennaService()


def _merged_values(payload: EntryPayload) -> dict[str, Any]:
    """合并两种提交方式：字段包在 values 里，或直接平铺在请求体顶层。"""
    extra = payload.model_extra or {}
    return {**extra, **payload.values}


@router.get("/stats")
def stats() -> dict[str, Any]:
    """状态分布与待调整数量：给页头统计卡片用，口径与列表一致。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出天馈系统清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "antenna", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按天馈编号检索"),
    status: str | None = Query(default=None, description="正常、驻波异常、下倾偏移、已调整"),
    pending: bool | None = Query(default=None, description="传 true 只看待调整名单"),
    sort: str | None = Query(default=None, description="排序字段：天馈编号、挂高、方位角、驻波比"),
    order: str = Query(default="asc", description="asc 升序、desc 降序"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、状态、待调整口径过滤天馈列表，支持按驻波比等字段排序；没有数据时返回空页，不报错。"""
    if page < 1:
        raise HTTPException(status_code=400, detail="页码从 1 开始")
    if not 1 <= size <= 200:
        raise HTTPException(status_code=400, detail="每页 1 到 200 条，请调整分页范围")
    if sort is not None and sort not in SORTABLE_FIELDS:
        raise HTTPException(status_code=400, detail=f"暂不支持按「{sort}」排序")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="排序方向只支持 asc 或 desc")
    items, total = service.list_entries(
        keyword=keyword, status=status, pending=pending, sort=sort, order=order, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条天馈设备明细；与列表同一份推导结果，不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"天馈设备 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条天馈设备，缺字段或数值不合法时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(_merged_values(payload))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改方位角、驻波比等字段；保存后状态按统一口径重新推导，列表同步刷新。"""
    entry, message = service.update_entry(entry_id, _merged_values(payload))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条天馈设备执行记录异常、记录偏移、安排调整；越限未记录、状态回退都会被拦下并说明原因。"""
    action = str(payload.action or payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
