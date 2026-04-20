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
    async def setup(self, *args, **kwargs) -> bool:
        pass

    @abstractmethod
    async def run(self) -> None:
        pass

    @abstractmethod
    def cancel(self) -> None:
        pass

    @abstractmethod
    def result(self):
        pass
