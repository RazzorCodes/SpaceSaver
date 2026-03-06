"""
An <Activity> handles a shoot-and-forget flow for a <sub-governor>.
"""

from abc import ABC, abstractmethod


class Activity(ABC):
    @property
    @abstractmethod
    def valid(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def setup(self, *args, **kwargs) -> bool:
        pass

    @abstractmethod
    def run(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def cancel(self) -> None:
        raise NotImplementedError
