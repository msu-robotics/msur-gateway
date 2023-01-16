from pydantic import BaseModel


class SensorsError(BaseModel):
    """Ошибки датчиков"""
    pressure: bool
    imu: bool


class Payload(BaseModel):
    """Состояние полезной нагрузки"""
    magnet_1: bool = False
    magnet_2: bool = False

    def __int__(self):
        return int(''.join([str(int(i)) for i in reversed([self.magnet_1,
            self.magnet_2, 0, 0, 0, 0, 0, 0])]), 2)


class Pid(BaseModel):
    """Состояние регуляторов вкл/выкл"""
    roll: bool = False
    pitch: bool = False
    depth: bool = False
    altitude: bool = False
    yaw: bool = False
    speed_x: bool = False
    speed_y: bool = False

    def __init__(self):
        super().__init__()

    def __int__(self):
        return int(''.join([str(int(i)) for i in reversed(
            [self.roll, self.pitch, self.depth, self.altitude, self.yaw,
             self.speed_x, self.speed_y, 0])]), 2)


class AUV(BaseModel):
    """Виртуальный AUV"""
    thrust_y: float = 0
    thrust_x: float = 0
    thrust_w: float = 0
    thrust_z: float = 0
    depth: float = 0
    altitude: float = 0
    yaw: float = 0
    velocity_x: float = 0
    velocity_y: float = 0
    pid: Pid = Pid()
    payload: Payload = Payload()
    navigation: bool = False

    def halt(self):
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
    pid: Pid
    payload: Payload
    leak: bool
    errors: SensorsError
    temperature: float
