from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import override

from data.db import Database
from misc.logger import logger
from models.configuration import Configuration
from models.models import ListItem
from models.orm import Items, Metadata, WorkItemStatus
from modules.module import Module, Stage, StagedEnum
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select


class State(StrEnum):
    UNKNOWN = "unknown"
    # --- STARTUP ---
    STARTUP = "startup"
    RETRIEVING = "retrieving"
    CREATE = "creating"
    CONNECT = "connecting"
    VALIDATE = "validating"
    MIGRATE = "migrating"
    READY = "ready"
    ERROR = "unrecoverable"

    def AsStage(self) -> Stage:
        match self:
            case State.UNKNOWN:
                return Stage.UNKNOWN
            case State.STARTUP:
                return Stage.STARTUP
            case State.RETRIEVING | State.CREATE | State.CONNECT | State.VALIDATE:
                return Stage.SETUP
            case State.MIGRATE:
                return Stage.PROCESSING
            case State.READY:
                return Stage.READY
            case _:
                return Stage.ERROR


class DatabaseModule(Module[State]):
    _database: Database = field(init=False)

    def __init__(self):
        super().__init__(State.UNKNOWN)

    @override
    def setup(self, config: Configuration) -> bool:
        logger.info("Setting up database module")
        return self._setup(db_path=config.database_path or None)

    def _setup(
        self, db_path: Path | None = None, db_obj: Database | None = None
    ) -> bool:
        self.state = State.STARTUP
        self.state = State.RETRIEVING

        if db_obj is not None:
            if db_path is not None:
                logger.debug("db_path ignored because db_obj was provided")
            logger.info(f"Setting up database module with provided database {db_obj}")
            db = db_obj
        elif db_path is not None:
            logger.info(f"Setting up database module from path {db_path}")
            try:
                db = Database(_db_path=db_path)
            except Exception as ex:
                logger.error(f"Could not retrieve database: {ex}")
                return False
        elif self._database:
            db = self._database
        else:
            self.state = State.ERROR
            logger.error("Could not set up database module with empty database")
            return False

        if not db.exists:
            self.state = State.CREATE
            if not db.create():
                self.state = State.ERROR
                return False

        self.state = State.CONNECT
        if not db.connect():
            self.state = State.ERROR
            return False

        self.state = State.VALIDATE
        if not db.validate():
            self.state = State.MIGRATE
            if not db.migrate():
                self.state = State.ERROR
                return False
            # Re-validate after migration to confirm it succeeded
            self.state = State.VALIDATE
            if not db.validate():
                self.state = State.ERROR
                return False

        self._database = db
        self.state = State.READY
        return True

    def _insert(self, obj: SQLModel) -> bool:
        session = self._database.session()
        if not session:
            return False

        session.add(obj)
        session.commit()
        session.refresh(obj)

        return True

    def _upsert(self, obj: SQLModel, unique_field: str) -> bool:
        session = self._database.session()
        if not session:
            return False

        # Get the value to match
        key_value = getattr(obj, unique_field)
        # Find existing row
        stmt = select(type(obj)).where(getattr(type(obj), unique_field) == key_value)
        existing = session.exec(stmt).first()

        if existing:
            # Update all fields from obj
            for f in type(obj).model_fields:  # use model_fields for SQLModel
                if f == "id":
                    continue
                setattr(existing, f, getattr(obj, f))
            session.add(existing)
            session.commit()
            session.refresh(existing)
            # Sync the id back so callers (like insert_record) can read item.id
            obj.id = existing.id
        else:
            session.add(obj)
            session.commit()
            session.refresh(obj)

        return True

    def insert_record(self, record: ListItem):
        session = self._database.session()
        if not session:
            return

        # Check if item with this hash already exists
        stmt = select(Items).where(Items.hash == record.hash)
        existing_item = session.exec(stmt).first()

        if existing_item:
            item_id = existing_item.id
        else:
            item_data = {
                k: v
                for k, v in asdict(record).items()
                if k in Items.model_fields and k not in ("id")
            }
            item = Items(**item_data)
            session.add(item)
            session.commit()
            session.refresh(item)
            item_id = item.id

        # Check if metadata for this item already exists
        stmt = select(Metadata).where(Metadata.id == item_id)
        existing_meta = session.exec(stmt).first()
        print(existing_meta)

        if not existing_meta:
            metadata_data = {
                k: v
                for k, v in asdict(record).items()
                if k in Metadata.model_fields and k != "id"
            }
            metadata = Metadata(**metadata_data, id=item_id)
            session.add(metadata)
            session.commit()

    def upsert_record(self, record: ListItem):
        session = self._database.session()
        if not session:
            return

        # Upsert Item
        item_data = {
            k: v
            for k, v in asdict(record).items()
            if k in Items.model_fields and k not in ("id")
        }
        item = Items(**item_data)

        stmt = select(Items).where(Items.hash == item.hash)
        existing_item = session.exec(stmt).first()

        if existing_item:
            for f in Items.model_fields:
                if f == "id":
                    continue
                setattr(existing_item, f, getattr(item, f))
            session.add(existing_item)
            session.commit()
            session.refresh(existing_item)
            item_id = existing_item.id
        else:
            session.add(item)
            session.commit()
            session.refresh(item)
            item_id = item.id

        # Upsert Metadata
        metadata_data = {
            k: v
            for k, v in asdict(record).items()
            if k in Metadata.model_fields and k != "id"
        }
        metadata = Metadata(**metadata_data, id=item_id)

        stmt = select(Metadata).where(Metadata.id == item_id)
        existing_meta = session.exec(stmt).first()

        if existing_meta:
            for f in Metadata.model_fields:
                if f == "id":
                    continue
                setattr(existing_meta, f, getattr(metadata, f))
            session.add(existing_meta)
        else:
            session.add(metadata)

        session.commit()

    def get_all(self) -> list[ListItem]:
        res = []
        with self._database.session() as session:
            if not session:
                return []
            stmt = select(Items).options(selectinload(Items.metadata_item))
            result = session.exec(stmt).all()
            for item in result:
                res.append(
                    ListItem(
                        **item.model_dump(exclude={"metadata_item"}),
                        **item.metadata_item.model_dump(exclude={"id"}),
                    )
                )

        return res

    def get_unknown(self) -> list[ListItem]:
        res = []
        with self._database.session() as session:
            if not session:
                return []
            stmt = (
                select(Items)
                .where(Items.status == WorkItemStatus.UNKNOWN)
                .options(selectinload(Items.metadata_item))
            )
            result = session.exec(stmt).all()
            for item in result:
                res.append(
                    ListItem(
                        **item.model_dump(exclude={"metadata_item"}),
                        **item.metadata_item.model_dump(exclude={"id"}),
                    )
                )

        return res
