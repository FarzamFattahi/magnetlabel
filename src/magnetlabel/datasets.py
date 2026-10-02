"""Independent local datasets, preserving the original project as a legacy entry."""

import json
import threading
import uuid
from pathlib import Path

from .store import Store


class Datasets:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = self.root / "datasets.json"
        self.lock = threading.RLock()
        if self.index.exists():
            self.entries = json.loads(self.index.read_text(encoding="utf-8"))
        else:
            self.entries = {"active": "original", "datasets": {"original": "."}}
            self._persist()
        self.stores = {}
        self.get()

    def _persist(self):
        temporary = self.index.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")
        temporary.replace(self.index)

    def get(self, dataset_id: str | None = None) -> Store:
        with self.lock:
            dataset_id = dataset_id or self.entries["active"]
            if dataset_id not in self.entries["datasets"]:
                raise KeyError("Dataset not found.")
            if dataset_id not in self.stores:
                path = (self.root / self.entries["datasets"][dataset_id]).resolve()
                if not path.is_relative_to(self.root):
                    raise ValueError("Dataset path must stay inside the workspace.")
                self.stores[dataset_id] = Store(path)
            return self.stores[dataset_id]

    def identifier(self, store: Store) -> str:
        with self.lock:
            return next(key for key, value in self.stores.items() if value is store)

    def listing(self):
        with self.lock:
            return [
                {"id": key, "name": self.get(key).project()["name"]}
                for key in self.entries["datasets"]
            ]

    def create(self, name: str, classes: list[str]):
        with self.lock:
            dataset_id = uuid.uuid4().hex
            store = Store(self.root / "projects" / dataset_id)
            store.configure(name, classes)
            self.entries["datasets"][dataset_id] = f"projects/{dataset_id}"
            self.entries["active"] = dataset_id
            self.stores[dataset_id] = store
            self._persist()
            return dataset_id, store

    def activate(self, dataset_id: str):
        with self.lock:
            store = self.get(dataset_id)
            self.entries["active"] = dataset_id
            self._persist()
            return store
