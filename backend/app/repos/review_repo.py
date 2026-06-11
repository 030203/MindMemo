import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.review import ReviewQueueItem


class ReviewRepository:
    def list_for_user(self, db: Session, user_id: uuid.UUID) -> list[ReviewQueueItem]:
        stmt = (
            select(ReviewQueueItem)
            .where(ReviewQueueItem.user_id == user_id)
            .order_by(desc(ReviewQueueItem.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    def get_for_user(self, db: Session, user_id: uuid.UUID, review_id: uuid.UUID) -> ReviewQueueItem | None:
        stmt = select(ReviewQueueItem).where(
            ReviewQueueItem.id == review_id,
            ReviewQueueItem.user_id == user_id,
        )
        return db.execute(stmt).scalar_one_or_none()

    def get_pending_for_target(
        self,
        db: Session,
        user_id: uuid.UUID,
        *,
        review_type: str,
        target_type: str,
        target_id: uuid.UUID,
    ) -> ReviewQueueItem | None:
        stmt = select(ReviewQueueItem).where(
            ReviewQueueItem.user_id == user_id,
            ReviewQueueItem.review_type == review_type,
            ReviewQueueItem.target_type == target_type,
            ReviewQueueItem.target_id == target_id,
            ReviewQueueItem.status == "pending",
        )
        return db.execute(stmt).scalar_one_or_none()

    def create(self, db: Session, review_item: ReviewQueueItem) -> ReviewQueueItem:
        db.add(review_item)
        db.flush()
        db.refresh(review_item)
        return review_item

    def save(self, db: Session, review_item: ReviewQueueItem) -> ReviewQueueItem:
        db.flush()
        db.refresh(review_item)
        return review_item


review_repository = ReviewRepository()
