from enum import IntEnum
from typing import Set, Optional

from pydantic import BaseModel, Field


class UpdatableBase(BaseModel):
    """Позволяет обновлять атрибуты объекта словарем с параметрами"""

    _updated: bool = False

    def _update_list(self, attr: str, values: dict, cls=None):
        # todo: Это необходимо справить, сделать универсальное решение

        instance = PidSettings(**values)
        for item in getattr(self, attr):
            if item.type == instance.type:
                item.update(values)
                item.need_update = True
                break
        else:
            getattr(self, attr).append(instance)

    def update(self, values: dict):
        for key, val in values.items():
            if isinstance(val, dict):
                getattr(self, key).update(val)
            elif isinstance(val, list):
                for item in val:
                    self._update_list(key, item)
            elif key in self.__dict__:
                setattr(self, key, val)
                self._updated = True
            else:
                raise AttributeError(f'not found: {self.__class__}.{key}')

    @property
    def need_update(self):
        return self._updated

    @need_update.setter
    def need_update(self, val: bool):
        self._updated = val

    class Config:
        extra = 'allow'


class SensorsError(BaseModel):
    """Ошибки датчиков"""
    pressure: bool
    imu: bool


class Payload(BaseModel):
    """Состояние полезной нагрузки"""
    magnet_1: bool = Field(False, title='Полезная нагрузка 1',
        description='Вкл/выкл полезную нагрузку 1')
    magnet_2: bool = Field(False, title='Полезная нагрузка 2',
        description='Вкл/выкл полезную нагрузку 2')

    def __int__(self):
        return int(''.join([str(int(i)) for i in reversed(
            [self.magnet_1, self.magnet_2, 0, 0, 0, 0, 0, 0])]), 2)


class PidStatus(UpdatableBase):
    """Состояние регуляторов"""
    roll: bool = Field(False, title='Состояние регулятора крена',
        description='Вкл/выкл регулятор')
    pitch: bool = Field(False, title='Состояние регулятора дифферента',
        description='Вкл/выкл регулятор')
    depth: bool = Field(False, title='Состояние регулятора глубины',
        description='Вкл/выкл регулятор')
    altitude: bool = Field(False, title='Состояние регулятора высоты',
        description='Вкл/выкл регулятор')
    yaw: bool = Field(False, title='Состояние регулятора курса',
        description='Вкл/выкл регулятор')
    speed_x: bool = Field(False, title='Состояние регулятора скорости по Х',
        description='Вкл/выкл регулятор')
    speed_y: bool = Field(False, title='Состояние регулятора ',
        description='Вкл/выкл регулятор')

    def __int__(self):
        return int(''.join([str(int(i)) for i in reversed(
            [self.roll, self.pitch, self.depth, self.altitude, self.yaw,
             self.speed_x, self.speed_y, 0])]), 2)


class PidType(IntEnum):
    DEPTH = 110
    ALTITUDE = 111
    ROLL = 112
    PITCH = 113
    YAW = 114
    VELOCITY_X = 115
    VELOCITY_Y = 116
    GYRO_P = 117


class PidSettings(UpdatableBase):
    """Настройка регулятора"""
    type: PidType
    p: float = Field(title='Пропорциональная составляющая')
    i: float = Field(title='Интегральная составляющая')
    d: float = Field(title='Дифференциальная составляющая')

    def __hash__(self):
        return hash(self.type)


class PidConfig(UpdatableBase):
    """Конфигурация системы ПИД регуляторов, состояние и конфигурация"""
    status: PidStatus = PidStatus()
    settings: Set[Optional[PidSettings]] = []

    saved: bool = Field(True, title='Состояние настроек ПИД регуляторов',
        description='Сохранена ли текущая конфигурация')


class AUV(UpdatableBase):
    """Виртуальный AUV"""
    thrust_y: int = Field(0, title='Тяга по Y',
        ge=0, le=100)
    thrust_x: int = Field(0, title='Тяга по X',
        ge=0, le=100)
    thrust_w: int = Field(0, title='Тяга по W',
        ge=0, le=100)
    thrust_z: int = Field(0, title='Тяга по Z',
        ge=0, le=100)
    depth: float = Field(0, title='Уставка по глубине',
        description='Задается в метрах')
    altitude: float = Field(0, title='Уставка по высоте',
        description='Задается в метрах')
    yaw: float = Field(0, title='Уставка по курсу',
        description='Задается в градусах')
    velocity_x: float = Field(0, title='Скорость по X')
    velocity_y: float = Field(0, title='Скорость по Y')
    pid: PidConfig = PidConfig()
    payload: Payload = Payload()
    navigation: bool = Field(False, title='Отсчет локальной системы координат',
        description='Вкл/выкл локальную систему координат')

    def halt(self):
        """"Экстренная остановка аппарата"""
        self.thrust_x = 0
        self.thrust_y = 0
        self.thrust_w = 0
        self.thrust_z = 0
        self.pid.yaw = False
        self.pid.pitch = False
        self.pid.roll = False
        self.pid.depth = False
        self.pid.altitude = False
        self.pid.speed_x = False
        self.pid.speed_y = False

    def get_parcel(self):
        """Возвращает объект для отправки на аппарат"""
        for pid_setting in self.pid.settings:
            if pid_setting._updated:
                pid_setting._updated = False
                return pid_setting
        return self


class Telemetry(BaseModel):
    roll: float
    pitch: float
    yaw: float
    gyro_z: float
    depth: float
    altitude: float
    velocity_x: float
    velocity_y: float
    pos_x: float
    pos_y: float
    voltage: float
    current: float
    pid: PidStatus
    payload: Payload
    leak: bool
    errors: SensorsError
    temperature: float
