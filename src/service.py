import asyncio
import json
import logging
import struct
from typing import Optional, Callable

import asyncio_mqtt as aiomqtt
import paho.mqtt.client as mqtt
from msur_crc.crc16 import crc16
from rich.console import Console

from src.models import AUV, Telemetry, PidSettings, PidConfig, PidStatus

console = Console()


class Encoder:
    """Кодирует и декодирует сообщения для аппарата"""

    def __init__(self):
        self._telemetry = struct.Struct('!BBffffffffffffBBBBf')
        self._auv = struct.Struct('!BBbbbbfffffBBBffB')
        self._crc16 = struct.Struct('!H')
        self._pid = struct.Struct('!BBfff')
        self._reboot = struct.Struct('!BBBBBBBB')

    def encode(self, obj) -> bytes:
        if isinstance(obj, AUV):
            values = [0, 230, obj.thrust_x, obj.thrust_y, obj.thrust_w,
                      obj.thrust_z, obj.depth, obj.altitude, obj.yaw,
                      obj.velocity_x, obj.velocity_y, int(obj.pid.status),
                      int(obj.payload), int(obj.navigation), 0, 0, 0]
            # print(values)
            package = self._auv.pack(*values)
        elif isinstance(obj, PidSettings):
            # обновляем коэффициент
            values = [0, obj.type, obj.p, obj.i, obj.d]
            package = self._pid.pack(*values)
        elif isinstance(obj, PidConfig):
            # сохраняем настройки ПИД
            package = self._reboot.pack(0, 133, 0, 0, 0, 1, 0, 0)
        else:
            raise ValueError('Не верный тип объекта')

        crc = self._crc16.pack(crc16(package))
        return package + crc

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

    def __init__(self, mqtt_host, host, mqtt_port, port, auv_topik):
        """

        Args:
            mqtt_host: Хост брокера mqtt
            host: Локальный интерфейс для связи с аппаратом
            mqtt_port: Порт брокера mqtt
            port: Локальный порт для связи с аппаратом
            auv_topik: Топик для AUV
        """
        console.rule("[bold red]MSUR GATEWAY")

        console.print(
            f"[blue]Ожидание входящих пакетов на: [bold red]{host}:{port}")
        console.print(
            f"[blue]MQTT Broker: [bold red]{mqtt_host}:{mqtt_port}")
        console.print(
            f"[blue]Топик телеметрии: [bold red]{auv_topik}/telemetry")
        console.print(
            f"[blue]Топик управления: [bold red]{auv_topik}/control")
        console.print(
            f"[blue]Топик информации: [bold red]{auv_topik}/info")
        console.rule("[bold red]Форматы сообщений")
        console.print(
            f"[blue]Управление AUV:")
        console.print(AUV.schema())

        self._host = str(host)
        self._port = int(port)
        self._mqtt_host = mqtt_host
        self._mqtt_port = int(mqtt_port)
        self._control_topik = auv_topik + '/control'
        self._telemetry_topik = auv_topik + '/telemetry'
        self._info_topik = auv_topik + '/info'

        self._transport = None

        self._auv = AUV()
        self._encoder = Encoder()

        self._mqtt_client = mqtt.Client()
        self._mqtt_client.connect(mqtt_host, self._mqtt_port)

        self._package_counter = 0

    def _control(self, control: dict):
        try:
            self._auv.update(control)
        except AttributeError:
            console.print_exception()

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
        return self._encoder.encode(self._auv.get_parcel())

    def _publish_package(self, msg: bytes):
        """Получает телеметрию с аппарата"""
        telemetry = self._encoder.decode(msg)
        if telemetry:
            self._mqtt_client.publish(self._telemetry_topik, telemetry.json())

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
