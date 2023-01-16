import struct
from typing import Optional, Callable
from collections import OrderedDict

import asyncio
import asyncio_mqtt as aiomqtt
from queue import Queue
import logging
from src.models import AUV, Telemetry
from msur_crc.crc16 import crc16
import paho.mqtt.client as mqtt
import json


class Encoder:
    """Кодирует и декодирует сообщения для аппарата"""

    def __init__(self):
        self._telemetry = struct.Struct('!BBffffffffffffBBBBf')
        self._auv = struct.Struct('!BBbbbbfffffBBBffB')
        self._crc16 = struct.Struct('!H')

    def encode(self, obj) -> bytes:
        if isinstance(obj, AUV):
            package = self._auv.pack(0, 230, obj.thrust_x, obj.thrust_y,
                obj.thrust_z, obj.depth, obj.altitude, obj.yaw, obj.velocity_x,
                obj.velocity_y, int(obj.pid), int(obj.payload),
                obj.navigation, 0, 0, 0, 0)
            crc = self._crc16.pack(crc16(package))
            return package + crc
        else:
            raise ValueError('Не верный тип объекта')

    def decode(self, msg: bytes) -> Optional[Telemetry]:
        if len(msg) < 2:
            return
        crc = self._crc16.unpack(msg[-2:])[0]
        if crc != crc16(msg[:-2]):
            logging.info('crc error')
            return
        telemetry = self._telemetry.unpack(msg[:-2])[2:]
        bin_pid = '{0:08b}'.format(telemetry[12])
        pid = {
            'roll': bin_pid[-1], 'pitch': bin_pid[-2], 'depth': bin_pid[-3],
            'altitude': bin_pid[-4], 'yaw': bin_pid[-5], 'speed_x': bin_pid[-6],
            'speed_y': bin_pid[-7]
        }
        bin_payload = '{0:08b}'.format(telemetry[13])
        payload = {'magnet_1': bin_payload[-1], 'magnet_2': bin_payload[-2]}
        bin_errors = '{0:08b}'.format(telemetry[15])
        errors = {'pressure': bin_errors[-1], 'imu': bin_errors[-2]}
        return Telemetry(roll=telemetry[0], pitch=telemetry[1],
            yaw=telemetry[2], gyro_z=telemetry[3], depth=telemetry[4],
            altitude=telemetry[5], velocity_x=telemetry[6], pos_x=telemetry[8],
            velocity_y=telemetry[7], pos_y=telemetry[9], voltage=telemetry[10],
            current=telemetry[11], pid=pid, payload=payload, errors=errors,
            leak=telemetry[14], temperature=telemetry[16])


class DatagramProtocol:
    """Получает сообщение, публикует его в mqtt, отправляет ответ"""

    def __init__(self, producer: Callable, consumer: Callable,
            response_port: int):
        """

        :param producer: Возвращает сообщение которое необходимо отправить.
        :param consumer: Принимает сообщение пришедшее на сокет

        """
        self._producer = producer
        self._consumer = consumer
        self._transport = None
        self._port = response_port

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, message, addr):
        self._consumer(message)
        message = self._producer()
        self._transport.sendto(message, (addr[0], self._port))


class Gateway:
    """
    Сервис для взаимодействия с аппаратом
    """

    def __init__(self, mqtt_host, host, mqtt_port, port, telemetry_topik,
            control_topik):
        """

        Args:
            mqtt_host: Хост брокера mqtt
            host: Локальный интерфейс для связи с аппаратом
            mqtt_port: Порт брокера mqtt
            port: Локальный порт для связи с аппаратом
            telemetry_topik: Топик для публикации телеметрии
            control_topik: Топик для прослушивания управления
        """
        logging.info(f'Ожидание входящих пакетов на: {host}:{port}')
        logging.info(f'MQTT Broker: {mqtt_host}:{mqtt_port}')
        logging.info(f'Топик телеметрии: {telemetry_topik}')
        logging.info(f'Топик управления: {control_topik}')

        self._host = str(host)
        self._port = int(port)
        self._mqtt_host = mqtt_host
        self._mqtt_port = int(mqtt_port)
        self._control_topik = control_topik
        self._telemetry_topik = telemetry_topik

        self._transport = None

        self._queue = Queue()
        self._auv = AUV()
        self._encoder = Encoder()

        self._mqtt_client = mqtt.Client()
        self._mqtt_client.connect(mqtt_host, self._mqtt_port)

        self._package_counter = 0

    def _control(self, control: dict):
        if control.get('type', 0) == 230:
            if 'thrust_x' in control:
                self._auv.thrust_x = float(control['thrust_x'])
            if 'thrust_y' in control:
                self._auv.thrust_y = float(control['thrust_y'])
            if 'thrust_z' in control:
                self._auv.thrust_z = float(control['thrust_z'])
            if 'thrust_w' in control:
                self._auv.thrust_w = float(control['thrust_w'])
            if 'depth' in control:
                self._auv.depth = float(control['depth'])
            if 'altitude' in control:
                self._auv.altitude = float(control['altitude'])
            if 'yaw' in control:
                self._auv.yaw = float(control['yaw'])
            if 'velocity_x' in control:
                self._auv.velocity_x = float(control['velocity_x'])
            if 'velocity_y' in control:
                self._auv.velocity_y = float(control['velocity_y'])
            if 'pid' in control:
                pid = control['pid']
                if 'yaw' in pid:
                    self._auv.pid.yaw = bool(pid['yaw'])
                if 'pitch' in pid:
                    self._auv.pid.pitch = bool(pid['pitch'])
                if 'roll' in pid:
                    self._auv.pid.roll = bool(pid['roll'])
                if 'speed_x' in pid:
                    self._auv.pid.speed_x = bool(pid['speed_x'])
                if 'speed_y' in pid:
                    self._auv.pid.speed_y = bool(pid['speed_y'])
                if 'altitude' in pid:
                    self._auv.pid.altitude = bool(pid['altitude'])
                if 'depth' in pid:
                    self._auv.pid.depth = bool(pid['depth'])
            if 'payload' in control:
                payload = control['payload']
                if 'magnet_1' in payload:
                    self._auv.payload.magnet_1 = bool(payload['magnet_1'])
                if 'magnet_2' in payload:
                    self._auv.payload.magnet_2 = bool(payload['magnet_2'])
        elif control.get('type', 0) == 110:
            pass

    async def _mqtt_subscriber(self):
        """Обрабатывает сообщения из auv/control и обновляет состояние аппарата
        """
        async with aiomqtt.Client(self._mqtt_host, self._mqtt_port) as client:
            async with client.messages() as messages:
                await client.subscribe(self._control_topik)
                async for message in messages:
                    # обновить глобальное состояние
                    try:
                        control: dict = json.loads(message.payload.decode())
                        self._control(control)
                    except json.JSONDecodeError:
                        logging.error('Ошибка декодирования сообщения: %s',
                            message.payload)
                        self._auv.halt()
                    except ValueError:
                        logging.error('Ошибка приведения типа: %s', control)
                        self._auv.halt()

    def _get_package(self) -> bytes:
        """Возвращает пакет управления для аппарата"""
        return self._encoder.encode(self._auv)

    def _publish_package(self, msg: bytes):
        """Получает телеметрию с аппарата"""
        telemetry = self._encoder.decode(msg)
        if telemetry:
            self._mqtt_client.publish(self._telemetry_topik, telemetry.dict())

    def get_protocol(self):
        return DatagramProtocol(self._get_package, self._publish_package, 2030)

    async def run(self):
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(self.get_protocol,
            local_addr=(self._host, self._port))

        self._transport = transport

        await self._mqtt_subscriber()

    def close(self):
        if self._transport is not None:
            self._transport.close()
