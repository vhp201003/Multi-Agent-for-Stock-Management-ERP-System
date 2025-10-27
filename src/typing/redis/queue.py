from pydantic import BaseModel


class TaskQueueItem(BaseModel):
    query_id: str
    sub_query: str
    task_id: str


class Queue(BaseModel):
    items: list[TaskQueueItem] = []


class PendingQueue(BaseModel):
    items: list[TaskQueueItem] = []
