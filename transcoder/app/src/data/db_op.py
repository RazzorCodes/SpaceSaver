from dataclasses import asdict
from typing import Any, Sequence

from data.db import Database
from misc.logger import logger
from models.models import ListItem
from models.orm import Items, Metadata, WorkItemStatus
from sqlalchemy.orm import selectinload
from sqlmodel import select


def _get_fields_dict(
    record: ListItem, model: type, exclude_id: bool = True
) -> dict[str, Any]:
    """Helper: Extracts fields from a ListItem that correspond to a specific SQLModel."""
    excludes = {"id"} if exclude_id else set()
    return {
        k: v
        for k, v in asdict(record).items()
        if k in model.model_fields and k not in excludes
    }


def create_list_item(db: Database, record: ListItem) -> bool:
    """Inserts a new ListItem and its Metadata into the database."""
    with db.session() as session:
        try:
            # Check for existing item to prevent duplicate inserts
            existing_item = session.exec(
                select(Items).where(Items.hash == record.hash)
            ).first()
            if existing_item:
                logger.debug(f"Item with hash {record.hash} already exists.")
                return False

            # 1. Create and add the main item
            item = Items(**_get_fields_dict(record, Items))
            session.add(item)
            session.flush()  # Get the ID without committing
            session.refresh(item)

            # 2. Create and add the metadata tied to the item's new ID
            metadata = Metadata(**_get_fields_dict(record, Metadata), id=item.id)
            session.add(metadata)
            session.commit()  # Single atomic commit for both

            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create list item: {e}")
            return False


def upsert_list_item(db: Database, record: ListItem) -> bool:
    """Updates an existing ListItem and its Metadata, or creates them if they don't exist."""
    with db.session() as session:
        try:
            # 1. Upsert the Main Item
            item = session.exec(select(Items).where(Items.hash == record.hash)).first()
            if item:
                # Update existing
                for key, value in _get_fields_dict(record, Items).items():
                    setattr(item, key, value)
                session.add(item)
                item_id = item.id
            else:
                # Insert new
                new_item = Items(**_get_fields_dict(record, Items))
                session.add(new_item)
                session.flush()  # Get the ID without committing
                session.refresh(new_item)
                item_id = new_item.id

            # 2. Upsert the Metadata
            metadata = session.exec(
                select(Metadata).where(Metadata.id == item_id)
            ).first()
            if metadata:
                # Update existing
                for key, value in _get_fields_dict(record, Metadata).items():
                    setattr(metadata, key, value)
                session.add(metadata)
            else:
                # Insert new
                new_metadata = Metadata(
                    **_get_fields_dict(record, Metadata), id=item_id
                )
                session.add(new_metadata)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to upsert list item: {e}")
            return False


def read_list_items(
    db: Database,
    status_filter: WorkItemStatus | Sequence[WorkItemStatus] | None = None,
    item_hash: str | None = None,
) -> list[ListItem]:
    """Retrieves list items, optionally filtered by processing status(es) and/or hash."""
    with db.session() as session:
        stmt = select(Items).options(selectinload(Items.metadata_item))

        # Handle status filtering (single or multiple)
        if status_filter is not None:
            # If it's a list/tuple/set, use the SQL 'IN' clause
            if isinstance(status_filter, (list, tuple, set)):
                stmt = stmt.where(Items.status.in_(status_filter))
            # If it's just a single status, use the standard equality check
            else:
                stmt = stmt.where(Items.status == status_filter)

        # Handle hash filtering
        if item_hash is not None:
            stmt = stmt.where(Items.hash == item_hash)

        results = session.exec(stmt).all()

        return [
            ListItem(
                **item.model_dump(exclude={"metadata_item"}),
                **item.metadata_item.model_dump(exclude={"id"}),
            )
            for item in results
            if item.metadata_item
        ]


def delete_list_item(db: Database, item_hash: str) -> bool:
    """Deletes a list item and its metadata by the item's hash."""
    with db.session() as session:
        try:
            item = session.exec(select(Items).where(Items.hash == item_hash)).first()
            if not item:
                return False

            # Note: If your ORM relationships have `cascade="all, delete-orphan"`,
            # deleting the item will automatically delete the metadata.
            # If not, you should delete the metadata explicitly here first:
            metadata = session.exec(
                select(Metadata).where(Metadata.id == item.id)
            ).first()
            if metadata:
                session.delete(metadata)

            session.delete(item)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to delete list item: {e}")
            return False
