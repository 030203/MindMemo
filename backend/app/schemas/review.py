from pydantic import BaseModel


class ReviewQueueItemResponse(BaseModel):
    id: str
    review_type: str
    reason: str
    target_title: str
    status: str


class ReviewDecisionRequest(BaseModel):
    note: str = ""
