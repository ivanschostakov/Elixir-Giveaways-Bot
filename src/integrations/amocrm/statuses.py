from dataclasses import dataclass


@dataclass
class WonStatuses:
    __init_data: dict[str, int]

    def __post_init__(self): [setattr(self, key, value) for key, value in self.__init_data.items()]

    @property
    def to_list(self) -> list[int]: return self.__init_data.values()

    @property
    def inverted(self) -> dict[int, str]: return {value: key for key, value in self.__init_data.items()}

    def get_status_key(self, status_id: int): return self.inverted.get(status_id, None)

@dataclass
class LossStatuses:
    __init_data: dict[str, int]

    def __post_init__(self): [setattr(self, key, value) for key, value in self.__init_data.items()]

    @property
    def to_list(self) -> list[int]: return self.__init_data.values()

    @property
    def inverted(self) -> dict[int, str]: return {value: key for key, value in self.__init_data.items()}

    def get_status_key(self, status_id: int): return self.inverted.get(status_id, None)
