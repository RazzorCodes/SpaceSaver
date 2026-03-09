"""
An <Activity> handles a shoot-and-forget flow for a <sub-governor>.
"""

from abc import ABC, abstractmethod


class Activity(ABC):
    @property
    @abstractmethod
    def type(self) -> str:
        pass

    @property
    @abstractmethod
    def valid(self) -> bool:
        pass

    @abstractmethod
    def setup(self, *args, **kwargs) -> bool:
        pass

    @abstractmethod
    def run(self) -> None:
        pass

    @abstractmethod
    def cancel(self) -> None:
        pass

    @abstractmethod
    def result(self):
        pass
